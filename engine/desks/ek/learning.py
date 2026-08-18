"""Outcome-weighted priors for the belief desks — the EK/GK counterpart to
engine/agents/learning.py, which explicitly stops at "the belief desks have no
sources in that sense" and never built this half. Same design, same math, same
guardrails (docs/learning-loop.md) — just different features, because this
desk's inputs are different: no source outlet to trust or distrust, but a
THEME (from themes.yaml, set by belief-scout) and a SHAPE (A/B, set by
premise-check) that a real track record can be learned over.

Added 2026-08-18 as the first concrete piece of the self-improving-framework
work (Anil: "lets improve your autonomy... to the architecture itself" /
"i give you full freedom"). Deliberately copies the parent module's shape
almost exactly rather than inventing a new pattern — this project's own
lesson (three separate caption-assembly implementations before
_build_hashtags/_FOLLOW_CTA became the one shared version) is that the second
implementation of the same idea should look like the first, not surprise
whoever reads it next.

Same hard rule, unchanged: advisory only. Must never suppress a theme or
shape because it scored low, must never touch premise-check's actual
judgment about whether a belief is genuinely held or whether a record
narrows to one case — those are the things worth getting wrong slowly by
hand, not tuned by an average.
"""
import math
from datetime import datetime, timezone

HALF_LIFE_DAYS = 45
MIN_EFFECTIVE_N = 1.5
_SMOOTH_PRIOR, _SMOOTH_WEIGHT = 0.5, 2.0

# needs_attention isn't a clean "wrong theme/shape" signal the way killed/
# dropped is — pipeline.py sets it for a BLOCK verdict (a real editorial miss)
# OR just dead/unnamed citations (a fixable sourcing gap, nothing to do with
# whether the belief or its shape was a good pick). Scored as a soft negative,
# same treatment as hold, rather than a full failure — see module docstring.
_OUTCOME_VALUE = {
    "published": 1.0,
    "killed": 0.0, "kill": 0.0, "dropped": 0.0,
    "hold": 0.4, "held": 0.4,
    "needs_attention": 0.4,
}


def _features(theme, lane, shape):
    feats = []
    if theme:
        feats.append(f"theme:{theme.strip().lower()}")
    if lane:
        feats.append(f"lane:{lane.strip().lower()}")
    if shape:
        feats.append(f"shape:{shape.strip().upper()}")
    return feats


def compute_learned_priors(now=None):
    """{feature: (score, effective_n)} over all terminal EK/GK runs, recency-
    decayed. Reads the DB directly — stateless, retrains on every call, same
    as the news-desk version."""
    from shared.db import _conn
    now = now or datetime.now(timezone.utc)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT p.id, p.status, p.created_at, bp.shape, bq.theme, bq.lane "
            "FROM pipeline_runs p "
            "LEFT JOIN belief_pieces bp ON bp.run_id = p.id "
            "LEFT JOIN belief_queue bq ON bq.run_id = p.id "
            "WHERE p.desk IN ('ek', 'gk')")
        rows = cur.fetchall()
    finally:
        conn.close()

    acc = {}  # feature -> [sum_wv, sum_w]
    for row in rows:
        _run_id, status, created_at, shape, theme, lane = row
        value = _OUTCOME_VALUE.get((status or "").lower())
        if value is None:
            continue  # not a terminal outcome (pending_human, running, etc.)
        try:
            ts = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
        except Exception:
            age_days = HALF_LIFE_DAYS
        w = math.pow(0.5, age_days / HALF_LIFE_DAYS)
        for f in _features(theme, lane, shape):
            s = acc.setdefault(f, [0.0, 0.0])
            s[0] += w * value
            s[1] += w

    priors = {}
    for f, (swv, sw) in acc.items():
        if sw < MIN_EFFECTIVE_N:
            continue
        score = (swv + _SMOOTH_PRIOR * _SMOOTH_WEIGHT) / (sw + _SMOOTH_WEIGHT)
        priors[f] = (round(score, 3), round(sw, 1))
    return priors


def format_priors_block(priors=None, top=5):
    """The advisory text block for belief-scout (which theme to reach for) and
    premise-check (context on how this shape/theme has landed before). '' when
    there isn't enough evidence yet — true for a while on a desk this new."""
    if priors is None:
        priors = compute_learned_priors()
    if not priors:
        return ""
    ranked = sorted(priors.items(), key=lambda kv: kv[1][0])
    strong = [kv for kv in reversed(ranked) if kv[1][0] >= 0.55][:top]
    weak = [kv for kv in ranked if kv[1][0] <= 0.45][:top]
    if not strong and not weak:
        return ""
    lines = ["LEARNED PRIORS (auto-computed from this desk's own outcomes; recency-decayed):"]
    if strong:
        lines.append("Historically promising:")
        lines += [f"  + {f} — publish-tendency {s} (n≈{n})" for f, (s, n) in strong]
    if weak:
        lines.append("Historically weak:")
        lines += [f"  - {f} — publish-tendency {s} (n≈{n})" for f, (s, n) in weak]
    lines.append(
        "Rules: advisory only — use to break ties between otherwise comparable "
        "candidates. NEVER drop a belief that's genuinely held and has a real "
        "record because its theme scored low, and NEVER let this affect whether "
        "a belief IS genuinely held or whether a shape-B case is properly "
        "narrowed — that judgment is premise-check's alone. The charter and "
        "docs/everyone-knows-desk.md outrank this block."
    )
    return "\n".join(lines)
