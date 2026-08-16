"""Posting-time and format priors — learning when/how a post actually reaches people.

Same spirit as engine/agents/learning.py (decayed, smoothed, transparent averages —
not an opaque model): reads engine/agents/learning.py's design notes if you haven't,
this mirrors it. Built 2026-08-16 at Anil's request for a self-learning system that
optimises posting time, after reach-analytics (docs/reach-analytics.md, 2026-08-08)
gave us real per-post numbers to learn from.

⚠️ HONESTY ABOUT DATA SIZE: as of 2026-08-16 there are ~29 posts, several of them
posted within minutes of each other in backlog-clearing bursts (the Oracle
reel-worker catching up on a queue, not independent posting-time choices). That
means several "data points" at nearly the same hour are really ONE event, not five
confirmations of that hour being good — treat any hour-of-day recommendation as
provisional until MIN_EFFECTIVE_N is comfortably cleared with genuinely spaced-out
posts. This module is designed to get more confident as more (spaced) posts land,
not to pretend today's sample supports precision it doesn't have.

This module biases WHEN a ready-to-post item goes out and nothing else — it never
touches verification, never touches the legal-flag gate, and a capped delay (see
MAX_DELAY_HOURS) always wins over waiting for a "better" hour: news going stale is
a real cost too, and it's not one this module is positioned to weigh.
"""
import math
from datetime import datetime, timedelta, timezone

HALF_LIFE_DAYS = 30          # shorter than learning.py's 45 — audience/algorithm
                              # behaviour drifts faster than editorial source quality
MIN_EFFECTIVE_N = 3.0        # higher bar than learning.py's 1.5 — time-of-day claims
                              # are easier to get wrong from a handful of clustered posts
MAX_DELAY_HOURS = 6          # never hold fresh news longer than this chasing a "better" hour
_SMOOTH_PRIOR, _SMOOTH_WEIGHT = 0.5, 2.0
IST_OFFSET = timedelta(hours=5, minutes=30)

# Four broad dayparts rather than 24 individual hours — at this data size, per-hour
# buckets would mostly have n_eff < 1 each. Coarser buckets are the honest choice.
_DAYPARTS = [
    ("late_night", 0, 5),     # 12am-5am IST
    ("morning",    5, 11),    # 5am-11am IST
    ("afternoon", 11, 17),    # 11am-5pm IST
    ("evening",   17, 24),    # 5pm-12am IST
]


def _daypart(hour_ist):
    for name, start, end in _DAYPARTS:
        if start <= hour_ist < end:
            return name
    return "late_night"


def _to_ist_hour(dt_utc):
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return (dt_utc + IST_OFFSET).hour


def compute_time_priors(now=None):
    """{(product_type, daypart): (score, effective_n)} — reach normalised WITHIN
    each product_type (reels and carousels have wildly different baseline reach,
    ~10x apart in the data so far; comparing raw reach across formats would just
    measure "reels beat carousels" again, not say anything about time of day).
    Recency-decayed, smoothed, same math as learning.compute_learned_priors."""
    from shared.db import _conn, _fetchall
    now = now or datetime.now(timezone.utc)

    with _conn() as c:
        cur = c.cursor()
        cur.execute("""
            SELECT m.product_type, m.posted_at, latest.reach
            FROM ig_media m
            JOIN LATERAL (
                SELECT reach FROM ig_media_metrics
                WHERE media_id = m.media_id ORDER BY captured_at DESC LIMIT 1
            ) latest ON true
            WHERE m.posted_at IS NOT NULL
        """)
        rows = _fetchall(cur)

    # Normalise reach within each product_type against that type's own mean first
    # — this is what makes "which hour works" comparable across reels vs carousels.
    by_type = {}
    for r in rows:
        by_type.setdefault(r["product_type"], []).append(r)
    type_means = {t: (sum(r["reach"] or 0 for r in rs) / len(rs)) or 1.0
                  for t, rs in by_type.items()}

    acc = {}  # (product_type, daypart) -> [sum_wv, sum_w]
    for t, rs in by_type.items():
        mean = type_means[t] or 1.0
        for r in rs:
            posted_at = r["posted_at"]
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)
            age_days = max((now - posted_at).total_seconds() / 86400.0, 0.0)
            w = math.pow(0.5, age_days / HALF_LIFE_DAYS)
            value = min((r["reach"] or 0) / mean, 3.0)  # cap one viral outlier's pull
            dp = _daypart(_to_ist_hour(posted_at))
            key = (t, dp)
            s = acc.setdefault(key, [0.0, 0.0])
            s[0] += w * value
            s[1] += w

    priors = {}
    for key, (swv, sw) in acc.items():
        score = (swv + _SMOOTH_PRIOR * _SMOOTH_WEIGHT) / (sw + _SMOOTH_WEIGHT)
        priors[key] = (round(score, 3), round(sw, 1))
    return priors


def recommend_now(product_type, now=None):
    """Should a ready-to-post item go out right now? Returns
    {post_now: bool, reason: str, best_daypart: str|None}.

    Fail-open by design (unlike the legal gate): if there isn't enough evidence
    yet, or every daypart is basically tied, just post — this module's whole job
    is nudging timing at the margin, not adding a new reason to hold real news.
    MAX_DELAY_HOURS is the hard ceiling regardless of what the priors say.
    """
    now = now or datetime.now(timezone.utc)
    priors = compute_time_priors(now)
    relevant = {dp: v for (t, dp), v in priors.items() if t == product_type}

    if not relevant or all(n < MIN_EFFECTIVE_N for _, n in relevant.values()):
        return {"post_now": True, "reason": "not enough spaced-out data yet — posting now",
               "best_daypart": None}

    current_dp = _daypart(_to_ist_hour(now))
    scored = sorted(relevant.items(), key=lambda kv: -kv[1][0])
    best_dp, (best_score, best_n) = scored[0]

    if best_n < MIN_EFFECTIVE_N:
        return {"post_now": True, "reason": f"best daypart '{best_dp}' has too little "
               f"evidence yet (n_eff={best_n})", "best_daypart": None}

    current_score = relevant.get(current_dp, (0.5, 0.0))[0]
    # Post now unless the current window is meaningfully worse AND a better one is
    # coming up soon enough to stay inside MAX_DELAY_HOURS.
    if current_score >= best_score * 0.85:
        return {"post_now": True, "reason": f"current window '{current_dp}' is close "
               f"enough to the best ('{best_dp}')", "best_daypart": best_dp}

    hours_to_best = _hours_until_daypart(now, best_dp)
    if hours_to_best > MAX_DELAY_HOURS:
        return {"post_now": True, "reason": f"best window '{best_dp}' is "
               f"{hours_to_best:.1f}h away — past the {MAX_DELAY_HOURS}h freshness cap",
               "best_daypart": best_dp}
    return {"post_now": False, "reason": f"holding for '{best_dp}' ({hours_to_best:.1f}h), "
           f"current window '{current_dp}' scores meaningfully lower",
           "best_daypart": best_dp, "delay_hours": round(hours_to_best, 1)}


def _hours_until_daypart(now_utc, daypart_name):
    ist_now = now_utc + IST_OFFSET
    for name, start, _end in _DAYPARTS:
        if name == daypart_name:
            target = ist_now.replace(hour=start, minute=0, second=0, microsecond=0)
            if target <= ist_now:
                target += timedelta(days=1)
            return (target - ist_now).total_seconds() / 3600.0
    return 0.0


def format_time_priors_block(priors=None, now=None):
    """Human-readable block — for /timepriors and the command centre, same pattern
    as learning.format_priors_block."""
    priors = priors if priors is not None else compute_time_priors(now)
    if not priors:
        return "No posting-time data yet."
    lines = ["LEARNED POSTING-TIME PRIORS (advisory, provisional — see module docstring):"]
    by_type = {}
    for (t, dp), (score, n) in priors.items():
        by_type.setdefault(t, []).append((dp, score, n))
    for t, entries in by_type.items():
        lines.append(f"  {t}:")
        for dp, score, n in sorted(entries, key=lambda e: -e[1]):
            flag = "" if n >= MIN_EFFECTIVE_N else "  (low confidence)"
            lines.append(f"    {dp:12s} score={score:.2f} n_eff={n}{flag}")
    return "\n".join(lines)
