"""The two ends of the long-form chain, either side of the second gate.

`publishing/longform.py` decides what is legal, `publishing/longform_render.py`
turns a script into an MP4, and `publishing/youtube.py` talks to Google. This
joins them, and it exists because the join is not obvious: the two halves of
"publish a long video" run on different machines.

    reel-worker box            has the voice server and the render, and by
                               deliberate design (see reel_worker.py) holds no
                               posting credentials at all
    Railway                    has the credentials, and never has the bytes

An upload needs both, which for a while looked like a contradiction. The way
out is that **the video is uploaded UNLISTED at render time**. Then:

  * gate 2 hands Anil a real YouTube link, playing in YouTube's own player,
    rather than several hundred megabytes streaming off a fileserver built for
    90-second reels whose bytes live in a Postgres column;
  * the ~20 minutes of upload are spent BEFORE the review rather than after it,
    so approving is instant instead of starting a long job;
  * and "post it" becomes a privacy flip — one small HTTP call that Railway can
    make with credentials alone.

The cost of that choice is an unlisted video existing on the channel before
anyone has approved it. That is acceptable in a way a public one would not be:
unlisted is not indexed, not on the channel page, and not in subscriber feeds,
so the only way to it is the link in Anil's own Telegram card. A dropped item
is deleted rather than left lying there — see `drop()`.

## Why rendering is retried but not repeated

Narration is about an hour of the only voice server for a 1,300-word script. If
the upload fails — and a 200MB PUT over a home uplink fails sometimes — the
next pass must not spend that hour again. So the local MP4 path is recorded the
moment the render finishes, and a pass that finds one on disk skips straight to
uploading it.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("longform_build")

# Where rendered videos live on the worker box. On disk rather than in the
# database: a reel is ~3MB and fits in a column, an eight-minute 1080p video is
# two orders of magnitude larger and does not.
LONGFORM_DIR = Path(os.environ.get(
    "LONGFORM_DIR", os.path.expanduser("~/.thelivu/longform")))

# Render at most this many per pass. Long-form is occasional; a queue with two
# approved scripts in it means something unusual is happening, and doing them
# one pass at a time keeps the voice server available for the daily reels in
# between.
MAX_PER_PASS = 1


def _kb(path):
    try:
        return os.path.getsize(path) // 1024
    except Exception:
        return 0


def attach_script(queue_id, script_path, blockers=None):
    """Record the written script against a queue item and open gate 1.

    Separate from rendering because the script is written by a different thing
    at a different time — today by hand, later by the script agent — and
    because SCRIPTED is a human gate: this is the last automated step before
    the pipeline has to stop and wait for a person.
    """
    from shared.db import longform_item, set_longform_artifact
    from publishing import longform

    path = Path(script_path)
    if not path.exists():
        return {"ok": False, "error": f"no script at {path}"}
    row = longform_item(queue_id)
    if not row:
        return {"ok": False, "error": f"no long-form queue item #{queue_id}"}

    parsed = longform.parse_script(path.read_text())
    if not parsed.get("chapters"):
        return {"ok": False, "error": "script parsed to zero chapters — check "
                                      "it uses CHAPTER n TITLE:/CHAPTER n: lines"}

    set_longform_artifact(queue_id, script_path=str(path.resolve()))
    longform.advance(queue_id, row.get("status") or longform.QUEUED,
                     longform.SCRIPTED, by="system")
    # The blockers matter more than the script on that card — see
    # notify_script_for_review. publishing/longform_script.py supplies the
    # mechanical ones; a hand-attached script passes none and says so by
    # omission.
    longform.notify_script_for_review(queue_id, parsed, blockers=blockers)
    return {"ok": True, "status": longform.SCRIPTED,
            "words": parsed.get("word_count", 0),
            "chapters": len(parsed["chapters"])}


def _marks_path(video_path):
    return Path(str(video_path) + ".marks.json")


def _write_render_marks(video_path, res):
    """Save the chapter marks beside the MP4.

    They are measured from the real audio during the render and are the one
    thing a retried upload cannot recompute without re-narrating. Losing them
    would not fail anything — YouTube would simply show a video with no
    chapters, which is exactly the kind of quiet degradation a monthly
    pipeline never notices.
    """
    try:
        _marks_path(video_path).write_text(json.dumps(
            {"seconds": res.get("seconds"), "chapters": res.get("chapters") or [],
             "shots": res.get("shots")}))
    except Exception as e:
        log.warning("could not save chapter marks for %s: %s", video_path, e)


def _read_render_marks(video_path):
    try:
        return json.loads(_marks_path(video_path).read_text())
    except Exception:
        return {}


def _render_one(row, voice=None, illustrate=True):
    """Render (or re-use) the MP4 for one approved script. Returns (path, parsed)."""
    from publishing import longform
    from publishing import longform_render
    from shared.db import set_longform_artifact

    qid = row["id"]
    script_path = row.get("script_path")
    if not script_path or not os.path.exists(script_path):
        raise RuntimeError(f"#{qid} is approved but its script is missing "
                           f"({script_path!r})")
    parsed = longform.parse_script(Path(script_path).read_text())

    existing = row.get("video_path")
    if existing and os.path.exists(existing):
        # An hour of narration already spent. Whatever failed last pass, it was
        # not this.
        log.info("#%s already rendered (%s, %dKB) — reusing", qid, existing,
                 _kb(existing))
        parsed["_render"] = _read_render_marks(existing)
        return existing, parsed

    LONGFORM_DIR.mkdir(parents=True, exist_ok=True)
    out = LONGFORM_DIR / f"longform_{qid}.mp4"
    work = LONGFORM_DIR / f"work_{qid}"
    log.info("#%s rendering %s words to %s", qid, parsed.get("word_count"), out)
    res = longform_render.render(parsed, str(out), work_dir=str(work),
                                 voice=voice, illustrate=illustrate)
    if not res.get("ok"):
        raise RuntimeError(f"render failed: {res.get('error')}")

    set_longform_artifact(qid, video_path=str(out))
    _write_render_marks(out, res)
    parsed["_render"] = res
    log.info("#%s rendered: %.1f min, %d shots, %dKB",
             qid, res["seconds"] / 60, res.get("shots", 0), _kb(out))
    return str(out), parsed


def _upload_unlisted(qid, video_path, parsed, existing_id=None):
    """Upload for review. Returns (video_id, permalink).

    `existing_id` short-circuits it. A pass reaches this point with one already
    recorded when the upload SUCCEEDED and something after it did not — the
    state write, or the Telegram card. Uploading again would leave a duplicate
    eight-minute video on the channel that nothing afterwards ever references
    or cleans up.
    """
    from publishing import youtube
    from shared.db import set_longform_artifact

    if existing_id:
        log.info("#%s is already uploaded as %s — not uploading again",
                 qid, existing_id)
        return existing_id, f"https://youtube.com/watch?v={existing_id}"

    render = parsed.get("_render") or {}
    chapters = [(int(s_), str(l)) for s_, l in (render.get("chapters") or [])]
    with open(video_path, "rb") as f:
        data = f.read()
    log.info("#%s uploading %.1fMB unlisted…", qid, len(data) / 1e6)
    from publishing.longform import build_description
    video_id, permalink = youtube.publish_video(
        data,
        title=parsed.get("title") or f"Thelivu long-form #{qid}",
        # Not parsed["description"] — build_description() appends every source
        # the video puts on screen, derived from the FIGURE/TABLE/RECORD lines
        # rather than trusted to the writer's own list, which drifts the moment
        # a chapter is edited.
        description=build_description(parsed),
        tags=parsed.get("hashtags") or None,
        privacy="unlisted",
        chapters=chapters or None,
    )
    set_longform_artifact(qid, youtube_video_id=video_id)
    return video_id, permalink


def render_pending(limit=MAX_PER_PASS, voice=None, illustrate=True):
    """Render and stage every script Anil has approved. Runs on the worker box.

    Called from reel_worker's pass. Returns a list of per-item results; never
    raises for an expected failure, on the same contract as make_narrated_reel,
    because one bad item must not stop the daily reels.
    """
    from publishing import longform
    from shared.db import longform_queue

    rows = longform_queue(status=longform.SCRIPT_OK)[:limit]
    if rows:
        # Before an hour of narration, not after it. This box needs to be able
        # to UPLOAD; it deliberately does not need to publish.
        from publishing import youtube
        ok, why = youtube.preflight(need_publish=False)
        if not ok:
            log.error("not rendering — %s", why)
            return [{"id": r["id"], "ok": False,
                     "error": f"YouTube upload unavailable on this box: {why}"}
                    for r in rows]
    out = []
    for row in rows:
        qid = row["id"]
        try:
            video_path, parsed = _render_one(row, voice=voice,
                                             illustrate=illustrate)
            _video_id, permalink = _upload_unlisted(
                qid, video_path, parsed, existing_id=row.get("youtube_video_id"))
            render = parsed.get("_render") or {}
            minutes = (render.get("seconds") or 0) / 60 or None
            # State last, notification after it: an item marked RENDERED with
            # nothing to watch is a dead end a human cannot clear, and RENDERED
            # is a gate the pipeline may never pass for itself.
            longform.advance(qid, longform.SCRIPT_OK, longform.RENDERED,
                             by="system")
            longform.notify_video_for_review(
                qid, parsed.get("title") or f"#{qid}", permalink, minutes=minutes)
            out.append({"id": qid, "ok": True, "url": permalink})
            log.info("#%s staged for review: %s", qid, permalink)
        except Exception as e:
            log.exception("#%s did not stage", qid)
            out.append({"id": qid, "ok": False, "error": f"{type(e).__name__}: {e}"})
    return out


def publish_approved():
    """Make public whatever Anil approved at gate 2. Runs on Railway.

    Both approval surfaces — the Telegram card and the dashboard — advance the
    item to POSTED and write `post_longform_id`. They do not talk to YouTube
    themselves: the bot's callback has to answer within seconds, and a Google
    round trip inside a button handler is how a card ends up looking like it
    did nothing. This sweep does the flip.
    """
    from shared.db import kv_get, kv_set, longform_item
    from publishing import youtube

    raw = (kv_get("post_longform_id") or "").strip()
    if not raw:
        return None
    try:
        qid = int(raw)
    except ValueError:
        kv_set("post_longform_id", "")
        return f"ignored unparseable post_longform_id {raw!r}"

    row = longform_item(qid)
    if not row:
        kv_set("post_longform_id", "")
        return f"no long-form item #{qid}"
    video_id = row.get("youtube_video_id")
    if not video_id:
        # Nothing to flip. Clearing the key is right: the item was approved for
        # a video that was never staged, and retrying forever would alert on
        # every tick.
        kv_set("post_longform_id", "")
        return f"#{qid} has no uploaded video to publish"

    status = youtube.set_privacy(video_id, "public")
    kv_set("post_longform_id", "")
    url = f"https://youtube.com/watch?v={video_id}"
    log.info("long-form #%s is %s: %s", qid, status, url)
    return f"#{qid} published ({status}): {url}"


def drop(queue_id):
    """Delete a rejected item's unlisted upload.

    An unlisted video is invisible enough to stage a review with and not
    invisible enough to leave lying on the channel after the answer was no.
    """
    from shared.db import longform_item, set_longform_status
    from publishing import youtube

    row = longform_item(queue_id) or {}
    video_id = row.get("youtube_video_id")
    removed = False
    if video_id:
        try:
            youtube.delete_video(video_id)
            removed = True
        except Exception as e:
            log.warning("could not delete unlisted #%s (%s): %s",
                        queue_id, video_id, e)
    set_longform_status(queue_id, "dropped")
    return {"ok": True, "youtube_deleted": removed}


def main():
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [longform] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--attach", type=int, metavar="ID",
                    help="attach a written script to queue item ID and open gate 1")
    ap.add_argument("--script", help="path to the script, with --attach")
    ap.add_argument("--render", action="store_true",
                    help="render and stage every approved script (worker box)")
    ap.add_argument("--publish", action="store_true",
                    help="make an approved video public (Railway)")
    ap.add_argument("--no-illustrate", action="store_true",
                    help="skip FLUX; every shot falls back to the house ground")
    ap.add_argument("--list", action="store_true", help="show the queue")
    args = ap.parse_args()

    # The CLI is often the first thing to touch a box (a fresh worker, a local
    # dry run), so create the tables rather than failing on a missing one.
    from shared.db import init_db
    init_db()

    if args.list:
        from publishing import longform
        from shared.db import longform_queue
        for state in (longform.QUEUED, longform.SCRIPTED, longform.SCRIPT_OK,
                      longform.RENDERED, longform.POSTED):
            for r in longform_queue(status=state):
                print(f"  #{r['id']:<4} {state:<10} {(r.get('title') or '')[:60]}")
        return 0

    if args.attach:
        if not args.script:
            sys.exit("--attach needs --script")
        print(attach_script(args.attach, args.script))
        return 0

    if args.render:
        for r in render_pending(illustrate=not args.no_illustrate):
            print(r)
        return 0

    if args.publish:
        print(publish_approved() or "nothing approved for posting")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
