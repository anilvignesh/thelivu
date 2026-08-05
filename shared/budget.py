"""Daily spend cap — the budget governor.

The quota breaker handles "the provider said no". This handles the failure the
breaker can't see coming: a balance draining to zero mid-spine, which is how the
engine dies ungracefully (a story half-verified, a draft never written). Instead
the engine parks at a spend cap it sets for itself and resumes when the UTC day
rolls over.

Deliberately simple: no state of its own beyond one kv key, and it self-expires
at midnight UTC because `daily_spend_usd()` only ever counts today.
"""

DEFAULT_CAP_USD = 0.75
CAP_KEY = "daily_budget_usd"
MAX_CAP_USD = 20.0


def attended_mode():
    """True when the operator is driving this process via `./attend`.

    Attended work does not touch the paid APIs at all — `skill_runner` swaps the
    model call for a blocking file handoff to the human's own session, and
    `shared/costs.py` already prices anything marked 'attended' at zero. So the
    cap, which exists to bound API spend, has nothing to bound here: leaving it
    armed would park work that costs nothing and force the owner to raise or
    disable the cap by hand just to run a cycle he is paying for out of a
    subscription.

    This was already true by accident — the only enforcement lives in run.py's
    daemon loop, which `attend.py` never enters — but an accident is not a
    guarantee. Stated here so a future budget check added anywhere else inherits
    it, and so the test suite can hold it.

    Fails safe if the env var were ever set on Railway: the same flag makes every
    skill call block on a `.attend/` response file that no unattended process
    will ever write, so a mis-set var hangs the engine rather than uncapping it.
    """
    import os
    return os.environ.get("THELIVU_ATTENDED") == "1"


def cap_usd():
    """The active cap in USD, or None when the governor is disabled.

    Unset → DEFAULT_CAP_USD. Explicit '' or '0' → disabled (no cap).
    """
    from shared.db import kv_get

    raw = kv_get(CAP_KEY)
    if raw is None:
        return DEFAULT_CAP_USD
    raw = str(raw).strip()
    if raw == "":
        return None
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_CAP_USD
    return None if val <= 0 else val


def set_cap_usd(usd):
    """Persist the cap. 0 (or None) disables the governor. Returns the new cap."""
    from shared.db import kv_set

    if usd is None:
        kv_set(CAP_KEY, "")
        return None
    val = float(usd)
    if val < 0 or val > MAX_CAP_USD:
        raise ValueError(f"budget must be between 0 and {MAX_CAP_USD:g} USD")
    kv_set(CAP_KEY, "" if val == 0 else f"{val:g}")
    return None if val == 0 else val


def status():
    """(spent_today_usd, cap_usd_or_None, over_bool) — one DB round trip."""
    from shared.costs import daily_spend_usd

    cap = cap_usd()
    spent = daily_spend_usd()
    return spent, cap, (cap is not None and spent >= cap)


def is_over_budget():
    """(spent, cap) when the cap is reached, else None.

    Returns the numbers so the caller can log/alert with them rather than
    re-querying. Always None in attended mode — see attended_mode().
    """
    if attended_mode():
        return None
    spent, cap, over = status()
    return (spent, cap) if over else None
