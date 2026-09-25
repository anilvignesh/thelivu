"""Attended corpus extraction — the seam, and the check it must never relax.

    python -m shared.tests.run_attend_corpus_cases

No API key, no network: a throwaway SQLite file, a fixture document, and
request/response files written into a temporary directory.

What this is FOR. Attended mode puts the assistant where the model was, and the
temptation that comes with that is to treat its output as already trustworthy —
it read the text, after all, so why re-check the quote. The answer is that
`_grounded()` does not test honesty, it tests whether a span is in the
document, and a reader working from a chunk it half-remembers produces exactly
the same artefact as a model reciting training data: a plausible figure,
attached to a real-sounding department, that nobody can find afterwards.

Anil's standard, 2026-09-08: *"we make sure there is no hallucination, for us
facts should also be correct."* The grounding check is where that is enforced
for the corpus, and it has to hold against every producer of findings, this
session included.

The second property here is quieter and matters as much: an `external` cause
survives extraction intact. Karnataka's flood damage must reach the findings
table LABELLED, not dropped and not laundered into 'state' — `state_findings()`
is what keeps it out of a synthesis, and it can only do that if the label is
recorded honestly upstream.
"""
import json
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from pathlib import Path                            # noqa: E402

from engine import attend_corpus                    # noqa: E402

# The real batch directory is REPO_ROOT/.attend/corpus and may hold a session's
# unanswered work. A test that cleared it would destroy a human's half-finished
# reading, so this points the module at a scratch directory instead.
_TMPDIR = Path(tempfile.mkdtemp(prefix="attend-corpus-test-"))
attend_corpus._dir = lambda: _TMPDIR
from shared.db import (                             # noqa: E402
    init_db, store_document, state_findings, findings_stats,
)

FAILURES = []

DOC_SHA = "a" * 64
DOC_TEXT = (
    "Report of the Comptroller and Auditor General of India for the year "
    "ended 31 March 2024, Government of Testland.\n\n"
    "The Department made an irregular salary payment of Rs 3.88 crore to an "
    "Associate professor and eight regular professors who did not perform "
    "their official duty.\n\n"
    "Flood damage to standing crops and rural infrastructure during the 2023 "
    "monsoon was assessed at Rs 9,781 crore across eleven districts.\n\n"
    "The Horticulture Department could not recover the interest-free "
    "outstanding loan of Rs 85.00 lakh from two Societies.\n"
)


DOC2_SHA = "b" * 64
DOC2_TEXT = (
    "Report of the Comptroller and Auditor General of India for the year "
    "ended 31 March 2024, Government of Otherland.\n\n"
    "The Public Works Department left Rs 12.40 crore parked in a civil deposit "
    "account for four years without executing any work.\n"
)


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def write_response(rid, payload):
    d = attend_corpus._dir()
    (d / f"{rid}.response.md").write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8")


def main():
    print("attend_corpus")
    init_db()
    store_document(DOC_SHA, "https://example.gov/report.pdf", DOC_TEXT,
                   title="Testland audit 2024", source_key="cag-testland",
                   published="2024")

    # ── 1. a batch is written, and it carries the contract ──────────────────
    m = attend_corpus.prepare(docs=1, chunks_per_doc=2)
    check("a request was written", len(m["entries"]) >= 1, str(m["entries"]))
    rid = m["entries"][0]["rid"]
    req = (attend_corpus._dir() / f"{rid}.request.md").read_text(encoding="utf-8")
    check("the request carries the document text",
          "irregular salary payment" in req)
    check("the request states the cause contract", '"external"' in req)
    check("the request names its own response file",
          f"{rid}.response.md" in req)

    # ── 2. an unanswered request is reported, never assumed empty ───────────
    st = attend_corpus.status()
    check("waiting requests are counted",
          st["batch"]["waiting"] == len(m["entries"]), str(st))

    # ── 3. THE CHECK. A quote that is not in the text does not get stored. ──
    write_response(rid, [
        {"claim": "a real finding",
         "excerpt": "The Department made an irregular salary payment of Rs 3.88 "
                    "crore to an Associate professor and eight regular professors",
         "amount_cr": 3.88, "category": "irregular", "cause": "state"},
        {"claim": "a figure this document never states",
         "excerpt": "The Department failed to recover Rs 4,271 crore advanced to "
                    "seventeen cooperative societies over nine years.",
         "amount_cr": 4271, "category": "recovery", "cause": "state"},
    ])
    r = attend_corpus.ingest()
    check("the grounded finding is kept", r["findings"] == 1, str(r))
    check("the invented figure is refused", r["dropped_ungrounded"] == 1, str(r))
    stored = state_findings()
    check("nothing invented reached the corpus",
          not any((f["amount_cr"] or 0) == 4271 for f in stored),
          str([f["amount_cr"] for f in stored]))
    check("the attended pass is labelled as such",
          all(f.get("status") == "new" for f in stored))

    # ── 4. reflowed whitespace is still the same quote ──────────────────────
    # `only_sha`, because the document stopped being "pending" the moment the
    # first finding landed. Guarding these phases with `if entries:` instead
    # would skip them silently — the same quiet pass that hid a broken case in
    # run_digger_cases for days.
    m2 = attend_corpus.prepare(docs=1, chunks_per_doc=1, only_sha=DOC_SHA)
    check("a read document can be re-opened", bool(m2["entries"]), str(m2))
    if m2["entries"]:
        rid2 = m2["entries"][0]["rid"]
        write_response(rid2, [
            {"claim": "quoted with different line breaks",
             "excerpt": "The Horticulture Department could not recover\n   the "
                        "interest-free    outstanding loan of Rs 85.00 lakh from "
                        "two Societies.",
             "amount_cr": 0.85, "category": "recovery", "cause": "state"},
        ])
        r2 = attend_corpus.ingest()
        check("a reflowed quote is still grounded",
              r2["dropped_ungrounded"] == 0, str(r2))

    # ── 5. an external cause survives, labelled ─────────────────────────────
    # It must NOT be dropped here. Dropping it would lose the row that
    # state_findings() exists to exclude, and a later reader would have no way
    # to tell "we judged this a misfortune" from "we never saw it".
    m3 = attend_corpus.prepare(docs=1, chunks_per_doc=1, only_sha=DOC_SHA)
    check("the external-cause phase has a request", bool(m3["entries"]))
    if m3["entries"]:
        rid3 = m3["entries"][0]["rid"]
        write_response(rid3, [
            {"claim": "flood damage to crops and rural infrastructure",
             "excerpt": "Flood damage to standing crops and rural infrastructure "
                        "during the 2023 monsoon was assessed at Rs 9,781 crore "
                        "across eleven districts.",
             "amount_cr": 9781, "category": "other", "cause": "external"},
        ])
        r3 = attend_corpus.ingest()
        check("an external finding is stored, not dropped",
              r3["findings"] == 1 and r3["by_cause"].get("external") == 1, str(r3))
        total, by_cause, _cr = findings_stats()
        check("it is recorded as external", by_cause.get("external") == 1,
              str(by_cause))
        check("and it stays out of the synthesise tier",
              not any((f["amount_cr"] or 0) == 9781 for f in state_findings()))

    # ── 5b. ingesting twice must not store twice ────────────────────────────
    # store_findings has no dedup key on purpose — the same claim in two
    # documents is two findings, and collapsing them would destroy the
    # recurring-objection signal. The cost is that ingest is not idempotent,
    # and the natural rhythm (answer some, ingest, answer more, ingest) walks
    # right into it. Answered responses are archived after a successful store.
    before = len(state_findings())
    again = attend_corpus.ingest()
    check("a second ingest finds nothing left to store",
          again["findings"] == 0 and again["answered"] == 0, str(again))
    check("and the corpus did not grow", len(state_findings()) == before,
          f"{before} -> {len(state_findings())}")

    # ── 6. prose instead of JSON costs that chunk and nothing else ──────────
    m4 = attend_corpus.prepare(docs=1, chunks_per_doc=1, only_sha=DOC_SHA)
    check("the unparseable phase has a request", bool(m4["entries"]))
    if m4["entries"]:
        write_response(m4["entries"][0]["rid"],
                       "I could not find anything useful in this chunk, sorry.")
        r4 = attend_corpus.ingest()
        check("an unparseable answer is counted, not stored",
              r4["unparseable"] == 1 and r4["findings"] == 0, str(r4))

    # ── 7. --keep ADDS to the batch, and ingest sees all of it ──────────────
    # Breadth is the whole point of the attended pass: the detectors need the
    # same category across many states in one year, and one prepare call only
    # ever covers one document. --keep kept the request FILES and overwrote the
    # manifest, which is the only thing ingest reads — so every earlier request
    # sat answered on disk and was never ingested, and the counts reported a
    # clean small batch rather than a lost large one.
    store_document(DOC2_SHA, "https://example.gov/other.pdf", DOC2_TEXT,
                   title="Otherland audit 2024", source_key="cag-otherland",
                   published="2024")
    a = attend_corpus.prepare(chunks_per_doc=1, only_sha=DOC_SHA)
    b = attend_corpus.prepare(chunks_per_doc=1, only_sha=DOC2_SHA, fresh=False)
    check("--keep adds to the batch rather than replacing it",
          len(b["entries"]) == len(a["entries"]) + 1, str(b["entries"]))
    check("and it reports what THIS call added",
          b.get("written_now") == 1, str(b.get("written_now")))
    again = attend_corpus.prepare(chunks_per_doc=1, only_sha=DOC2_SHA,
                                  fresh=False)
    check("a chunk already in the batch is not queued twice",
          again.get("written_now") == 0 and
          len(again["entries"]) == len(b["entries"]), str(again["entries"]))

    for e in b["entries"]:
        if e["sha256"] == DOC_SHA:
            write_response(e["rid"], [
                {"claim": "kept from the earlier prepare",
                 "excerpt": "The Horticulture Department could not recover the "
                            "interest-free outstanding loan of Rs 85.00 lakh "
                            "from two Societies.",
                 "amount_cr": 0.85, "category": "recovery", "cause": "state"}])
        else:
            write_response(e["rid"], [
                {"claim": "from the document added by --keep",
                 "excerpt": "The Public Works Department left Rs 12.40 crore "
                            "parked in a civil deposit account for four years "
                            "without executing any work.",
                 "amount_cr": 12.40, "category": "idle", "cause": "state"}])
    r7 = attend_corpus.ingest()
    check("every request in the batch is ingested, not just the last prepare's",
          r7["answered"] == 2 and r7["findings"] == 2, str(r7))
    check("nothing was dropped from the kept batch",
          r7["dropped_ungrounded"] == 0, str(r7))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all attend_corpus cases passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            os.unlink(_TMPDB.name)
        except OSError:
            pass
