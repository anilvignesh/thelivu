"""The one cost model.

USD-per-MTok used to live in three places — the orchestrator's daily report,
the Streamlit dashboard, and the command center — and they had already diverged
(gemini-pro output was $5 in one and $10 in the others, and neither the
orchestrator nor the dashboard knew that NVIDIA-hosted Gemma is free, so free
presentation calls were being billed at Claude rates in the daily report).
Everything imports from here now.

Rates are USD per million tokens, verified against the providers' current
pricing pages on 2026-07-26, Gemini re-verified 2026-08-04. `RATES` is the introspectable table (the tech
steward reads it); `cost_usd` is the resolver — model strings in `token_usage`
are whatever the provider was called with, so matching is substring-based.
"""

RATES = {
    # tier          (input, output)  USD per MTok
    "claude-opus":   (5.00, 25.00),
    "claude":        (3.00, 15.00),   # sonnet-class, the default
    "claude-haiku":  (1.00,  5.00),
    "gemini-pro":    (1.25, 10.00),
    # Flash OUTPUT was raised to $2.50 (it is $1.00 in plenty of older
    # write-ups, which is where the stale value came from). Verified against
    # ai.google.dev/gemini-api/docs/pricing on 2026-08-04, page updated
    # 2026-07-30. Understating this by 2.5x understated every research call the
    # engine makes — the budget governor's whole job is to be right about this.
    "gemini":        (0.30,  2.50),   # flash
    "free":          (0.00,  0.00),   # NVIDIA-hosted Gemma/FLUX, attended work
}

USD_TO_INR = 84

# Substrings that mean "this cost us nothing": NVIDIA's free hosted catalog and
# work a human did in a session.
_FREE_MARKERS = ("gemma", "nvidia", "attended", "flux")


def tier_for(model):
    """Resolve a raw model string to a RATES key. Order matters."""
    m = (model or "").lower()
    if any(f in m for f in _FREE_MARKERS):
        return "free"
    if "gemini" in m:
        return "gemini-pro" if "pro" in m else "gemini"
    if "haiku" in m:
        return "claude-haiku"
    if "opus" in m:
        return "claude-opus"
    return "claude"


# Prompt-cache multipliers on the tier's INPUT rate. A write costs more than a
# fresh read of the same tokens; a read costs a tenth. Both were priced at zero
# until 2026-08-05 because neither was recorded — see shared/db.record_usage.
CACHE_WRITE_MULT = 1.25   # 5-minute TTL (the only TTL the engine uses)
CACHE_READ_MULT = 0.10


def cost_usd(model, in_tok, out_tok, cache_write=0, cache_read=0):
    """USD for one skill call.

    `in_tok` is the UNCACHED REMAINDER the provider billed at full rate, not the
    prompt size. Callers that only have the old two-token pair still get the old
    answer; pass the cache columns to get the true one.
    """
    rate_in, rate_out = RATES[tier_for(model)]
    return (((in_tok or 0) / 1e6 * rate_in)
            + ((out_tok or 0) / 1e6 * rate_out)
            + ((cache_write or 0) / 1e6 * rate_in * CACHE_WRITE_MULT)
            + ((cache_read or 0) / 1e6 * rate_in * CACHE_READ_MULT))


def cost_inr(model, in_tok, out_tok, cache_write=0, cache_read=0):
    return cost_usd(model, in_tok, out_tok, cache_write, cache_read) * USD_TO_INR


def spend_by_skill_model(days=30):
    """[{skill, model, in_tok, out_tok, calls, usd}] over the last N days,
    priciest first. The tech steward's view of where the money actually goes."""
    from shared.db import _conn, _is_postgres

    conn = _conn()
    try:
        cur = conn.cursor()
        cols = ("SELECT skill, model, SUM(input_tokens), SUM(output_tokens), COUNT(*), "
                "SUM(COALESCE(cache_write_tokens,0)), SUM(COALESCE(cache_read_tokens,0)) ")
        if _is_postgres():
            cur.execute(cols + "FROM token_usage WHERE recorded_at >= NOW() - INTERVAL %s "
                        "GROUP BY skill, model", (f"{days} days",))
        else:
            cur.execute(cols + "FROM token_usage WHERE recorded_at >= datetime('now', ?) "
                        "GROUP BY skill, model", (f"-{days} days",))
        rows = [{"skill": r[0], "model": r[1], "in_tok": r[2] or 0,
                 "out_tok": r[3] or 0, "calls": r[4],
                 "cache_write": r[5] or 0, "cache_read": r[6] or 0,
                 "usd": cost_usd(r[1], r[2], r[3], r[5], r[6])} for r in cur.fetchall()]
        rows.sort(key=lambda r: r["usd"], reverse=True)
        return rows
    finally:
        conn.close()


def daily_spend_usd(day=None):
    """Total spend for a UTC day (default: today), summed from token_usage.

    Dual-dialect — same postgres/sqlite split as shared.db.get_cost_report_data.
    The budget governor calls this once per tick from inside Railway, so it is
    deliberately one round trip and does no caching.
    """
    from shared.db import _conn, _is_postgres

    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            if day is None:
                cur.execute(
                    "SELECT model, SUM(input_tokens), SUM(output_tokens), "
                    "SUM(COALESCE(cache_write_tokens,0)), SUM(COALESCE(cache_read_tokens,0)) "
                    "FROM token_usage WHERE recorded_at::date = CURRENT_DATE "
                    "GROUP BY model")
            else:
                cur.execute(
                    "SELECT model, SUM(input_tokens), SUM(output_tokens), "
                    "SUM(COALESCE(cache_write_tokens,0)), SUM(COALESCE(cache_read_tokens,0)) "
                    "FROM token_usage WHERE recorded_at::date = %s "
                    "GROUP BY model", (day,))
        else:
            if day is None:
                cur.execute(
                    "SELECT model, SUM(input_tokens), SUM(output_tokens), "
                    "SUM(COALESCE(cache_write_tokens,0)), SUM(COALESCE(cache_read_tokens,0)) "
                    "FROM token_usage WHERE date(recorded_at) = date('now') "
                    "GROUP BY model")
            else:
                cur.execute(
                    "SELECT model, SUM(input_tokens), SUM(output_tokens), "
                    "SUM(COALESCE(cache_write_tokens,0)), SUM(COALESCE(cache_read_tokens,0)) "
                    "FROM token_usage WHERE date(recorded_at) = ? "
                    "GROUP BY model", (str(day),))
        return sum(cost_usd(r[0], r[1], r[2], r[3], r[4]) for r in cur.fetchall())
    finally:
        conn.close()
