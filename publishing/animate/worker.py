"""Turn an approved animate story file into a held reel, on the reel-worker VM.

    venv/bin/python -m publishing.animate.worker            # every approved story with no reel yet
    venv/bin/python -m publishing.animate.worker <story.json>   # one story

The workflow, end to end:

  1. GATE 1, the script: a story only runs if its file says `"approved": true`. A person reads the spoken lines against
     the record and sets it. `draft_story` never writes that flag, and `build_piece` refuses any beat still marked `_draft`.
  2. build_piece: every figure, date and excerpt is checked against the cited findings, or nothing is built.
  3. Voice: the shared Chatterbox server is started for this pass and released after (reel_worker.ensure_voice/release_voice).
  4. Render with the animate skill (voice alignment, build, export), then its review. A cut-off or overlapping text, or a
     cut off the grid, blocks the reel; narration density and dead beats are reported, not blocking.
  5. GATE 2, the video: the reel is stored with status 'held' and sent to Telegram with the same Post / Kill buttons every
     reel has. 'held' is invisible to the autopost sweep, so nothing goes out until a person taps Post.

A story is one `pipeline_runs` row (source 'animate', status 'animate', slug = story name) so the existing reel machinery
(posting, double-post guard, YouTube cross-post, command center) works unchanged. The status keeps it out of the article
publisher and out of reel_worker's own candidate query. Re-running a story that already has a run is a no-op.

Env: the reel-worker env file (DATABASE_URL, TELEGRAM_*, SLIDE_SERVER_BASE_URL). ANIMATE_HOME (default ~/animate) is the
cth9191/animate checkout; ANIMATE_PIECES is where pieces are built (default $ANIMATE_HOME/pieces).
"""
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("animate_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [animate_worker] %(message)s")

HOME = Path(os.environ.get("ANIMATE_HOME", os.path.expanduser("~/animate")))
PIECES = Path(os.environ.get("ANIMATE_PIECES", str(HOME / "pieces")))
STORIES = Path(__file__).parent / "stories"
VOICE_NAME = os.environ.get("ANIMATE_VOICE", "anil")
BLOCKING = ("all cuts", "text")      # review lines whose FAIL stops the reel


def _sh(cmd, **kw):
    env = dict(os.environ)
    env["PATH"] = f"{os.path.expanduser('~/fwenv/bin')}:/usr/local/bin:" + env["PATH"]
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw")
    r = subprocess.run(cmd, cwd=HOME, env=env, capture_output=True, text=True, **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _run_for(slug):
    from shared.db import _conn, _is_postgres
    ph = "%s" if _is_postgres() else "?"
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id FROM pipeline_runs WHERE source = 'animate' AND slug = {ph}", (slug,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _make_run(story):
    from shared.db import _conn, _is_postgres
    ph = "%s" if _is_postgres() else "?"
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO pipeline_runs (source, throughline, status, slug, desk) VALUES ('animate', {ph}, 'animate', {ph}, 'news')",
            (story["title"], story["name"]))
        cur.execute("SELECT lastval()") if _is_postgres() else None
        rid = cur.fetchone()[0] if _is_postgres() else cur.lastrowid
        conn.commit()
        return rid
    finally:
        conn.close()


def review_blocks(text):
    """Review lines that stop a reel: a FAIL on cut grid or text (cut-off, overlap, safe zone)."""
    return [l.strip() for l in text.splitlines()
            if re.match(r"\s*(" + "|".join(BLOCKING) + r")\b", l, re.I) and "FAIL" in l]


def render(story_path):
    """build_piece -> voice -> render -> review. Returns (mp4 path, review text). Raises RuntimeError on any failed step."""
    from publishing.animate import build_piece
    from publishing.reel_worker import ensure_voice, release_voice
    story = json.loads(Path(story_path).read_text())
    piece = PIECES / story["name"]
    build_piece.build(story_path, str(piece))
    ensure_voice()
    try:
        rc, out = _sh([sys.executable, str(Path(__file__).parent / "synth_voice.py"), str(piece), VOICE_NAME])
        if rc:
            raise RuntimeError(f"voice synthesis failed: {out[-400:]}")
    finally:
        release_voice()
    for label, cmd in (("voice align", ["node", "tools/voice.mjs", str(piece)]),
                       ("build", ["node", "tools/build.mjs", str(piece)]),
                       ("export", ["node", "tools/export.mjs", str(piece), "--share", "--workers", "2"])):
        rc, out = _sh(cmd)
        if rc:
            raise RuntimeError(f"{label} failed: {out[-400:]}")
    rc, review = _sh(["node", "tools/review.mjs", str(piece)])
    bad = review_blocks(review)
    if bad:
        raise RuntimeError("review blocks the reel: " + " | ".join(bad))
    mp4 = piece / "renders" / "final.mp4"
    if not mp4.exists():
        raise RuntimeError("render produced no final.mp4")
    return mp4, review


def caption(story):
    c = (story.get("caption") or "").strip()
    if not c:
        raise RuntimeError("story has no caption (written by the person approving the script)")
    return c


def process(story_path):
    from shared.db import save_reel, update_reel, update_run
    story = json.loads(Path(story_path).read_text())
    if not story.get("approved"):
        log.info("%s: not approved, skipping", story["name"]); return None
    from shared.db import kv_get, kv_set
    if kv_get(f"animate_parked_{story['name']}"):
        log.info("%s: parked after a failure, skipping (clear with kv_set('animate_parked_%s', ''))", story["name"], story["name"]); return None
    if _run_for(story["name"]):
        log.info("%s: already has a run, skipping", story["name"]); return None
    cap = caption(story)
    mp4, review = render(story_path)
    run_id = _make_run(story)
    reel_id = save_reel(run_id, mp4.read_bytes(), cap, kind="animate", presentation_style="animate")
    update_reel(reel_id, status="held", notes="animate reel, held for the video gate")
    log.info("%s: reel #%s held for run #%s", story["name"], reel_id, run_id)
    from publishing.reel_worker import _notify_reel_ready
    _notify_reel_ready(reel_id, run_id, story["title"], "animate",
                       notes="held — tap Post to publish. " + "; ".join(
                           l.strip() for l in review.splitlines() if "WARN" in l or "FAIL" in l)[:300])
    return reel_id


def _park(path, err):
    """A failed story is parked, not retried: a retry restarts the 4.5GB voice server and re-renders for the same input.
    One Telegram alert; fix the story file (or the cause) and clear the flag."""
    try:
        from shared.db import kv_set
        name = json.loads(Path(path).read_text())["name"]
        kv_set(f"animate_parked_{name}", str(err)[:300])
        import requests
        tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_DRAFT_CHAT_ID")
        if tok and chat:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=20, json={
                "chat_id": chat, "text": f"⚠️ Animate story '{name}' failed and is parked: {str(err)[:400]}"})
    except Exception as e:                                       # noqa: BLE001
        log.warning("could not park/alert: %s", e)


def main(argv):
    from publishing.animate.auto import OUT
    paths = [Path(a) for a in argv] or sorted(STORIES.glob("*/story.json")) + sorted(OUT.glob("*/story.json"))
    failed = 0
    for p in paths:
        try:
            process(p)
        except Exception as e:                                   # noqa: BLE001
            failed += 1
            log.error("%s: %s", p, e)
            _park(p, e)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
