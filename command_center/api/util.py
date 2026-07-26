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


# Cost model — mirrors the Streamlit dashboard's numbers.
INR = 84
_MODEL_COSTS = {
    "claude":     {"in": 3.00, "out": 15.00},
    "gemini":     {"in": 0.30, "out": 1.00},
    "gemini-pro": {"in": 1.25, "out": 10.00},
    "nvidia":     {"in": 0.00, "out": 0.00},
}


def cost_usd(model, in_tok, out_tok):
    m = (model or "").lower()
    if "gemma" in m or "nvidia" in m or m == "attended":
        tier = "nvidia"
    elif "gemini" in m and "pro" in m:
        tier = "gemini-pro"
    elif "gemini" in m:
        tier = "gemini"
    else:
        tier = "claude"
    c = _MODEL_COSTS[tier]
    return ((in_tok or 0) / 1e6 * c["in"]) + ((out_tok or 0) / 1e6 * c["out"])


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
