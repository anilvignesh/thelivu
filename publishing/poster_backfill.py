"""Recover a poster still for posted reels whose MP4 is already gone, using the thumbnail Instagram holds.

The video blob is purged after posting (db.release_posted_reel_bytes), so older stories had no image on the
homepage. Each posted reel keeps its ig_media_id; Instagram's `thumbnail_url` for it is a JPEG we copy into
reels.poster once, because those URLs expire. Small batches, best-effort, safe to run repeatedly:
    python -m publishing.poster_backfill
"""
import logging

import requests

log = logging.getLogger("poster_backfill")


def _candidates(limit):
    from shared.db import _conn
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, ig_media_id FROM reels WHERE poster IS NULL AND mp4 IS NULL "
                    "AND ig_media_id IS NOT NULL AND status = 'posted' ORDER BY id DESC LIMIT %d" % int(limit))
        return [(r[0], r[1]) for r in cur.fetchall()]
    finally:
        conn.close()


def _thumbnail(media_id):
    from publishing.instagram import _graph_get, _token
    out = _graph_get(media_id, {"fields": "thumbnail_url", "access_token": _token()})
    url = out.get("thumbnail_url") if isinstance(out, dict) else None
    if not url:
        return None
    r = requests.get(url, timeout=20)
    ok = r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff" and len(r.content) > 1000
    return r.content if ok else None


def run(limit=30):
    """Returns (stored, tried). A failure on one reel (deleted post, expired token) skips just that one."""
    from shared.db import _conn, _store_poster
    stored = 0
    todo = _candidates(limit)
    for reel_id, media_id in todo:
        try:
            jpeg = _thumbnail(media_id)
            if jpeg:
                conn = _conn()
                try:
                    _store_poster(conn.cursor(), reel_id, jpeg)
                    conn.commit()
                finally:
                    conn.close()
                stored += 1
        except Exception as e:  # noqa: BLE001
            log.info("no thumbnail for reel %s (%s): %s", reel_id, media_id, e)
    log.info("poster backfill: %d stored of %d tried", stored, len(todo))
    return stored, len(todo)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
