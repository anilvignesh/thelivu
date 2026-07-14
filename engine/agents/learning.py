"""Outcome-weighted priors — the engine learning from its own track record.

Every finished run is a labelled example (published / killed / held). This
module turns them into decayed, smoothed publish-tendency scores per source
and theme, for the two SELECTION stages (news-monitor, newsworthiness-gate)
to use as an advisory prior. Design notes: docs/learning-loop.md.

Hard rule carried in the block itself: this biases which lead gets picked
first — it must never affect verification, and must never suppress a
high-impact story because its theme historically died.
"""
import math
from datetime import datetime, timezone

HALF_LIFE_DAYS = 45
MIN_EFFECTIVE_N = 1.5
_SMOOTH_PRIOR, _SMOOTH_WEIGHT = 0.5, 2.0

_OUTCOME_VALUE = {
    "published": 1.0,
    "killed": 0.0, "kill": 0.0, "dropped": 0.0,
    "held": 0.4, "hold": 0.4,
}

# Keyword buckets over the throughline. Crude on purpose: transparent,
# debuggable, and adequate at this data size. Extend as beats emerge.
_THEMES = {
    "infrastructure":   ("port", "seaport", "airport", "highway", "metro", "bridge", "silo", "vizhinjam", "infra"),
    "public-finance":   ("bond", "kiifb", "fiscal", "revenue", "budget", "borrow", "debt", "cag", "audit", "tax"),
    "health":           ("hospital", "health", "medical", "medicine", "doctor", "patient", "drug"),
    "education":        ("school", "madrasa", "university", "college", "student", "exam", "teacher"),
    "environment":      ("mining", "quarry", "wetland", "forest", "coast", "cliff", "monsoon", "climate", "pollution", "aravalli"),
    "privatisation":    ("privatis", "psu", "divest", "monetis", "outsourc"),
    "welfare":          ("ration", "pension", "mgnrega", "welfare", "subsidy", "midday", "housing scheme", "anganwadi"),
    "courts-legal":     ("court", "judgment", "tribunal", "contempt", "bail", "fir", " ats", "enforcement directorate"),
    "gender-violence":  ("woman", "assault", "harass", "pocso", "dowry", "stalk"),
    "communal-caste":   ("communal", "religio", "temple", "mosque", "church", "caste", "iskcon", "madrasa"),
    "corporate-power":  ("adani", "ambani", "reliance", "conglomerate", "monopol", "cartel"),
    "labour":           ("worker", "wage", "strike", "union", "gig ", "labour", "migrant"),
}


def _features(source, throughline):
    feats = []
    if source:
        feats.append(f"source:{source.strip().lower()}")
    tl = (throughline or "").lower()
    for theme, kws in _THEMES.items():
        if any(k in tl for k in kws):
            feats.append(f"theme:{theme}")
    return feats


def compute_learned_priors(now=None):
    """{feature: (score, effective_n)} over all terminal pipeline runs,
    recency-decayed. Reads the DB directly — stateless, so the 'model' retrains
    itself on every call as outcomes accumulate and old evidence fades."""
    from shared.db import _conn
    now = now or datetime.now(timezone.utc)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT source, throughline, status, created_at FROM pipeline_runs")
        rows = cur.fetchall()
    finally:
        conn.close()

    acc = {}  # feature -> [sum_wv, sum_w]
    for row in rows:
        source, throughline, status, created_at = row[0], row[1], row[2], row[3]
        value = _OUTCOME_VALUE.get((status or "").lower())
        if value is None:
            continue  # not a terminal outcome
        try:
            ts = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
        except Exception:
            age_days = HALF_LIFE_DAYS  # unknown age: count at half weight
        w = math.pow(0.5, age_days / HALF_LIFE_DAYS)
        for f in _features(source, throughline):
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
    """The advisory text block injected into selection prompts (and shown by
    /priors). '' when there isn't enough evidence for a single signal."""
    if priors is None:
        priors = compute_learned_priors()
    if not priors:
        return ""
    ranked = sorted(priors.items(), key=lambda kv: kv[1][0])
    # A signal is only a signal when it leans away from the 0.5 neutral prior.
    strong = [kv for kv in reversed(ranked) if kv[1][0] >= 0.55][:top]
    weak = [kv for kv in ranked if kv[1][0] <= 0.45][:top]
    if not strong and not weak:
        return ""
    lines = ["LEARNED PRIORS (auto-computed from this pipeline's own outcomes; recency-decayed):"]
    if strong:
        lines.append("Historically promising:")
        lines += [f"  + {f} — publish-tendency {s} (n≈{n})" for f, (s, n) in strong]
    if weak:
        lines.append("Historically weak:")
        lines += [f"  - {f} — publish-tendency {s} (n≈{n})" for f, (s, n) in weak]
    lines.append(
        "Rules: advisory only — use to break ties between otherwise comparable leads. "
        "NEVER drop or downgrade a high-impact lead because its theme scored low, and "
        "NEVER let these numbers affect verification. The charter outranks this block."
    )
    return "\n".join(lines)
