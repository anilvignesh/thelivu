"""Reading the corpus attended — the session does the extraction, not the API.

Anil, 2026-09-20: *"forget the budget, we will increase it and try to run
maximum via the attended mode."*

`analyst.py` reads a document by calling Haiku once per 18,000-character chunk.
A 258-page audit report is roughly thirty chunks, and there are hundreds of
reports. This runs the same extraction with the assistant in an interactive
session in the model's place, so the pass costs nothing and is bounded by
attention rather than by credit.

**WHY THIS IS NOT `engine/attend.py`'s existing loop.** That seam writes one
request and BLOCKS until its response appears, which is right for a pipeline of
a dozen skill calls and impossible for a few thousand chunks. This writes a
BATCH of requests, the session answers them all, and a second command ingests
them. Same seam, different granularity.

**WHAT DOES NOT CHANGE, and must not.** `dx._grounded()` still runs on every
finding, against the chunk it came from. That check is the single most valuable
thing in the extraction package — it is exactly how a confident model smuggles
training-data recall into a "finding" — and it is not less necessary when the
model is the assistant. A quote that is not in the text does not enter the
corpus, whoever produced it.

The `cause` contract is unchanged too: state / external / unclear, committed to
per finding, never guessed. Karnataka's flood damage is `external` no matter
how large the number.

    python -m engine.attend_corpus prepare --docs 3        # write requests
    (the session writes each NNN.response.md)
    python -m engine.attend_corpus ingest                  # validate and store
    python -m engine.attend_corpus status

⚠️ HUMAN-OPERATED, like the rest of attended mode. Legitimate because Anil is
driving his own session on his own project; never from cron, never unattended.
See docs/attended-mode.md.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from engine import analyst

log = logging.getLogger("attend.corpus")

DIR_NAME = ".attend/corpus"
MANIFEST = "manifest.json"
# Chunks written per document per batch. The whole report is not written at
# once on purpose: thirty chunks of one state is a worse batch than three
# chunks of ten states, because the detectors need breadth before depth.
DEFAULT_CHUNKS = 4
DEFAULT_DOCS = 3


def _dir():
    from shared.config import REPO_ROOT
    d = Path(REPO_ROOT) / DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


REQUEST_TEMPLATE = """# corpus extraction — {where}, {year}

request `{rid}`   document `{sha12}`   chunk {n} of {total}

Write your answer to **`{response_name}`** in this directory. A JSON array and
nothing else — no prose around it, no code fence needed.

## The contract

Extract only findings where a PUBLIC BODY did or failed to do something.

```
claim     one sentence, your own words, naming who and what
excerpt   a VERBATIM span copied exactly from the text below, 15-40 words,
          containing the evidence. Never paraphrase it.
amount_cr the rupee figure in CRORE as a number, or null
category  one of: {cats}
cause     "state"    an act or omission of government
          "external" a flood, drought, epidemic or other outside event
          "unclear"  you cannot tell from this text
```

A flood damaging crops is `external` even when the amount is enormous. Money
advanced and not recovered is `state`. If unsure, say `unclear` — do not guess.

**Every excerpt is checked against the text below before it is stored.** A
quote that is not literally there is dropped on ingest, and the drop is
reported. Copy spans; do not reconstruct them from memory.

Return `[]` if nothing in this chunk qualifies. That is a normal answer — most
chunks of an audit report are tables of contents, annexure headings and
procedural boilerplate.

## TEXT

```
{text}
```
"""


def pending_documents(limit=None):
    """Corpus documents with no findings yet, largest first.

    `documents_without_findings()` returns (sha256, source_key, published,
    chars) TUPLES and deliberately omits the text — a 561,598-character report
    per row makes a listing query unusable — so the text is fetched per
    document when its requests are written.

    Largest first, reversing that accessor's own order: a long report is a
    report with annexures, and the annexures are where the findings nobody
    else has actually live. The executive summary was published with a press
    release.
    """
    from shared import db

    rows = [{"sha256": r[0], "source_key": r[1], "published": r[2],
             "chars": r[3] or 0}
            for r in (db.documents_without_findings() or [])]
    rows.sort(key=lambda r: -r["chars"])
    return rows[:limit] if limit else rows


def prepare(docs=DEFAULT_DOCS, chunks_per_doc=DEFAULT_CHUNKS, fresh=True,
            only_sha=None, skip_offset=0):
    """Write a batch of extraction requests. Returns the manifest.

    `only_sha` re-reads one named document even though it already has findings.
    Needed for the ordinary case of going back for MORE of a report: the first
    batch takes four chunks of a thirty-chunk audit report, and the document
    stops being 'pending' the moment any finding lands. Without this, the other
    twenty-six chunks are unreachable.

    `skip_offset` starts that deeper read after the chunks already covered.
    """

    d = _dir()
    prior = []
    if fresh:
        for f in d.glob("*.md"):
            f.unlink()
        (d / MANIFEST).unlink(missing_ok=True)
    elif (d / MANIFEST).exists():
        # `--keep` means ADD to the batch. The manifest is the ONLY thing
        # ingest() reads, so keeping the request files while overwriting the
        # manifest left every earlier request orphaned: answered on disk,
        # invisible to ingest, and silently absent from the counts. That is the
        # failure mode this repo keeps meeting — an absence that reads exactly
        # like a zero. Breadth needs a batch spanning many documents, and one
        # prepare call only ever covers one.
        try:
            prior = json.loads(
                (d / MANIFEST).read_text(encoding="utf-8")).get("entries") or []
        except ValueError:
            log.warning("manifest at %s is unreadable; starting a new batch", d)
            prior = []

    from shared import db, jurisdiction as juris
    try:
        j = juris.load()
    except Exception:                                           # noqa: BLE001
        j = None

    if only_sha:
        row = db.document_text(only_sha)
        if not row:
            raise RuntimeError(f"no document {only_sha[:12]} in the corpus")
        todo = [{"sha256": row["sha256"], "source_key": row.get("source_key"),
                 "published": row.get("published"), "chars": row.get("chars") or 0}]
    else:
        todo = pending_documents(limit=docs)

    entries, rid = [], len(prior)
    # A chunk already in the batch is not written twice: re-preparing the same
    # document would otherwise queue a second request for the same text and
    # double-count whatever it yields.
    seen = {(e.get("sha256"), e.get("chunk")) for e in prior}
    for doc in todo:
        where = None
        if j is not None:
            from engine import synthesis
            where = synthesis.entity_of(doc.get("source_key"), j)
        where = where or doc.get("source_key") or "a state"
        year = doc.get("published") or "an unstated year"
        full = db.document_text(doc["sha256"])
        if not full or not full.get("text"):
            log.warning("%s: no text in the corpus, skipped", doc["sha256"][:12])
            continue
        all_pieces = analyst.chunk(full["text"])
        pieces = all_pieces[skip_offset:skip_offset + chunks_per_doc]
        for offset, piece in enumerate(pieces, 1):
            n = skip_offset + offset
            if (doc["sha256"], n) in seen:
                continue
            rid += 1
            sha12 = doc["sha256"][:12]
            stem = f"{rid:03d}-{sha12}-c{n}"
            response_name = f"{stem}.response.md"
            (d / f"{stem}.request.md").write_text(
                REQUEST_TEMPLATE.format(
                    where=where, year=year, rid=stem, sha12=sha12, n=n,
                    total=len(all_pieces), response_name=response_name,
                    cats=", ".join(analyst.CATEGORIES), text=piece),
                encoding="utf-8")
            entries.append({
                "rid": stem, "sha256": doc["sha256"], "chunk": n,
                "source_key": doc.get("source_key"), "published": doc.get("published"),
                "where": where, "chars": len(piece),
            })

    manifest = {"written_at": datetime.now(timezone.utc).isoformat(),
                "entries": prior + entries}
    (d / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    # `written_now` is returned but deliberately NOT stored: the manifest on
    # disk describes the batch, and "how many did this call add" is a fact
    # about the call. The caller needs it to report honestly when --keep has
    # added five requests to a batch that already held forty.
    return dict(manifest, written_now=len(entries))


def _chunk_text(entry):
    """The exact chunk a request was built from, for the grounding check.

    Re-derived from the document rather than parsed back out of the request
    file, so a hand-edited request cannot widen what counts as grounded."""
    from shared import db

    row = db.document_text(entry["sha256"])
    if not row or not row.get("text"):
        return None
    pieces = analyst.chunk(row["text"])
    idx = entry["chunk"] - 1
    return pieces[idx] if 0 <= idx < len(pieces) else None


def ingest(store=True):
    """Read every answered request, verify grounding, store what survives.

    Returns a report. A response that is missing, unparseable, or answers with
    prose costs that chunk and nothing else — a 258-page report is worth
    reading imperfectly.
    """
    from engine.digger import extract as dx
    from shared import db

    d = _dir()
    mpath = d / MANIFEST
    if not mpath.exists():
        raise RuntimeError(f"no manifest at {mpath} — run prepare first")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))

    report = {"answered": 0, "missing": 0, "unparseable": 0,
              "findings": 0, "dropped_ungrounded": 0, "by_cause": {}}
    rows = []
    for entry in manifest["entries"]:
        rpath = d / f"{entry['rid']}.response.md"
        if not rpath.exists():
            report["missing"] += 1
            continue
        report["answered"] += 1
        raw = rpath.read_text(encoding="utf-8")
        parsed = analyst._parse(raw)
        if not parsed and raw.strip() and "[]" not in raw:
            report["unparseable"] += 1
            continue
        piece = _chunk_text(entry)
        if piece is None:
            log.warning("%s: document gone from the corpus", entry["rid"])
            continue
        for f in parsed:
            if not dx._grounded(f, piece):
                report["dropped_ungrounded"] += 1
                continue
            cause = (f.get("cause") or "unclear").lower()
            report["by_cause"][cause] = report["by_cause"].get(cause, 0) + 1
            f.update({
                "doc_sha256": entry["sha256"],
                "source_key": entry["source_key"],
                "published": entry["published"],
                "model": "attended",
            })
            rows.append(f)

    report["findings"] = len(rows)
    if store and rows:
        db.store_findings(rows)
    if store:
        # ARCHIVE WHAT WAS STORED, so a second ingest cannot store it again.
        #
        # store_findings() has no dedup key, deliberately — the same claim in
        # two documents is two findings, and collapsing them would destroy the
        # recurring-objection signal the corpus exists to expose. The cost of
        # that choice is that ingest is NOT idempotent, and the natural working
        # rhythm walks straight into it: answer four chunks, ingest, answer four
        # more, ingest again, and the first four are now in the corpus twice
        # with different ids. Nothing downstream would notice; a doubled figure
        # would simply make a finding look twice as large as it is.
        #
        # Same move attend.py makes with its own request files.
        done = d / "done"
        done.mkdir(exist_ok=True)
        for entry in manifest["entries"]:
            rpath = d / f"{entry['rid']}.response.md"
            if rpath.exists():
                rpath.replace(done / f"{entry['rid']}.response.md")
                report.setdefault("archived", 0)
                report["archived"] += 1
    return report


def status():
    """What is waiting, what is answered, what the corpus still owes."""
    d = _dir()
    mpath = d / MANIFEST
    pending = len(pending_documents())
    out = {"documents_without_findings": pending, "batch": None}
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        answered = sum(1 for e in manifest["entries"]
                       if (d / f"{e['rid']}.response.md").exists())
        out["batch"] = {"requests": len(manifest["entries"]),
                        "answered": answered,
                        "waiting": len(manifest["entries"]) - answered,
                        "written_at": manifest.get("written_at")}
    return out


def main(argv=None):
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Attended corpus extraction")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="write a batch of extraction requests")
    p.add_argument("--docs", type=int, default=DEFAULT_DOCS)
    p.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS)
    p.add_argument("--keep", action="store_true",
                   help="do not clear the previous batch first")
    p.add_argument("--sha", help="re-read ONE document by hash, even if it "
                                 "already has findings")
    p.add_argument("--from-chunk", type=int, default=1,
                   help="start at this chunk (1-based) — for going back for "
                        "more of a report already partly read")
    ig = sub.add_parser("ingest", help="verify and store the answered requests")
    # `store_findings` has no dedup key ON PURPOSE — the same objection in two
    # years is two findings and collapsing them destroys the signal. The cost
    # of that choice is that ingest is NOT idempotent: run it twice over one
    # batch and every finding is stored twice. So there has to be a way to see
    # what a batch would yield, and what it would drop, without committing it.
    ig.add_argument("--dry-run", action="store_true",
                    help="verify grounding and report, storing nothing")
    sub.add_parser("status", help="what is waiting")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s")

    if args.cmd == "prepare":
        m = prepare(docs=args.docs, chunks_per_doc=args.chunks,
                    fresh=not args.keep, only_sha=args.sha,
                    skip_offset=max(0, args.from_chunk - 1))
        new = m.get("written_now", len(m["entries"]))
        fresh_written = m["entries"][len(m["entries"]) - new:] if new else []
        print(f"{new} new request(s); {len(m['entries'])} in the batch "
              f"in {DIR_NAME}/")
        for e in fresh_written[:10]:
            print(f"  {e['rid']}  {e['where']} {e['published']}  "
                  f"{e['chars']:,} chars")
        if new > 10:
            print(f"  … and {new - 10} more")
        return 0

    if args.cmd == "ingest":
        r = ingest(store=not args.dry_run)
        print(json.dumps(r, indent=1))
        if args.dry_run:
            print("\ndry run — nothing was stored.")
        if r["dropped_ungrounded"]:
            print(f"\n{r['dropped_ungrounded']} finding(s) dropped — the quote "
                  f"was not in the text. That check is working.")
        return 0

    print(json.dumps(status(), indent=1))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
