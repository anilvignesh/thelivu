"""Shared plumbing for the API modules."""
import datetime
import decimal
import json

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response


def _jdefault(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (bytes, memoryview)):
        return f"<{len(o)} bytes>"
    return str(o)


def J(data, status=200):
    return Response(json.dumps(data, default=_jdefault),
                    status_code=status, media_type="application/json")


def err(message, status=400):
    return J({"ok": False, "error": message}, status)


def endpoint(fn):
    """Async wrapper: parse the JSON body up front, then run the sync handler
    in the threadpool (all our DB/publishing calls are blocking)."""
    async def wrapper(request):
        data = {}
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            try:
                data = await request.json()
            except Exception:
                data = {}
        return await run_in_threadpool(fn, request, data)
    wrapper.__name__ = fn.__name__
    return wrapper


# Cost model — one table for the whole repo, in shared/costs.py.
from shared.costs import cost_usd, USD_TO_INR as INR  # noqa: F401 (re-exported)


def budget_state(spent_usd=None):
    """Cap + today's spend + whether the governor is parking model stages.

    Pass `spent_usd` when the caller already computed today's cost (the
    overview does) — that turns this into a single kv read. Cap parsing lives
    in shared.budget so the UI and the engine can never disagree about it.
    """
    from shared import budget

    if spent_usd is None:
        spent, cap, _ = budget.status()
    else:
        spent, cap = spent_usd, budget.cap_usd()
    return {"cap_usd": cap,
            "spent_today_usd": round(spent, 4),
            "over": cap is not None and spent >= cap}


def breaker_state():
    """Breaker status in ONE round trip. quota.is_blocked()+blocked_until()
    read kv_store key-by-key — six round trips (~6s on a slow link) for two
    values; we read both keys at once and apply the same expiry logic."""
    from shared.quota import BLOCKED_UNTIL_KEY, BLOCKED_REASON_KEY
    from command_center.db import kv_many
    kv = kv_many([BLOCKED_UNTIL_KEY, BLOCKED_REASON_KEY])
    raw = kv.get(BLOCKED_UNTIL_KEY)
    if not raw:
        return {"open": False, "reason": None, "until": None}
    try:
        until = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return {"open": False, "reason": None, "until": None}
    if until.tzinfo is None:
        until = until.replace(tzinfo=datetime.timezone.utc)
    if datetime.datetime.now(datetime.timezone.utc) >= until:
        return {"open": False, "reason": None, "until": None}
    return {"open": True,
            "reason": kv.get(BLOCKED_REASON_KEY) or "LLM providers unavailable",
            "until": until.isoformat()}
