"""The ~2-day batched review: what a Tier-0 candidate has to survive to become
a real dig.

Build-order step 7. This is the seam between free models writing continuously
and expensive investigative resources being spent, and the whole tier's cost
argument rests on it holding: Tier 0 is free, a dig is not.

Three passes, cheapest first, because the naive version — Claude reads every
candidate — does not survive real volume:

  1. `prefilter.run()` drops what nobody would ever promote. Free, rule-based.
  2. This module batches what survives into ONE review call, rather than one
     call per candidate. A batch of twenty costs roughly what two singles do,
     and the reviewer is better for seeing them together — duplicates and
     patterns across sources are visible in a batch and invisible one at a time.
  3. What the reviewer promotes becomes a dig via `create_dig()`, which is where
     the existing pipeline takes over.

**Nothing here publishes.** A promoted candidate becomes a dig; a dig reaches
the pipeline only through `promote_dig()`, which still ends where it always did.
This adds an input to an existing funnel, not a bypass around it.

## Which model reviews (build-order step 8)

Deliberately left as configuration with a documented default rather than a
decision baked into code. The review is low-frequency and high-leverage — it
decides what real investigative effort gets spent on — which is the shape Opus
suits. But the volume that would justify it has not been observed: the first
day produced six candidates, three surviving the pre-filter. Sonnet is the
default until a batch is large enough that the choice is worth paying for, and
`THELIVU_DIGGER_REVIEW_MODEL` moves it without a code change.
"""

import json
import logging
import os
import re

log = logging.getLogger("digger.review")

# Batch ceiling. Not a cost limit — a judgement limit: a reviewer asked to weigh
# sixty candidates at once starts pattern-matching instead of deciding.
MAX_BATCH = 25

PROMOTE = "promote"
REJECT = "reject"
HOLD = "hold"

REVIEW_MODEL_VAR = "THELIVU_DIGGER_REVIEW_MODEL"

_PROMPT = """You are triaging leads for an investigative desk. Each was extracted
by a cheap model from a primary document it actually fetched, and each quotes
that document. They are leads, not stories.

For EACH numbered candidate, decide:

- "promote" — there is a specific, checkable claim here that a real
  investigation could confirm or kill, and it would matter if true. A named
  figure, a documented decision, a gap between what was stated and what was done.
- "hold" — plausibly interesting but too thin alone. Say what single further
  record would settle it.
- "reject" — routine disclosure, no anomaly, or nothing an investigation could
  advance. Most candidates are this, and saying so is the job.

Judge only what is in front of you. Do not assume facts not shown. A candidate
whose excerpt does not support its own claim is a reject, and say why.

Prefer rejecting. The cost of a wrong promote is real investigative effort spent
on nothing; the cost of a wrong reject is one lead among many, and the source
will be read again.

Return STRICT JSON, no prose, no markdown fence:
{{"decisions": [{{"n": 1, "verdict": "promote|hold|reject", "reason": "one sentence",
"question": "the investigative question, promote only", "next_record": "the one
record that would settle it, hold only"}}]}}

CANDIDATES:
{candidates}
"""


def format_batch(candidates):
    """Render candidates for review, excerpt included.

    The excerpt is what lets a reviewer catch a candidate whose claim outruns
    its own evidence — the failure mode that matters most here, because it is
    the one that would otherwise reach a dig.
    """
    parts = []
    for i, c in enumerate(candidates, 1):
        parts.append(
            f"{i}. [{c.get('target_key', '?')}] {c.get('title', '')}\n"
            f"   finding: {c.get('finding', '')}\n"
            f"   quoted from source: {(c.get('excerpt') or '(none)')[:300]}\n"
            f"   agreement between the two readers: {c.get('agreement', '?')}\n"
            f"   source: {c.get('source_url', '')}"
        )
    return "\n\n".join(parts)


def parse_decisions(raw, expected):
    """Tolerant parse. A malformed reviewer response must not silently promote
    or silently discard — anything unparsed is treated as HOLD, which keeps the
    candidate for the next batch instead of losing it."""
    default = [{"n": i, "verdict": HOLD,
                "reason": "reviewer response could not be parsed; held for the next batch"}
               for i in range(1, expected + 1)]
    if not raw:
        return default
    s = raw.strip()
    s = re.sub(r"^```[a-zA-Z]*\n", "", s)
    s = re.sub(r"\n```$", "", s).strip()
    obj = None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    if not isinstance(obj, dict):
        return default
    got = obj.get("decisions")
    if not isinstance(got, list) or not got:
        return default

    by_n = {}
    for d in got:
        if not isinstance(d, dict):
            continue
        try:
            n = int(d.get("n"))
        except (TypeError, ValueError):
            continue
        verdict = str(d.get("verdict", "")).strip().lower()
        if verdict not in (PROMOTE, HOLD, REJECT):
            verdict = HOLD
        by_n[n] = {"n": n, "verdict": verdict,
                   "reason": (d.get("reason") or "").strip(),
                   "question": (d.get("question") or "").strip(),
                   "next_record": (d.get("next_record") or "").strip()}
    # A candidate the reviewer simply omitted is held, never dropped.
    return [by_n.get(i, {"n": i, "verdict": HOLD,
                         "reason": "omitted by the reviewer; held for the next batch"})
            for i in range(1, expected + 1)]


def review_batch(candidates, run_skill=None, model=None):
    """One review call over a whole batch. Returns decisions aligned to input."""
    if not candidates:
        return []
    batch = candidates[:MAX_BATCH]
    prompt = _PROMPT.format(candidates=format_batch(batch))

    if run_skill is None:
        from engine.agents.skill_runner import run_skill as _rs
        run_skill = _rs
    model = model or os.environ.get(REVIEW_MODEL_VAR, "")

    kwargs = {"max_tokens": 4096}
    if model:
        kwargs["model"] = model
    raw = run_skill("chief-of-staff", prompt, **kwargs)
    return parse_decisions(raw, len(batch))


def apply_decisions(candidates, decisions, create_dig=None, set_status=None):
    """Turn decisions into digs and status changes.

    Promotion opens a DIG, not a topic. A dig is the thing that can be advanced,
    disproved and abandoned; sending a free-model lead straight at the writing
    pipeline would skip every step that exists to catch it being wrong.
    """
    if create_dig is None:
        from shared.db import create_dig as _cd
        create_dig = _cd

    promoted, held, rejected = [], [], []
    for cand, dec in zip(candidates, decisions):
        v = dec.get("verdict", HOLD)
        if v == PROMOTE:
            dig_id = create_dig(
                title=cand.get("title", "")[:200],
                question=dec.get("question") or "",
                hypothesis=cand.get("finding", "")[:500],
                owner_note=(f"auto-digger candidate from {cand.get('target_key','?')} — "
                            f"{cand.get('source_url','')}"),
                status="scoping",
            )
            promoted.append((cand, dig_id, dec))
        elif v == HOLD:
            held.append((cand, dec))
        else:
            rejected.append((cand, dec))

        if set_status and cand.get("id"):
            set_status(cand["id"], {PROMOTE: "promoted", HOLD: "held",
                                    REJECT: "rejected"}[v])
    return {"promoted": promoted, "held": held, "rejected": rejected}


def summarise(result):
    p, h, r = (len(result[k]) for k in ("promoted", "held", "rejected"))
    lines = [f"review: {p} promoted, {h} held, {r} rejected"]
    for cand, dig_id, dec in result["promoted"]:
        lines.append(f"  dig #{dig_id}: {cand.get('title','')[:60]} — {dec.get('reason','')[:70]}")
    for cand, dec in result["held"]:
        lines.append(f"  hold: {cand.get('title','')[:52]} — needs {dec.get('next_record','?')[:50]}")
    return "\n".join(lines)
