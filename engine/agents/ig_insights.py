"""Snapshotting Instagram, because the API will not remember for us.

Probed 2026-08-08 against `graph.instagram.com` with the Railway token
(docs/reach-analytics.md §2). What is actually available:

- **Per media** — `reach, views, likes, comments, saved, shares`, and both of
  our media types (`CAROUSEL_ALBUM`/FEED and `VIDEO`/REELS) accept the identical
  metric set, which is why one table covers carousels and reels.
- **Account** — `reach` (day, days_28), `accounts_engaged`,
  `total_interactions`. `profile_views` and `follows_and_unfollows` return 200
  with an EMPTY data array on this token; they are not available to us and
  nothing should be built expecting them.

**The reason this module exists rather than a fetch in the command centre:**
account `reach` with `period=day` returns **two days**, and `followers_count` is
a bare current number with no history whatsoever. The API is not a record. If we
do not write the numbers down daily, the history does not exist — and a fetch
driven by the command centre would leave a hole for every day Anil did not open
his laptop. So the sweep lives on the engine, which runs continuously.

**It costs nothing and must never be parked.** This is HTTP against Meta, not a
model call: no `token_usage` row, no quota breaker, and deliberately placed
ABOVE the budget governor in run.py. Parking it with the model stages would
punch holes in the history on precisely the busiest days.

Metric titles come back in Malayalam (the account's locale). Values are
unaffected — we read `name` and `values`, never `title`/`description`.
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger("ig-insights")

BASE = "https://graph.instagram.com"
MEDIA_METRICS = "reach,views,likes,comments,saved,shares"
ACCOUNT_METRICS = "reach"
ACCOUNT_TOTAL_METRICS = "accounts_engaged,total_interactions"

# One sweep is ~24 calls (22 media + 2 account) against a 200/hour limit, so a
# 6-hour cadence sits at ~96/day with room to spare. Insights move slowly enough
# that more often would buy noise.
SWEEP_HOURS = 6
LAST_SYNC_KEY = "last_ig_sync_at"
LAST_RESULT_KEY = "last_ig_sync_result"
FORCE_KEY = "force_ig_sync"
TIMEOUT = 25

# Guard against an account that has grown past what one sweep should pull. Well
# above the current 22; if it ever trips, paginate rather than raising the number.
MAX_MEDIA = 200


def _cfg():
    import os
    tok = os.environ.get("IG_ACCESS_TOKEN")
    uid = os.environ.get("IG_USER_ID")
    if not (tok and uid):
        raise RuntimeError("IG_ACCESS_TOKEN / IG_USER_ID not configured")
    return tok, uid


def _get(path, params):
    import requests
    r = requests.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.json().get('error', {}).get('message', r.text)[:160]}")
    return r.json()


def _metric_values(payload):
    """{name: value} from an insights response, tolerating both shapes.

    Period metrics carry `values: [{value: n}]`; total_value metrics carry
    `total_value: {value: n}`. Reading both here keeps the call sites from
    having to know which is which.
    """
    out = {}
    for d in payload.get("data", []):
        name = d.get("name")
        if d.get("values"):
            out[name] = d["values"][-1].get("value")
        elif isinstance(d.get("total_value"), dict):
            out[name] = d["total_value"].get("value")
    return out


def fetch_media(tok, uid):
    payload = _get(f"{uid}/media", {
        "fields": "id,media_type,media_product_type,timestamp,permalink,caption",
        "limit": MAX_MEDIA, "access_token": tok})
    return payload.get("data", [])


def fetch_media_insights(tok, media_id):
    return _metric_values(_get(f"{media_id}/insights",
                               {"metric": MEDIA_METRICS, "access_token": tok}))


def fetch_account(tok, uid):
    """Followers + today's account numbers, as one dict."""
    prof = _get(uid, {"fields": "followers_count,media_count", "access_token": tok})
    out = {"followers": prof.get("followers_count")}
    try:
        out.update(_metric_values(_get(f"{uid}/insights", {
            "metric": ACCOUNT_METRICS, "period": "day", "access_token": tok})))
    except Exception as e:
        log.warning("account reach unavailable: %s", e)
    try:
        out.update(_metric_values(_get(f"{uid}/insights", {
            "metric": ACCOUNT_TOTAL_METRICS, "period": "day",
            "metric_type": "total_value", "access_token": tok})))
    except Exception as e:
        log.warning("account engagement unavailable: %s", e)
    return out


def fetch_tg_subscribers():
    """Telegram channel subscriber count, or None.

    Rides along with this sweep because it is the same job — how big is the
    audience today — and the same reason applies: nobody keeps this history for
    us. Per-post view counts are NOT obtainable: `message.views` is MTProto-only
    and needs a user session, not a bot token. The eye-count visible in the
    channel is out of reach, and no dashboard should imply otherwise.
    """
    import os
    import requests
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHANNEL_ID")
    if not (tok and chat):
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getChatMemberCount",
                         params={"chat_id": chat}, timeout=15)
        return r.json().get("result") if r.status_code == 200 else None
    except Exception as e:
        log.warning("telegram subscriber count unavailable: %s", e)
        return None


def run_ig_sync():
    """Pull everything and write it down. Returns a short human summary."""
    from shared.db import (kv_set, upsert_ig_media, add_ig_media_metrics,
                           upsert_audience_day, ig_run_id_for_media)

    tok, uid = _cfg()
    media = fetch_media(tok, uid)

    seen, snapped, failed = 0, 0, 0
    for m in media:
        mid = m.get("id")
        if not mid:
            continue
        try:
            upsert_ig_media(
                mid, media_type=m.get("media_type"),
                product_type=m.get("media_product_type"),
                permalink=m.get("permalink"), caption=(m.get("caption") or "")[:600],
                posted_at=m.get("timestamp"),
                run_id=ig_run_id_for_media(mid, m.get("permalink")))
            seen += 1
        except Exception as e:
            log.warning("ig media upsert failed for %s: %s", mid, e)
            failed += 1
            continue
        try:
            vals = fetch_media_insights(tok, mid)
            add_ig_media_metrics(mid, **{k: vals.get(k) for k in
                                         ("reach", "views", "likes", "comments",
                                          "saved", "shares")})
            snapped += 1
        except Exception as e:
            # One post's insights failing must not cost the whole sweep. Reels
            # published in the last few minutes routinely 400 while Meta is
            # still processing them.
            log.warning("ig insights failed for %s: %s", mid, e)
            failed += 1

    acct_note = ""
    try:
        acct = fetch_account(tok, uid)
        upsert_audience_day(
            datetime.now(timezone.utc).date().isoformat(),
            followers=acct.get("followers"), reach_day=acct.get("reach"),
            accounts_engaged=acct.get("accounts_engaged"),
            total_interactions=acct.get("total_interactions"),
            tg_subscribers=fetch_tg_subscribers())
        acct_note = f", {acct.get('followers')} followers"
    except Exception as e:
        log.warning("ig account snapshot failed: %s", e)
        acct_note = ", account snapshot failed"

    result = f"{seen} post(s), {snapped} snapshotted, {failed} failed{acct_note}"
    kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
    kv_set(LAST_RESULT_KEY, result[:300])
    log.info("ig sync: %s", result)
    return result


def sync_due(now_utc):
    from datetime import timedelta
    from shared.db import kv_get

    raw = kv_get(LAST_SYNC_KEY)
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    # A stamp in the future can only be a bad clock or a hand-edited kv value,
    # and left alone it means "never due again" — the same guard cycle_due has.
    if last - now_utc > timedelta(hours=1):
        return True
    return (now_utc - last).total_seconds() >= SWEEP_HOURS * 3600
