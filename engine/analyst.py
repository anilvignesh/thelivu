"""Turning the corpus into findings.

The corpus holds 126.7M characters across 29 states and ten years and, until
this, nothing read it. A pile of text nobody queries is not an asset.

**What this is for.** Anil, 2026-09-15: *"we are pulling up news which the media
is not giving enough coverage, in this we become the primary source of news."*
That only happens if the finding is not already a headline. "30,308 crore
uncollected" is on page 11 of a report the CAG published with a press release —
restating it makes us a commentator. The material that makes us a primary source
is in the annexures, and in what shows up when ten years of one state, or one
year of twenty-nine, are put beside each other.

**The two rules everything here answers to.**

1. EVERY FINDING QUOTES THE DOCUMENT. `extract._grounded` already does this and
   it is the most valuable check in the package — a confident free model
   smuggling training-data recall into a "finding" is caught by nothing else.

2. A FAILURE AND A MISFORTUNE ARE DIFFERENT STORIES. The first scan of this
   corpus returned three flood-damage figures in its top eight, presented
   exactly like failures: huge numbers, in audit reports, next to the word
   "loss". Karnataka's 97,814 crore of flood damage is not a scandal. Punjab's
   33,973 crore advanced against 1,422 crore recovered is. Nothing mechanical
   separates them, so the model must COMMIT to one, and anything it cannot call
   is held for a person rather than guessed.

Chunked, because a 258-page report does not fit a context window and would not
be read carefully if it did. Free models, because this is extraction against a
strict contract and the grounding check catches what they get wrong — the
judgement tier is a separate job (see docs/plans/09-investigation-framework.md).
"""

import json
import logging
import re

log = logging.getLogger("analyst")

# Big enough to hold a whole finding with its context, small enough that a free
# model reads it rather than summarising it. Measured against the same free
# models the digger uses.
CHUNK_CHARS = 18_000
CHUNK_OVERLAP = 1_200          # a finding split across a boundary is still found

CATEGORIES = ("recovery", "idle", "non-compliance", "delay", "diversion",
              "shortfall", "irregular", "other")

_PROMPT = """You are reading part of a government audit report from {where}, {year}.

Extract only findings where a PUBLIC BODY did or failed to do something. For each:

  claim     one sentence, your own words, naming who and what
  excerpt   a VERBATIM span copied exactly from the text below, 15-40 words,
            containing the evidence. Never paraphrase it.
  amount_cr the rupee figure in CRORE as a number, or null
  category  one of: {cats}
  cause     "state"    an act or omission of government
            "external" a flood, drought, epidemic or other outside event
            "unclear"  you cannot tell from this text

A flood damaging crops is "external" even when the amount is enormous. Money
advanced and not recovered is "state". If unsure, say "unclear" — do not guess.

Return ONLY a JSON array, no prose. [] if nothing qualifies.

TEXT:
{text}
"""


# Haiku, not a free model, and the reason is measured rather than preferred.
# The free tier caps at roughly 2,000 CHARACTERS of prompt — anything larger
# returns "All models exhausted" regardless of request rate (2026-09-15: 1,958
# chars OK, 5,871 refused). An audit finding needs the paragraph around it, so
# free models can read a parliamentary answer and cannot read an audit report.
MODEL = "claude-haiku-4-5"


def _ask(prompt, model=MODEL, max_tokens=1600):
    """One extraction call, billed and recorded. Returns the raw reply.

    Usage is logged to token_usage on every call, so the corpus pass can be
    priced from what it actually spent rather than from an estimate — and so a
    run that goes wrong is visible in the same place as every other cost.
    """
    import anthropic

    from shared.config import ANTHROPIC_API_KEY
    from shared.db import record_usage

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    try:
        record_usage("corpus-analyst", model,
                     resp.usage.input_tokens, resp.usage.output_tokens)
    except Exception as e:                                  # noqa: BLE001
        log.warning("could not record usage: %s", e)
    return "".join(b.text for b in resp.content if getattr(b, "text", None))


def chunk(text, size=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """Split on paragraph boundaries where possible, with overlap.

    Overlap is not belt-and-braces: an audit finding regularly runs a table into
    the sentence that explains it, and a hard cut between them produces a number
    with no claim attached to it and a claim with no number.
    """
    text = text or ""
    if len(text) <= size:
        return [text] if text.strip() else []
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):
            brk = text.rfind("\n", i + size // 2, end)
            if brk > i:
                end = brk
        out.append(text[i:end])
        if end >= len(text):
            break
        i = max(i + 1, end - overlap)
    return out


def _parse(raw):
    """Findings out of a model's reply. Tolerant of fences and stray prose."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        rows = json.loads(s[start:end + 1])
    except ValueError:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not (r.get("claim") or "").strip():
            continue
        cause = (r.get("cause") or "unclear").strip().lower()
        if cause not in ("state", "external", "unclear"):
            cause = "unclear"
        cat = (r.get("category") or "other").strip().lower()
        amt = r.get("amount_cr")
        try:
            amt = float(amt) if amt not in (None, "", "null") else None
        except (TypeError, ValueError):
            amt = None
        out.append({
            "claim": r["claim"].strip()[:600],
            "excerpt": (r.get("excerpt") or "").strip()[:600],
            "amount_cr": amt,
            "category": cat if cat in CATEGORIES else "other",
            "cause": cause,
        })
    return out


def read_document(sha256, text, where, year, model=None, max_chunks=None):
    """Extract grounded findings from one corpus document. Returns a list.

    Never raises: a chunk that the model refuses, times out on, or answers with
    prose costs that chunk and nothing else. A 258-page report is worth reading
    imperfectly.
    """
    from engine.digger import extract as dx

    pieces = chunk(text)
    if max_chunks:
        pieces = pieces[:max_chunks]
    model = model or MODEL
    found, dropped = [], 0

    for n, piece in enumerate(pieces, 1):
        prompt = _PROMPT.format(where=where or "a state", year=year or "an unstated year",
                                cats=", ".join(CATEGORIES), text=piece)
        try:
            raw = _ask(prompt, model)
        except Exception as e:                              # noqa: BLE001
            log.info("chunk %d/%d unread: %s", n, len(pieces), str(e)[:70])
            continue
        used = model
        for f in _parse(raw):
            # Grounded against THIS CHUNK, not the whole document: a quote the
            # model lifted from elsewhere in the report is still a quote it did
            # not read here, and the looser check would wave it through.
            if not dx._grounded(f, piece):
                dropped += 1
                continue
            f.update({"doc_sha256": sha256, "model": used})
            found.append(f)

    if dropped:
        log.info("%s: %d finding(s) dropped — quote not in the text", sha256[:12], dropped)
    return found


# --------------------------------------------------------------------------
# the corpus pass
# --------------------------------------------------------------------------

def spent_on_corpus_usd():
    """What the analyst has billed so far, from token_usage.

    Read back from what was actually recorded rather than accumulated in
    memory, so an interrupted run resumes knowing its true spend. A counter that
    resets when the process does is not a budget.
    """
    from shared.costs import cost_usd
    from shared.db import _conn, _is_postgres

    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""SELECT model, input_tokens, output_tokens,
                       coalesce(cache_write_tokens,0), coalesce(cache_read_tokens,0)
                  FROM token_usage WHERE skill = {ph}""", ("corpus-analyst",))
        return sum(cost_usd(*r) for r in cur.fetchall())
    finally:
        conn.close()


def read_corpus(budget_usd, limit_docs=None, max_chunks=None, progress=None):
    """Read unread corpus documents until the budget is spent. Returns a summary.

    THE BUDGET IS A HARD STOP AND IT IS CHECKED BEFORE EVERY DOCUMENT, not
    after. A bug in a loop that spends money is the one kind of bug that keeps
    costing while you look for it, so the cap has to be the thing that cannot be
    got past — not a warning, not an average, not a post-hoc check.

    Smallest documents first, deliberately: if the estimate is wrong, it is
    wrong cheaply and visibly on the tenth document rather than expensively on
    the first. Resumable — a document that already has findings is skipped, so
    an interruption costs nothing but the document in flight.
    """
    from shared.db import (documents_without_findings, store_findings)
    from shared.db import _conn

    started = spent_on_corpus_usd()
    todo = documents_without_findings(limit=limit_docs)
    out = {"documents": 0, "findings": 0, "stopped": None,
           "spent_usd": 0.0, "remaining": len(todo)}

    for sha, src, pub, chars in todo:
        spent = spent_on_corpus_usd() - started
        out["spent_usd"] = spent
        if spent >= budget_usd:
            out["stopped"] = f"budget reached (${spent:.2f} of ${budget_usd:.2f})"
            log.warning("stopping: %s", out["stopped"])
            break

        conn = _conn()
        try:
            cur = conn.cursor()
            ph = "%s" if conn.__class__.__module__.startswith("psycopg2") else "?"
            cur.execute(f"SELECT text FROM documents WHERE sha256 = {ph}", (sha,))
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            continue

        where = (src or "").replace("cag-", "").replace("-", " ").title()
        rows = read_document(sha, row[0], where, pub, max_chunks=max_chunks)
        for r in rows:
            r["source_key"] = src
            r["published"] = pub
        store_findings(rows)

        out["documents"] += 1
        out["findings"] += len(rows)
        out["remaining"] -= 1
        log.info("%s %s: %d finding(s) from %s chars  [$%.2f spent]",
                 src, pub, len(rows), format(chars, ","),
                 spent_on_corpus_usd() - started)
        if progress:
            progress(out)

    out["spent_usd"] = spent_on_corpus_usd() - started
    return out
