"""Presentation-style bandit — the engine trying different reel visual
treatments and shifting toward whichever one people actually engage with.

Anil's framing (2026-08-19): reach isn't opposed to editorial seriousness,
it's a precondition for staying independent — so format experimentation is
part of the job, not a compromise of it. He delegated the experiment cadence
to the engine. Design notes: docs/style-experiments.md.

Mirrors engine/agents/learning.py's shape on purpose (decayed weighted
average, smoothed, advisory) — same reasoning applies here: crude, transparent,
debuggable, adequate at this data size. The one structural difference is this
module CHOOSES an action (which style to render next) rather than only
scoring one — a small epsilon-greedy bandit, not a full RL setup, because the
action space is a handful of hand-built renderers, not a continuous one.

Hard rule carried in the block itself: this never touches verification,
sourcing, or the legal gate — it only decides which renderer draws the frame.
"""
import math
import random
from datetime import datetime, timezone

# The variant registry. 'static' (FLUX illustration + Ken Burns + progressive
# captions) is the only one built today. Add a name here the moment a new
# renderer ships (publishing/reel.py picks by this string) — the bandit
# below treats a name it has never seen as automatically cold-start, so
# nothing else needs to change to bring a new style into rotation.
AVAILABLE_STYLES = ["static"]

HALF_LIFE_DAYS = 21          # faster than editorial learning's 45 — a format
                              # effect should show up within a couple of weeks
                              # of posts, not a season of them.
MATURITY_DAYS = 5            # an IG post's numbers are still climbing before
                              # this; younger posts are excluded, not scored low.
MIN_EFFECTIVE_N = 3.0        # below this many decayed samples, treat the style
                              # as cold-start (gather data) rather than trust its score.
EXPLORE_RATE = 0.3           # even once styles have scores, this fraction of
                              # picks stay random — keeps the bandit from
                              # calcifying on an early lead.
_SMOOTH_PRIOR, _SMOOTH_WEIGHT = 0.05, 2.0   # engagement rates are small
                                             # (a few percent); smooth toward
                                             # a small prior, not 0.5.


def _engagement_rate(reach, likes, comments, saved, shares):
    reach = reach or 0
    if reach <= 0:
        return None
    numer = (likes or 0) + (comments or 0) + (saved or 0) + (shares or 0)
    return numer / reach


def compute_style_scores(now=None):
    """{style: (score, effective_n)} — decayed mean engagement rate (likes +
    comments + saved + shares, over reach) per presentation_style, using each
    reel's latest available metrics snapshot. Reads the DB directly — stateless,
    recomputed on every call, same as compute_learned_priors()."""
    from shared.db import _conn, _is_postgres
    now = now or datetime.now(timezone.utc)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.presentation_style, r.posted_at, m.reach, m.likes, "
            "m.comments, m.saved, m.shares "
            "FROM reels r JOIN ig_media_metrics m ON m.media_id = r.ig_media_id "
            "WHERE r.posted_at IS NOT NULL AND r.ig_media_id IS NOT NULL "
            "AND m.captured_at = (SELECT MAX(captured_at) FROM ig_media_metrics "
            "WHERE media_id = r.ig_media_id)"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    acc = {}  # style -> [sum_wv, sum_w]
    for row in rows:
        style, posted_at, reach, likes, comments, saved, shares = row
        style = style or "static"
        try:
            ts = posted_at if isinstance(posted_at, datetime) else datetime.fromisoformat(str(posted_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (now - ts).total_seconds() / 86400.0
        except Exception:
            continue
        if age_days < MATURITY_DAYS:
            continue  # numbers haven't matured yet — exclude, don't score low
        rate = _engagement_rate(reach, likes, comments, saved, shares)
        if rate is None:
            continue
        w = math.pow(0.5, age_days / HALF_LIFE_DAYS)
        s = acc.setdefault(style, [0.0, 0.0])
        s[0] += w * rate
        s[1] += w

    scores = {}
    for style, (swv, sw) in acc.items():
        score = (swv + _SMOOTH_PRIOR * _SMOOTH_WEIGHT) / (sw + _SMOOTH_WEIGHT)
        scores[style] = (round(score, 4), round(sw, 2))
    return scores


def choose_style(now=None, rng=None):
    """Pick a presentation_style for the next reel. Cold-start styles (no
    data, or fewer than MIN_EFFECTIVE_N decayed samples) are always preferred
    over trusting a thin score, so a newly-added style gets exercised before
    it's judged. Once every style has enough data, EXPLORE_RATE of picks stay
    random and the rest go to the current best-scoring style."""
    rng = rng or random
    scores = compute_style_scores(now=now)
    cold = [s for s in AVAILABLE_STYLES if scores.get(s, (0.0, 0.0))[1] < MIN_EFFECTIVE_N]
    if cold:
        return rng.choice(cold)
    if rng.random() < EXPLORE_RATE:
        return rng.choice(AVAILABLE_STYLES)
    return max(AVAILABLE_STYLES, key=lambda s: scores[s][0])


def format_style_report(scores=None):
    """Human-readable summary for /priors and the weekly self-review — not
    injected into any model prompt, this one's purely for Anil and the log."""
    if scores is None:
        scores = compute_style_scores()
    if not scores:
        return "No matured style data yet."
    ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
    lines = ["STYLE PERFORMANCE (decayed mean engagement rate, matured posts only):"]
    for style, (score, n) in ranked:
        cold = " (cold-start — still gathering data)" if n < MIN_EFFECTIVE_N else ""
        lines.append(f"  {style}: {score:.2%} engagement/reach (n≈{n}){cold}")
    return "\n".join(lines)
