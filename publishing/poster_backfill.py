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
    """(reel_id, [media ids to try]) for posted reels with no poster and no MP4. The id stored on the reel can be a
    stale container id, so the ids Instagram itself listed for that run (ig_media, synced from the account) come first."""
    from shared.db import _conn
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, run_id, ig_media_id FROM reels WHERE poster IS NULL AND mp4 IS NULL "
                    "AND status = 'posted' ORDER BY id DESC LIMIT %d" % int(limit))
        reels = cur.fetchall()
        out = []
        for rid, run_id, own in reels:
            ids = []
            if run_id is not None:
                ph = "%s" if _is_pg() else "?"
                cur.execute("SELECT media_id FROM ig_media WHERE run_id = " + ph +
                            " AND (product_type = 'REELS' OR media_type = 'VIDEO') ORDER BY seen_at DESC", (run_id,))
                ids += [r[0] for r in cur.fetchall()]
            if own and own not in ids:
                ids.append(own)
            if ids:
                out.append((rid, ids))
        return out
    finally:
        conn.close()


def _is_pg():
    from shared.db import _is_postgres
    return _is_postgres()


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
    for reel_id, media_ids in todo:
        try:
            jpeg = None
            for media_id in media_ids:
                jpeg = _thumbnail(media_id)
                if jpeg:
                    break
            if jpeg:
                conn = _conn()
                try:
                    _store_poster(conn.cursor(), reel_id, jpeg)
                    conn.commit()
                finally:
                    conn.close()
                stored += 1
        except Exception as e:  # noqa: BLE001
            log.info("no thumbnail for reel %s (%s): %s", reel_id, media_ids, e)
    log.info("poster backfill: %d stored of %d tried", stored, len(todo))
    return stored, len(todo)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
