"""Snapshotting YouTube, for the same reason ig_insights.py snapshots
Instagram: `videos.list` only ever returns the CURRENT totals, not history, so
if nothing writes today's numbers down there is no curve to look at tomorrow.

Needs the `youtube.readonly` scope (added 2026-08-17 — the original
`youtube.upload`-only token 403'd on this with ACCESS_TOKEN_SCOPE_INSUFFICIENT,
verified directly against the live API before adding the scope, not assumed).
Same "Testing" OAuth caveat as publishing/youtube.py: the refresh token expires
every 7 days until the app is verified — a run failing with an invalid_grant
here means that, not a bug in this module.

Deliberately reuses reels.youtube_video_id as the video list (see the
yt_video_metrics schema comment in shared/db.py) rather than an API list call —
YouTube's `videos.list` takes explicit ids, no channel-scoped "list my uploads"
in the free tier of this token, and we already know every id we've posted.

Costs nothing per call beyond the free Data API quota (videos.list is 1 quota
unit/call, batched up to 50 ids per call) — same reasoning as ig_insights.py
for living above the model budget governor in run.py: this is HTTP, not a
model call, and must never be parked with the paid stages.
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger("yt-insights")

SWEEP_HOURS = 6
LAST_SYNC_KEY = "last_yt_sync_at"
LAST_RESULT_KEY = "last_yt_sync_result"
FORCE_KEY = "force_yt_sync"
TIMEOUT = 25
BATCH = 50  # videos.list max ids per call


def _access_token():
    from publishing.youtube import _access_token as _at
    return _at()


def fetch_stats(video_ids):
    """{video_id: {views, likes, comments}} for up to 50 ids at a time,
    batched. Videos that 404 (deleted, or a bad id) are just absent from the
    result — not an error, so one bad id can't cost the whole sweep."""
    import requests
    if not video_ids:
        return {}
    token = _access_token()
    out = {}
    for i in range(0, len(video_ids), BATCH):
        chunk = video_ids[i:i + BATCH]
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": ",".join(chunk)},
            headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        for item in r.json().get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = {
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
            }
    return out


def run_yt_sync():
    """Pull stats for every posted YouTube video and write a snapshot each.
    Returns a short human summary. Never raises — same contract as run_ig_sync,
    the caller's try/except is belt-and-braces, not the primary guard."""
    from shared.db import kv_set, add_yt_video_metrics, get_yt_posted_videos

    try:
        posted = get_yt_posted_videos()
    except Exception as e:
        log.error("could not list posted YouTube videos: %s", e)
        return f"failed to list videos: {e}"

    video_ids = [p["video_id"] for p in posted if p.get("video_id")]
    if not video_ids:
        result = "no YouTube videos posted yet"
        kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
        kv_set(LAST_RESULT_KEY, result)
        return result

    try:
        stats = fetch_stats(video_ids)
    except Exception as e:
        log.error("yt stats fetch failed: %s", e)
        result = f"{len(video_ids)} video(s), fetch failed: {e}"
        kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
        kv_set(LAST_RESULT_KEY, result[:300])
        return result

    snapped = 0
    for vid in video_ids:
        s = stats.get(vid)
        if not s:
            continue  # deleted/private/bad id — not an error, just absent
        try:
            add_yt_video_metrics(vid, **s)
            snapped += 1
        except Exception as e:
            log.warning("yt metrics write failed for %s: %s", vid, e)

    result = f"{len(video_ids)} video(s), {snapped} snapshotted"
    kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
    kv_set(LAST_RESULT_KEY, result[:300])
    log.info("yt sync: %s", result)
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
    if last - now_utc > timedelta(hours=1):
        return True
    return (now_utc - last).total_seconds() >= SWEEP_HOURS * 3600
