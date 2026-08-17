"""Auto-build reels for published runs — the piece that used to be a human
clicking "Make reel" in the command center. See docs/plans/06-reel-autonomy.md.

Runs as a long-lived loop (systemd, restart-always) on a box that is NOT Anil's
laptop — designed to be co-located with `chatterbox_server.py` on the same
always-on VM, talking to it over 127.0.0.1. Everything it calls
(`make_narrated_reel`) is the exact same orchestration the command center's
button uses; this file only adds "find work" + "loop" around it.

What it does NOT do: post. It only ever writes `reels` rows with status='ready'
(via the existing `save_reel`, called inside `make_narrated_reel`) — posting
stays the human-gated tap, now reachable from two places: the command center
(unchanged) and Telegram (thelivu_bot/bot.py's reelapprove_/reelkill_ handlers,
which call the exact same publishing/publish.py::post_reel_run the command
center's button calls). This file never gets IG credentials — it can notify,
it cannot post. It also never rebuilds a run that already has ANY reel row
except in one case: a `reels` row explicitly set to status='remake_requested'
(via the Telegram /remake command) is picked up, rebuilt with the stored notes
as a NEW reel row, and the old one is marked 'superseded' — the direct analog
of the command center's remake-with-suggestions box.

Env required (same variables command_center/run.sh already pulls from Railway):
  DATABASE_URL          — must be set BEFORE shared.db is imported (module-level
                           constant there), which is why this file sets up env
                           first and only imports thelivu modules after.
  NVIDIA_API_KEY         — script (Gemma) + illustration (FLUX) generation.
  SLIDE_SERVER_BASE_URL  — for the article_url passed into the reel (source link
                           card / caption) AND the public video URL Telegram
                           fetches to preview it. Reel still builds without it,
                           just can't be pushed to Telegram or posted to IG.
  TELEGRAM_BOT_TOKEN, TELEGRAM_DRAFT_CHAT_ID — optional. Push a preview + the
                           Post/Kill buttons to Anil's draft chat the moment a
                           reel is ready. Deliberately NOT the same credential
                           class as IG_ACCESS_TOKEN — this worker can notify,
                           it can never post. Both unset just skips the push
                           silently (reel still lands in the command center).

Run:  venv/bin/python -m publishing.reel_worker            (loops forever)
      venv/bin/python -m publishing.reel_worker --once      (one pass, for tests)
"""
import argparse
import logging
import os
import sys
import time

log = logging.getLogger("reel_worker")
logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s [reel_worker] %(message)s")

POLL_SECONDS = int(os.environ.get("REEL_WORKER_POLL_SECONDS", "600"))


def _find_candidates():
    """Run ids that are published and have no reel row at all yet. NOT EXISTS
    rather than a LEFT JOIN so a run with multiple carousel_runs rows (if that
    ever happens) can't fan out into duplicate candidates."""
    from shared.db import _conn
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.id, r.slug FROM pipeline_runs r "
            "WHERE r.status = 'published' "
            "AND NOT EXISTS (SELECT 1 FROM reels re WHERE re.run_id = r.id) "
            "ORDER BY r.id ASC"
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def _find_remake_candidates():
    """Reels a human flagged via /remake <id> <notes> in Telegram. One row per
    remake request — bot.py sets status='remake_requested' + notes, never
    touches anything else, so this is the only place that status is consumed."""
    from shared.db import _conn
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, run_id, notes FROM reels "
            "WHERE status = 'remake_requested' ORDER BY id ASC"
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def _carousel_mood(run_id):
    """(dark, article_url) from this run's carousel, same fields the CC's manual
    "Make reel" click uses (command_center/api/media.py::make_reel). None/None
    if there's no carousel yet — make_narrated_reel handles that fine, it just
    means default light + no source-link card."""
    from shared.db import _conn, _is_postgres
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            "SELECT dark, article_url FROM carousel_runs WHERE run_id = " + ph +
            " ORDER BY id DESC LIMIT 1", (run_id,))
        row = cur.fetchone()
        if not row:
            return None, None
        return row[0], row[1]
    finally:
        conn.close()


def _tg_post_video(video_url, caption, reply_markup):
    """Send a reel for review as a native Telegram video (not a link) — one
    call, unlike the carousel's sendMediaGroup-then-follow-up-message dance,
    because sendVideo (unlike sendMediaGroup) accepts reply_markup directly.
    Sent by URL, not file upload: the fileserver already serves the MP4
    publicly (/reel/<id>.mp4) and Telegram fetches it server-side, so this
    worker never needs the raw bytes in memory. Best-effort — a failed push
    must never take the build down with it, the reel already landed in the
    DB and the command center either way."""
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "")
    if not token or not chat_id:
        return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendVideo",
            json={"chat_id": str(chat_id), "video": video_url,
                  "caption": caption[:1024], "reply_markup": reply_markup},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.warning("Telegram push failed (reel still saved, still in the "
                    "command center): %s", e)
        return None


def _notify_reel_ready(reel_id, run_id, story, kind, notes=None):
    base = os.environ.get("SLIDE_SERVER_BASE_URL", "").rstrip("/")
    if not base:
        log.info("SLIDE_SERVER_BASE_URL not set — skipping Telegram push for reel #%s", reel_id)
        return
    video_url = f"{base}/reel/{reel_id}.mp4"
    lines = [f"🎬 Reel #{reel_id} ready for run #{run_id} ({kind})", story or ""]
    if notes:
        lines.append(f"\nApplied your notes: {notes}")
    lines.append(f"\nReview, then tap Post — or /remake {reel_id} <notes> for another cut.")
    caption = "\n".join(l for l in lines if l is not None)
    keyboard = {"inline_keyboard": [[
        {"text": "✓ Post reel", "callback_data": f"reelapprove_{reel_id}"},
        {"text": "✗ Kill",      "callback_data": f"reelkill_{reel_id}"},
    ]]}
    _tg_post_video(video_url, caption, keyboard)


# A run stuck failing every poll used to be a signal to look at that nobody
# ever looked at — found 2026-08-17 (Anil asked why some published articles
# never got a reel): run #171 had been silently retrying against a timed-out
# NVIDIA endpoint for over an hour, every ~10-26 min, with no notification
# anywhere. This many CONSECUTIVE failed builds (not attempts within one
# build — make_narrated_reel already retries 3x internally) before one
# Telegram alert. After that, keeps retrying at the normal cadence (the free
# NVIDIA tier can recover on its own) but only alerts again if it goes quiet
# and comes back to life failing.
_STUCK_ALERT_AFTER = 3


def _tg_post_text(text):
    """Plain text push — same minimal, best-effort pattern as _tg_post_video:
    a failed notification must never take the worker down."""
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "")
    if not token or not chat_id:
        return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": str(chat_id), "text": text[:4096], "parse_mode": "HTML"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.warning("Telegram text push failed: %s", e)
        return None


def _build_one(run_id, slug):
    from publishing.make_reel import make_narrated_reel
    from shared.db import get_run, kv_get, kv_set

    dark, article_url = _carousel_mood(run_id)
    if not article_url:
        base = os.environ.get("SLIDE_SERVER_BASE_URL", "").rstrip("/")
        article_url = f"{base}/a/{slug}" if base and slug else None

    log.info("building reel for run #%s (dark=%s, article_url=%s)",
              run_id, dark, article_url)
    try:
        result = make_narrated_reel(run_id, dark=dark, article_url=article_url,
                                    mode="nvidia")
    except Exception as e:
        # make_narrated_reel's contract is to never raise for expected failures
        # (voice down, quota, etc. all come back as {ok:False, ...}) — this is
        # the belt-and-braces for anything unexpected. One run blowing up must
        # not take the rest of the batch down with it.
        log.exception("run #%s raised building its reel", run_id)
        result = {"ok": False, "error": str(e)}

    fail_key = f"reel_build_fails_{run_id}"
    if result.get("ok"):
        log.info("run #%s -> reel #%s (%s, %s beats, %sKB)", run_id,
                  result.get("reel_id"), result.get("kind"),
                  result.get("beats"), result.get("size_kb"))
        run = get_run(run_id) or {}
        _notify_reel_ready(result["reel_id"], run_id,
                           run.get("throughline"), result.get("kind"))
        kv_set(fail_key, "")  # clear the streak — it recovered
    else:
        # Never raises by contract (make_reel.py docstring) — log and move on,
        # next poll picks it up again.
        log.warning("run #%s did not build: %s", run_id, result)
        n = int(kv_get(fail_key) or 0) + 1
        kv_set(fail_key, str(n))
        if n == _STUCK_ALERT_AFTER:
            run = get_run(run_id) or {}
            _tg_post_text(
                f"⚠️ Reel stuck: run #{run_id} has failed to build {n}x in a row.\n\n"
                f"{(run.get('throughline') or '')[:200]}\n\n"
                f"Last error: {str(result.get('error', ''))[:300]}\n\n"
                f"Still retrying automatically — this is a heads-up, not a request "
                f"to do anything, unless it stays stuck.")
    return result


def _build_remake(old_reel_id, run_id, notes):
    """Rebuild run_id with owner notes (from /remake in Telegram), the direct
    analog of the command center's remake-suggestion box. make_narrated_reel
    always produces a fresh reel row (never overwrites) — same as the CC path
    — so the old one is marked 'superseded' here to keep it out of both the
    command center's default views and this worker's own candidate query."""
    from publishing.make_reel import make_narrated_reel
    from shared.db import get_run, update_reel

    dark, article_url = _carousel_mood(run_id)
    if not article_url:
        base = os.environ.get("SLIDE_SERVER_BASE_URL", "").rstrip("/")
        run = get_run(run_id) or {}
        article_url = f"{base}/a/{run.get('slug')}" if base and run.get("slug") else None

    log.info("remaking reel for run #%s (was reel #%s) with notes: %s",
              run_id, old_reel_id, notes)
    try:
        result = make_narrated_reel(run_id, dark=dark, article_url=article_url,
                                    mode="nvidia", notes=notes)
    except Exception as e:
        log.exception("remake for run #%s raised", run_id)
        update_reel(old_reel_id, status="ready")  # don't strand it stuck mid-remake
        return {"ok": False, "error": str(e)}
    if result.get("ok"):
        log.info("remake: run #%s -> reel #%s (%s, %s beats, %sKB)", run_id,
                  result.get("reel_id"), result.get("kind"),
                  result.get("beats"), result.get("size_kb"))
        update_reel(old_reel_id, status="superseded")
        run = get_run(run_id) or {}
        _notify_reel_ready(result["reel_id"], run_id, run.get("throughline"),
                           result.get("kind"), notes=notes)
    else:
        log.warning("remake for run #%s did not build: %s", run_id, result)
        update_reel(old_reel_id, status="ready")  # revert — /remake can be retried
    return result


def run_once():
    did_something = False

    remakes = _find_remake_candidates()
    if remakes:
        log.info("%d remake(s) requested: %s", len(remakes), [r["id"] for r in remakes])
        did_something = True
        for r in remakes:
            _build_remake(r["id"], r["run_id"], r.get("notes"))

    candidates = _find_candidates()
    if candidates:
        log.info("%d run(s) awaiting a reel: %s", len(candidates),
                  [c["id"] for c in candidates])
        did_something = True
        for c in candidates:
            _build_one(c["id"], c.get("slug"))

    if not did_something:
        log.info("nothing to build")


def _wait_for_voice(timeout_s=240):
    """Block until Chatterbox answers /health, or timeout_s elapses.

    Co-located deploys (systemd `After=`/`Wants=` on chatterbox.service) only
    guarantee start ORDER, not readiness — the Turbo model can take well over
    a minute to load (longer still on first boot, downloading weights). Without
    this, the worker's first pass burns through the entire backlog against a
    still-loading voice server: every run in that pass fails with voice_down
    and the whole backlog waits a full POLL_SECONDS for nothing. Seen exactly
    this on the first real deploy — 28 queued runs, 28 failures, model was
    still loading underneath. Bounded, not indefinite: a genuinely broken
    voice server should still surface via the normal per-run voice_down path
    rather than hang the process forever.
    """
    import requests
    deadline = time.time() + timeout_s
    waited = False
    while time.time() < deadline:
        try:
            if requests.get("http://127.0.0.1:3901/health", timeout=3).status_code == 200:
                if waited:
                    log.info("voice server ready")
                return
        except Exception:
            pass
        waited = True
        log.info("voice server not ready yet, waiting...")
        time.sleep(5)
    log.warning("voice server still not ready after %ds — proceeding anyway, "
                "individual runs will report voice_down if it's genuinely down", timeout_s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                     help="run a single pass and exit (tests/manual runs)")
    args = ap.parse_args()

    # shared.db reads DATABASE_URL as a module-level constant at import time —
    # everything above this point must not import it. Neither var set means an
    # unconfigured box would silently write into ./thelivu.db — refuse to start
    # instead. DB_PATH (unset DATABASE_URL) is the documented scratch-test path
    # (docs/plans/README.md "test discipline"), so that's allowed through.
    if not os.environ.get("DATABASE_URL") and not os.environ.get("DB_PATH"):
        sys.exit("Neither DATABASE_URL nor DB_PATH set — refusing to start "
                 "(would default to ./thelivu.db)")
    if not os.environ.get("NVIDIA_API_KEY"):
        sys.exit("NVIDIA_API_KEY not set — reel script/illustration steps need it")
    if not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_DRAFT_CHAT_ID")):
        log.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_DRAFT_CHAT_ID not set — reels will "
                    "build fine but won't be pushed to Telegram for review")

    _wait_for_voice()

    if args.once:
        run_once()
        return

    log.info("reel_worker starting, polling every %ds", POLL_SECONDS)
    while True:
        try:
            run_once()
        except Exception:
            log.exception("pass failed — will retry next poll")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
