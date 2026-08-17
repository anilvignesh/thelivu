"""A hybrid interest signal for belief-desk candidates — LLM judgment (the gate's
own SO_WHAT test, and whoever is triaging the queue) paired with a real-world
search-demand read, because research on pre-publication virality prediction is
consistent on one point: content features judged in isolation are a weak
predictor (one study puts content-only models near a 0.13 ceiling) — you need an
external signal, not just a model's opinion of the text. See the research pointer
in docs/everyone-knows-desk.md if that section gets added; this module is the
external-signal half.

**This is informational, never a gate.** Two reasons a low score must not become
a DROP: (1) Guatemala 1954 will never trend on its own name — the desk exists to
run pieces because the RECORD says they matter, not because the crowd already
cares, and turning this into a filter would just re-invent the myth-swapping
failure mode from the other direction (running only what's already popular).
(2) The signal itself is soft — Google Trends' public interest-over-time series
is relative (0-100 per query, not comparable across unrelated queries) and noisy
at low volumes. Use it to break ties among candidates that already cleared
premise-check and editorial judgment, never to pick which beliefs are worth
researching in the first place.

**The data source is unofficial**, same trust tier as social_desk.py's Nitter/
Reddit-RSS bridges: `pytrends` scrapes the public Google Trends website (no API
key — Google's own official Trends API is alpha/allowlist-gated as of 2026 and
not available here). It can rate-limit or break without notice. Fails soft and
says so — reach.py's rule applies here too: an analytics view that quietly
invents a number is worse than one that admits a gap.
"""
import logging

log = logging.getLogger("ek.interest")


def topic_interest(terms, timeframe="today 3-m", geo=""):
    """Best-effort relative search-interest read for up to 5 short query terms.

    Returns {term: {"mean": float 0-100, "recent": float 0-100, "trend": "rising"
    |"flat"|"falling"|"negligible"}} for terms Trends returned data for. Terms
    with no signal (all-zero or the call failed) are simply absent from the
    result — never stubbed with a fabricated 0, so an empty dict or a missing
    key both mean "no read," not "no interest." Never raises; a failure here
    should never block a triage decision.
    """
    terms = [t.strip() for t in (terms or []) if t and t.strip()][:5]
    if not terms:
        return {}
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=330)
        pt.build_payload(terms, timeframe=timeframe, geo=geo)
        df = pt.interest_over_time()
    except Exception as e:
        log.warning("Trends read failed (unofficial API, expected to be flaky): %s", e)
        return {}
    if df is None or df.empty:
        return {}

    out = {}
    for term in terms:
        if term not in df.columns:
            continue
        series = df[term]
        mean = float(series.mean())
        if mean <= 0:
            continue  # no measurable signal — omit, don't report a fake 0
        recent = float(series.tail(max(1, len(series) // 4)).mean())
        older = float(series.head(max(1, len(series) // 4)).mean()) or mean
        if recent < 1:
            trend = "negligible"
        elif recent > older * 1.3:
            trend = "rising"
        elif recent < older * 0.7:
            trend = "falling"
        else:
            trend = "flat"
        out[term] = {"mean": round(mean, 1), "recent": round(recent, 1), "trend": trend}
    return out


if __name__ == "__main__":
    import sys
    import json
    terms = sys.argv[1:] or ["banana republic phrase", "cuban missile crisis"]
    print(json.dumps(topic_interest(terms), indent=2))
