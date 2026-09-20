"""The synthesise tier — what the corpus says ACROSS documents.

    python -m shared.tests.run_synthesis_cases

No API key, no network: a throwaway SQLite file and fixture findings, so the DB
writes are real and nothing else is.

What this is FOR is the property that makes this tier safe to run at all:

  **A misfortune must never become a failure.** The first scan of this corpus
  returned three flood-damage figures in its top eight results, presented
  exactly like governance failures — huge numbers, in audit reports, next to the
  word "loss". Karnataka's ₹97,814 crore of flood damage is not a scandal;
  Punjab's ₹33,973 crore advanced against ₹1,422 crore recovered is. Nothing
  mechanical tells them apart, so `cause` is committed to at extraction time and
  the synthesise tier reads `state` rows ONLY.

  A ten-year "pattern" assembled out of monsoons would be wrong in public, in
  our own voice, with a citation. That is the single worst output this system
  can produce, and the filter that prevents it is one WHERE clause — exactly the
  kind of thing a later refactor drops without noticing.

The other invariant here: every synthesis names the finding ids it rests on. A
claim that cannot produce its evidence is an opinion, and at read time it would
be indistinguishable from one backed by twelve quoted documents.
"""
import os
import sys
import tempfile

# BEFORE any shared.* import — shared.config reads DATABASE_URL at import time,
# and a developer with the production URL exported is the normal state.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from engine import synthesis                      # noqa: E402
from shared import jurisdiction as juris          # noqa: E402
from shared.db import (                           # noqa: E402
    init_db, store_findings, store_document, state_findings, corpus_coverage,
    store_synthesis, syntheses, set_synthesis_status,
)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def finding(source_key, year, category, amount, cause="state", claim=None,
            excerpt="verbatim span from the document"):
    return {
        "doc_sha256": f"sha-{source_key}-{year}",
        "source_key": source_key, "published": str(year), "category": category,
        "amount_cr": amount, "cause": cause,
        "claim": claim or f"{category} of {amount} crore in {year}",
        "excerpt": excerpt, "model": "fixture",
    }


def main():
    print("synthesis")
    init_db()
    j = juris.load("india")

    # ── the corpus we are pretending to hold ────────────────────────────────
    rows = []
    # Kerala: the same objection six years running, never resolved.
    for y in range(2015, 2021):
        rows.append(finding("cag-kerala", y, "recovery", 100 + y - 2015))
    # Punjab: a figure that worsens every year.
    for y, amt in ((2018, 1000), (2019, 2000), (2020, 4000)):
        rows.append(finding("cag-punjab", y, "idle", amt))
    # A structural failure in 2019: ten states, same category.
    for slug in ("bihar", "assam", "odisha", "goa", "gujarat", "haryana",
                 "jharkhand", "manipur", "tripura", "sikkim"):
        rows.append(finding(f"cag-{slug}", 2019, "non-compliance", 50))
    # Karnataka: FLOODS. Enormous, in an audit report, and not a failure.
    for y in range(2015, 2021):
        rows.append(finding("cag-karnataka", y, "recovery", 97814,
                            cause="external",
                            claim="flood damage to crops and infrastructure"))
    # Telangana: one large finding, never named again, and we DO hold later
    # reports for it.
    rows.append(finding("cag-telangana", 2016, "diversion", 7777))
    # Rajasthan: one large finding, and we hold NO later report — absence here
    # is our ignorance, not the auditor's silence.
    rows.append(finding("cag-rajasthan", 2016, "diversion", 8888))

    store_findings(rows)
    for key, years in (("cag-telangana", (2016, 2019, 2020)),
                       ("cag-rajasthan", (2016,))):
        for y in years:
            store_document(f"sha-{key}-{y}", f"https://example/{key}/{y}",
                           "text of the report", source_key=key, published=str(y))

    # ── 1. the flood rule ───────────────────────────────────────────────────
    loaded = state_findings()
    check("state_findings excludes external causes",
          all(r["cause"] == "state" for r in loaded),
          str({r["cause"] for r in loaded}))
    check("the flood rows are in the corpus at all",
          len(rows) > len(loaded), "fixture must contain external rows to test")

    prepared = synthesis.prepare(loaded, j)
    found = synthesis.run(store=True)
    claims = " ".join(s["claim"] for s in found).lower()
    check("no synthesis mentions Karnataka", "karnataka" not in claims)
    check("no synthesis carries the flood figure", "97,814" not in claims)

    # ── 2. every synthesis cites its evidence ───────────────────────────────
    ids = {r["id"] for r in loaded}
    check("every synthesis has evidence", all(s["evidence"] for s in found))
    check("all evidence ids are real findings",
          all(set(s["evidence"]) <= ids for s in found))
    try:
        store_synthesis("recurring", "a claim with nothing behind it", [])
        check("a synthesis with no evidence is refused", False)
    except ValueError:
        check("a synthesis with no evidence is refused", True)

    # ── 3. recurring ────────────────────────────────────────────────────────
    rec = [s for s in found if s["kind"] == "recurring"]
    kerala = [s for s in rec if s["entities"] == ["Kerala"]]
    check("Kerala's six-year objection is found", len(kerala) == 1,
          str([s["claim"] for s in rec]))
    if kerala:
        check("it reports six consecutive years",
              len(kerala[0]["years"]) == 6, str(kerala[0]["years"]))
    check("two years is not a pattern",
          not any(len(s["years"]) < synthesis.MIN_CONSECUTIVE_YEARS for s in rec))
    check("a gap breaks a run",
          synthesis._consecutive_runs([2011, 2012, 2013, 2016]) ==
          [[2011, 2012, 2013], [2016]])

    # ── 4. structural ───────────────────────────────────────────────────────
    st = [s for s in found if s["kind"] == "structural"]
    check("the ten-state failure is found", len(st) == 1, str(len(st)))
    if st:
        check("it counts ten entities", len(st[0]["entities"]) == 10,
              str(st[0]["entities"]))
        check("it stores the denominator it was true against",
              st[0]["peer_count"] == j.peer_count,
              f"{st[0]['peer_count']} vs {j.peer_count}")
        check("the claim states both numbers",
              f"of {j.peer_count}" in st[0]["claim"], st[0]["claim"])

    # ── 5. no follow-through, and the ignorance it must not claim ───────────
    nf = [s for s in found if s["kind"] == "no-follow-through"]
    ents = {e for s in nf for e in s["entities"]}
    check("Telangana's unfollowed figure is found", "Telangana" in ents, str(ents))
    check("Rajasthan is NOT claimed — we hold no later report",
          "Rajasthan" not in ents,
          "absence of evidence reported as evidence of absence")

    # ── 6. wrong direction ──────────────────────────────────────────────────
    wd = [s for s in found if s["kind"] == "wrong-direction"]
    check("Punjab's worsening figure is found",
          any(s["entities"] == ["Punjab"] for s in wd), str([s["claim"] for s in wd]))
    check("the claim does not invent an assurance",
          not any("assur" in s["claim"].lower() for s in wd))
    check("Kerala's flat series is not called a trend",
          not any(s["entities"] == ["Kerala"] for s in wd))

    # ── 7. re-running updates rather than duplicates ────────────────────────
    before = len(syntheses(limit=500))
    synthesis.run(store=True)
    after = len(syntheses(limit=500))
    check("a second pass files no duplicates", before == after,
          f"{before} -> {after}")

    # ── 8. triage ───────────────────────────────────────────────────────────
    stored = syntheses(limit=500)
    check("stored syntheses start as new",
          all(s["status"] == "new" for s in stored))
    if stored:
        set_synthesis_status(stored[0]["id"], "promoted")
        check("a person can promote one",
              len(syntheses(status="promoted")) == 1)

    # ── 9. the dossier a person reads ───────────────────────────────────────
    if kerala:
        text = synthesis.draft_dossier(kerala[0])
        check("the dossier quotes the documents",
              "verbatim span from the document" in text)
        check("the dossier names the finding ids",
              all(f"[{i}]" in text for i in kerala[0]["evidence"][:3]))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print(f"all synthesis cases passed ({len(found)} syntheses from "
          f"{len(prepared)} placed findings)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            os.unlink(_TMPDB.name)
        except OSError:
            pass
