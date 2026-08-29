"""Daily spend cap — the budget governor.

The quota breaker handles "the provider said no". This handles the failure the
breaker can't see coming: a balance draining to zero mid-spine, which is how the
engine dies ungracefully (a story half-verified, a draft never written). Instead
the engine parks at a spend cap it sets for itself and resumes when the UTC day
rolls over.

Deliberately simple: no state of its own beyond one kv key, and it self-expires
at midnight UTC because `daily_spend_usd()` only ever counts today.
"""

DEFAULT_CAP_USD = 1.00
CAP_KEY = "daily_budget_usd"
MAX_CAP_USD = 20.0

# How much headroom to keep free so the governor can refuse to START a cycle it
# cannot afford, instead of only noticing after one has overrun.
#
# The cap used to be checked once per tick and then `run_daily_cycle()` ran to
# completion with no further check, so the cap could refuse to start a tick but
# could not bound a day: against a $1.00 cap, 2026-08 produced $1.32, $1.28 and
# $1.16 days. The obvious fix — check between model stages and abort — is the
# one thing this module exists to prevent. See the docstring above: a balance
# dying mid-spine leaves a story half-verified and a draft never written, and an
# abort we schedule ourselves is not better than one the provider schedules.
#
# So the check moves earlier instead of getting sharper. Measured over 63 real
# cycles in the 21 days to 2026-08-08: p50 $0.211, p80 $0.337, p95 $0.993, max
# $1.090. The default is the p80 — about four cycles in five now fit in the
# headroom the governor kept back, so most days land under the cap rather than
# over it.
#
# It does NOT make the cap inviolable, and nothing here should imply it does: a
# single cycle in the p95 tail breaks a $1.00 cap whichever end you check it
# from. The honest claim is "usually honoured" rather than "routinely exceeded".
DEFAULT_RESERVE_USD = 0.35
RESERVE_KEY = "daily_budget_reserve_usd"


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


def reserve_usd(cap=None):
    """Headroom kept free so a cycle is refused before it starts, not after.

    Unset → DEFAULT_RESERVE_USD. Explicit '' or '0' → 0, which restores the old
    check-after-the-fact behaviour exactly. Junk → the default.

    Clamped below the cap: a reserve at or above the cap would park every model
    stage for ever, and a budget that can never be spent is an off switch wearing
    a number. Half the cap is the ceiling — past that the governor is refusing
    more than it allows.
    """
    from shared.db import kv_get

    raw = kv_get(RESERVE_KEY)
    if raw is None:
        val = DEFAULT_RESERVE_USD
    else:
        raw = str(raw).strip()
        if raw == "":
            return 0.0
        try:
            val = float(raw)
        except ValueError:
            val = DEFAULT_RESERVE_USD
    # NaN and inf both parse as floats and both defeat the guard below — NaN
    # because every comparison against it is False, so `spent + nan >= cap` is
    # False for ever and the governor silently stops parking anything. A typo in
    # a kv value must not be able to uncap the engine.
    import math
    if not math.isfinite(val):
        val = DEFAULT_RESERVE_USD
    if val <= 0:
        return 0.0
    if cap is None:
        cap = cap_usd()
    return val if cap is None else min(val, cap / 2.0)


def set_reserve_usd(usd):
    """Persist the reserve. 0 (or None) restores the old post-hoc cap check."""
    from shared.db import kv_set

    if usd is None:
        kv_set(RESERVE_KEY, "")
        return 0.0
    val = float(usd)
    if val < 0 or val > MAX_CAP_USD:
        raise ValueError(f"reserve must be between 0 and {MAX_CAP_USD:g} USD")
    kv_set(RESERVE_KEY, "" if val == 0 else f"{val:g}")
    return val


def status():
    """(spent_today_usd, cap_usd_or_None, over_bool) — one DB round trip.

    `over` is true once the day can no longer afford a typical cycle, not once it
    has already paid for an atypical one — see DEFAULT_RESERVE_USD.
    """
    from shared.costs import daily_spend_usd

    cap = cap_usd()
    spent = daily_spend_usd()
    if cap is None:
        return spent, None, False
    return spent, cap, spent + reserve_usd(cap) >= cap


def is_over_budget():
    """(spent, cap) when the cap is reached, else None.

    Returns the numbers so the caller can log/alert with them rather than
    re-querying. Always None in attended mode — see attended_mode().
    """
    if attended_mode():
        return None
    spent, cap, over = status()
    return (spent, cap) if over else None
