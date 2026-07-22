"""LLM circuit breaker — stop the engine cleanly when the APIs run dry.

On 2026-07-21 both providers ran out of credit within hours of each other. The
tick loop kept calling `news-monitor` every 2 minutes, crashing on a 429 each
time, for 22 hours. Nothing was produced and the logs were unreadable.

This breaker is the designed response. A *hard* provider failure (out of credit,
quota exhausted, bad key) trips it; the tick then skips every LLM stage until it
expires. A *transient* failure (overloaded, 500, timeout) does NOT trip it —
those already pause + requeue via `_route_spine_failure` in the orchestrator.

Deliberately NOT a fallback to another model. See `docs/attended-mode.md`: when
credit runs out the work parks and Anil runs the cycle attended, rather than the
trust gate silently moving to a weaker engine.

The breaker auto-expires so recovery needs no manual switch — a top-up or a
midnight quota reset is picked up within the hour.
"""

from datetime import datetime, timezone, timedelta

from shared.db import kv_get, kv_set

BLOCKED_UNTIL_KEY = "llm_blocked_until"
BLOCKED_REASON_KEY = "llm_blocked_reason"

# Long enough to stop the crash loop, short enough that a top-up recovers on its
# own within the hour. Owner's call, 2026-07-22.
DEFAULT_COOLDOWN_MINUTES = 60

# Alert types from skill_runner._classify_error that mean "this will not succeed
# on retry" — a wallet/key problem, not a blip.
HARD_ALERT_TYPES = {"billing_cap", "exhausted", "bad_key", "free_tier"}


def trip(reason, minutes=DEFAULT_COOLDOWN_MINUTES):
    """Open the breaker for `minutes`. Returns True if this call opened it,
    False if it was already open (so the caller can alert only on the edge)."""
    was_open = is_blocked() is not None
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    kv_set(BLOCKED_UNTIL_KEY, until.isoformat())
    kv_set(BLOCKED_REASON_KEY, str(reason)[:500])
    return not was_open


def is_blocked():
    """Return the reason string while the breaker is open, else None.

    Expiry is implicit — we compare against the stored timestamp rather than
    clearing on a schedule, so nothing has to be running for it to lapse.
    """
    raw = kv_get(BLOCKED_UNTIL_KEY)
    if not raw:
        return None
    try:
        until = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= until:
        return None
    return kv_get(BLOCKED_REASON_KEY) or "LLM providers unavailable"


def blocked_until():
    """The expiry timestamp while open, else None — for status displays."""
    raw = kv_get(BLOCKED_UNTIL_KEY)
    if not raw or is_blocked() is None:
        return None
    try:
        until = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return until.replace(tzinfo=timezone.utc) if until.tzinfo is None else until


def clear():
    """Close the breaker immediately — after a top-up, or from `attend clear`."""
    kv_set(BLOCKED_UNTIL_KEY, "")
    kv_set(BLOCKED_REASON_KEY, "")
