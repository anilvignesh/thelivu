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


# The desk scopes a list surface can be filtered to. "belief" spans both series
# because that is how the desks are actually worked — Everyone Knows and Turns
# Out share a pipeline, a trust floor and a queue. "all" is the absence of a
# filter and is deliberately not a key here.
DESK_GROUPS = {"news": ["news"], "belief": ["ek", "gk"],
               "ek": ["ek"], "gk": ["gk"]}


class ListQuery:
    """The parsed shared list controls (search / status / sort / page) for one request.

    Every browse surface — Stories, Carousels, Reels — takes the same five query params
    so the UI control can be one component instead of one per screen. This class turns
    them into SQL pieces; the endpoint supplies the table-specific spec.

    `order` is looked up in a **whitelist**, never interpolated from the request: a sort
    key the spec doesn't define falls back to the default rather than reaching SQL.
    """

    def __init__(self, *, q, status, sort, order, limit, offset):
        self.q, self.status, self.sort = q, status, sort
        self.order, self.limit, self.offset = order, limit, offset
        self.where, self.params = [], []

    def add(self, clause, *params):
        self.where.append(clause)
        self.params.extend(params)

    def filter_status(self, column, groups):
        """Status filter by GROUP, not by raw literal. `pipeline_runs` carries legacy
        duplicate spellings (`hold` AND `held`, `kill` AND `killed`), so filtering on the
        literal the UI shows silently drops rows — 9 killed runs, today. The group map is
        the single place that aliasing is allowed to live."""
        if not self.status or self.status == "all":
            return
        values = groups.get(self.status, [self.status])
        marks = ",".join(["%s"] * len(values))
        self.add(f"{column} IN ({marks})", *values)

    def filter_desk(self, column, desk):
        """Scope a list to one desk, or to the belief desks as a pair.

        `belief` is a GROUP for the same reason the status filter has groups:
        Everyone Knows and Turns Out are two series of one desk, and every screen
        that offers a News/Belief choice would otherwise have to know that the
        belief side is spelled with two values. Unknown input falls through to
        "all" rather than erroring, and nothing from the request ever reaches SQL
        — only the whitelisted values below do."""
        values = DESK_GROUPS.get((desk or "all").strip().lower())
        if not values:
            return
        marks = ",".join(["%s"] * len(values))
        self.add(f"{column} IN ({marks})", *values)

    def search(self, *columns):
        """Case-insensitive OR across the given text columns."""
        if not self.q:
            return
        needle = f"%{self.q.lower()}%"
        ors = " OR ".join(f"LOWER(COALESCE({c},'')) LIKE %s" for c in columns)
        self.add(f"({ors})", *[needle] * len(columns))

    def where_sql(self):
        return (" WHERE " + " AND ".join(self.where)) if self.where else ""

    def page_sql(self):
        return f" ORDER BY {self.order} LIMIT %s OFFSET %s"

    def page_params(self):
        return tuple(self.params) + (self.limit, self.offset)

    def count_sql(self, table):
        return f"SELECT COUNT(*) AS n FROM {table}{self.where_sql()}"

    def envelope(self, total):
        """The shape every list endpoint returns alongside its rows, so the UI can render
        "N of M" and a Load more without knowing which screen it is."""
        return {"total": total, "limit": self.limit, "offset": self.offset,
                "sort": self.sort, "status": self.status or "all", "q": self.q}


# Sorts shared by every list surface. Ordering by id rather than created_at: both are
# monotonic here and id is the primary key, so it needs no extra index.
SORTS_BASE = {"newest": "id DESC", "oldest": "id ASC"}


def list_query(request, *, sorts, default="newest", max_limit=200, default_limit=40):
    qp = request.query_params
    sort = qp.get("sort") or default
    if sort not in sorts:
        sort = default          # whitelist: request text never reaches the ORDER BY
    try:
        limit = min(max(int(qp.get("limit") or default_limit), 1), max_limit)
    except ValueError:
        limit = default_limit
    try:
        offset = max(int(qp.get("offset") or 0), 0)
    except ValueError:
        offset = 0
    return ListQuery(q=(qp.get("q") or "").strip(), status=(qp.get("status") or "").strip(),
                     sort=sort, order=sorts[sort], limit=limit, offset=offset)


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

# None is a meaningful value for both cap and reserve (no cap / no reserve), so
# "not supplied" needs its own sentinel or a fan-out that legitimately read
# `cap = None` would be re-read from kv.
_UNSET = object()


def budget_state(spent_usd=None, cap=_UNSET, reserve=_UNSET):
    """Cap + today's spend + whether the governor is parking model stages.

    Pass `spent_usd` when the caller already computed today's cost, and
    `cap`/`reserve` when they came from a fan-out — the overview passes all
    three, so the banner still costs no round trip of its own. Cap and reserve
    parsing live in shared.budget so the UI and the engine can never disagree.

    `over` means what the ENGINE means by it: parked because what remains is
    under the reserve a cycle needs, which trips before the cap itself is
    reached (shared/budget.py, DEFAULT_RESERVE_USD). Comparing spend to the cap
    alone would paint a parked day healthy and send the owner hunting for a bug.
    This is the one implementation — overview, system view and banner all come
    through here.
    """
    from shared import budget

    if spent_usd is None and cap is _UNSET:
        spent, cap, over = budget.status()
        reserve = budget.reserve_usd(cap) if cap is not None else 0.0
        return {"cap_usd": cap, "reserve_usd": round(reserve, 4),
                "spent_today_usd": round(spent, 4), "over": over}

    spent = budget.status()[0] if spent_usd is None else spent_usd
    if cap is _UNSET:
        cap = budget.cap_usd()
    if reserve is _UNSET:
        reserve = budget.reserve_usd(cap) if cap is not None else 0.0
    reserve = reserve or 0.0
    return {"cap_usd": cap,
            "reserve_usd": round(reserve, 4),
            "spent_today_usd": round(spent, 4),
            "over": cap is not None and spent + reserve >= cap}


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
