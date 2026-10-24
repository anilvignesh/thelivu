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
  5. GATE 2, the video: a reel that passes every check is stored `ready` and the autopost sweep posts it in the next posting slot (POST_SLOTS_IST in engine/distribution/sweep.py) (Kill in Telegram stops it); only a legal flag or the kill switch stores it `held` for a Post tap.

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
import shutil
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
    script = json.loads((piece / "voice" / "script.json").read_text())["lines"]
    for attempt in (1, 2, 3):                   # reel_worker releases the shared voice server whenever ITS queue is empty, which can land mid-synthesis; takes already made are kept
        if all((piece / "voice" / f"{l['id']}.wav").exists() for l in script):
            break
        ensure_voice()
        try:
            rc, out = _sh([sys.executable, str(Path(__file__).parent / "synth_voice.py"), str(piece), VOICE_NAME])
        finally:
            release_voice()
        if rc:
            log.warning("%s: voice synthesis attempt %s failed: %s", story["name"], attempt, out[-200:].replace("\n", " "))
    if any(not (piece / "voice" / f"{l['id']}.wav").exists() for l in script):
        raise RuntimeError("voice synthesis failed after 3 attempts")
    try:
        return _render_steps(piece)
    finally:                                    # the frames are 2.7GB a piece and rebuilt by export; the mp4 is what is kept (the VM disk filled up on 2026-10-18)
        shutil.rmtree(piece / "frames", ignore_errors=True)


def _render_steps(piece):
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


TG_LIMIT = 19_000_000        # Telegram will not fetch a video over 20 MB by URL, so the review push would fail


def fit(mp4):
    """The same video, re-encoded to fit Telegram's fetch limit when the render is larger. Audio and picture size are untouched."""
    mp4 = Path(mp4)
    if mp4.stat().st_size <= TG_LIMIT:
        return mp4
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                               capture_output=True, text=True, check=True).stdout)
    kbps = int(TG_LIMIT * 8 / dur / 1000 * 0.9) - 128
    out = mp4.with_name("final-tg.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k",
                    "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-movflags", "+faststart", str(out)], check=True)
    log.info("%s: %.1f MB re-encoded to %.1f MB to fit Telegram", mp4.parent.parent.name, mp4.stat().st_size / 1e6, out.stat().st_size / 1e6)
    return out


def caption(story):
    c = (story.get("caption") or "").strip()
    if not c:
        raise RuntimeError("story has no caption (written by the person approving the script)")
    return c


def process(story_path):
    from shared.db import save_reel, update_reel
    story = json.loads(Path(story_path).read_text())
    if not story.get("approved"):
        log.info("%s: not approved, skipping", story["name"]); return None
    from shared.db import kv_get
    if kv_get(f"animate_parked_{story['name']}"):
        log.info("%s: parked after a failure, skipping (clear with kv_set('animate_parked_%s', ''))", story["name"], story["name"]); return None
    if story.get("run_id"):
        from shared.db import _conn
        c = _conn(); cur = c.cursor(); cur.execute("SELECT 1 FROM reels WHERE run_id = %s AND status NOT IN ('superseded', 'killed')", (story["run_id"],)); had = cur.fetchone(); c.close()
        if had:
            log.info("%s: article run %s already has a reel, skipping", story["name"], story["run_id"]); return None
    elif _run_for(story["name"]):
        log.info("%s: already has a run, skipping", story["name"]); return None
    cap = caption(story)
    mp4, review = render(story_path)
    mp4 = fit(mp4)
    run_id = story.get("run_id") or _make_run(story)
    reasons = needs_review(story, review)
    auto = not reasons
    reel_id = save_reel(run_id, mp4.read_bytes(), cap, kind="animate", presentation_style="animate")
    update_reel(reel_id, status="ready" if auto else "held",
                notes="animate reel, clean on every gate: auto-posts at the next slot" if auto else "animate reel, held for review: " + "; ".join(reasons))
    log.info("%s: reel #%s %s for run #%s%s", story["name"], reel_id, "READY (auto-post)" if auto else "held", run_id, "" if auto else " - " + "; ".join(reasons))
    _notify(reel_id, run_id, story["title"], reasons)
    return reel_id


def needs_review(story, review):
    """Reasons a person must look before this reel posts. Empty means every gate passed and the autopost sweep may take it.

    The factual gates (grounding, claim verifier, shape) already had to pass for the story to exist. What is left is what no
    machine here can judge: a legal flag or the kill switch. Anil, 2026-10-18: "Let it be posted, I'll delete from Instagram if it's troublesome" - layout WARNs and
    attributed allegations no longer hold a reel; Kill in Telegram stays as a veto."""
    from shared.db import kv_get, _conn
    out = []
    if kv_get("animate_autopost_off"):
        out.append("auto-post is switched off (kv animate_autopost_off)")
    if story.get("run_id"):
        c = _conn(); cur = c.cursor()
        cur.execute("SELECT legal_flag FROM pipeline_runs WHERE id = %s", (story["run_id"],))
        (legal,) = cur.fetchone(); c.close()
        if legal:
            out.append("the article carries a legal flag")
    return out


def _next_slot():
    from datetime import datetime, timedelta, timezone
    from engine.distribution.sweep import POST_SLOTS_IST
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    for add in (0, 1):
        for h, m in POST_SLOTS_IST:
            t = (ist + timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
            if t > ist:
                return t.strftime("%a %H:%M IST")


def _notify(reel_id, run_id, title, reasons):
    from publishing.reel_worker import _tg_post_video
    base = os.environ.get("SLIDE_SERVER_BASE_URL", "").rstrip("/")
    if not base:
        return
    if reasons:
        head = f"🎬 Reel #{reel_id} HELD for your review (run #{run_id}, animate)\n{title}\n\nWhy: " + "; ".join(reasons) + "\n\nWatch, then tap Post or Kill."
    else:
        head = (f"🎬 Reel #{reel_id} passed every check and posts itself at {_next_slot()} (run #{run_id}, animate)\n{title}\n\n"
                "Tap Kill before then to stop it. Tap Post to send it now.")
    keyboard = {"inline_keyboard": [[{"text": "✓ Post now", "callback_data": f"reelapprove_{reel_id}"},
                                     {"text": "✗ Kill", "callback_data": f"reelkill_{reel_id}"}]]}
    _tg_post_video(f"{base}/reel/{reel_id}.mp4", head, keyboard)


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


MIN_FREE_BYTES = 8_000_000_000      # one export needs about 3GB of frames; below this, stop and say so instead of failing mid-render


def _disk_guard():
    free = shutil.disk_usage(PIECES).free
    if free < MIN_FREE_BYTES:
        msg = f"⚠️ Animate worker stopped: only {free / 1e9:.1f} GB free on the VM (needs {MIN_FREE_BYTES / 1e9:.0f}). Old frames or renders need clearing."
        log.error(msg)
        try:
            import requests
            tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
            if tok and chat:
                requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": msg}, timeout=20)
        except Exception:                                        # noqa: BLE001
            pass
        return False
    return True


def main(argv):
    if not _disk_guard():
        return 1
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
