"""Attended mode — run the Thelivu pipeline at the terminal when the APIs are dry.

    ./attend status              what's parked, and what the breaker says
    ./attend cycle               run the full RSS cycle attended
    ./attend topic "<text>"      run one topic through the spine attended
    ./attend clear               close the breaker early (after a top-up)

This runs the REAL orchestrator. The only thing that changes is where the model
output comes from: `skill_runner._run_attended` writes each prompt to
`.attend/NNN-<skill>.request.md` and blocks until the assistant in this
interactive session writes `.attend/NNN-<skill>.response.md`. The trust gate,
the anti-monotony check, draft parsing and the human publish gate are all
untouched — which is the entire point of putting the seam at the model call.

⚠️ THIS IS A HUMAN-OPERATED TOOL. It is legitimate because Anil is sitting here
driving his own Claude Code session on his own project. It must never be run
unattended — not from cron, not from Railway, not piped through `claude -p`.
The blocking wait is the compliance boundary, not a rough edge to smooth out.
See docs/attended-mode.md.
"""

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

# Attended mode must be set BEFORE the orchestrator imports the skill runner, so
# every skill call in this process takes the human handoff path.
os.environ["THELIVU_ATTENDED"] = "1"

from shared import quota                                    # noqa: E402
from shared.config import REPO_ROOT                          # noqa: E402
from shared.db import (init_db, kv_get, queue_topic, pop_next_topic,  # noqa: E402
                       get_queued_leads, get_runs_by_status, _conn, _fetchall)
from engine.agents.skill_runner import ATTEND_DIR_NAME       # noqa: E402

log = logging.getLogger("attend")


def _fresh_attend_dir():
    """Archive any previous session's files so numbering restarts at 001."""
    d = REPO_ROOT / ATTEND_DIR_NAME
    d.mkdir(exist_ok=True)
    leftovers = list(d.glob("*.md"))
    if leftovers:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive = d / "done" / stamp
        archive.mkdir(parents=True, exist_ok=True)
        for f in leftovers:
            shutil.move(str(f), str(archive / f.name))
        print(f"  archived {len(leftovers)} file(s) from a previous session → {archive}")
    return d


def _parked_counts():
    counts = {}
    # Count in SQL rather than len(get_queued_leads(...)) — that helper caps at a
    # limit, so a big backlog would silently report as exactly the cap. Split by
    # the 7-day window the cycle actually honours: older leads are expired by
    # expire_old_leads() and will never be worked, so counting them as "parked"
    # would overstate what an attended cycle can pick up.
    try:
        with _conn() as c:
            cur = c.cursor()
            cur.execute("select count(*) as n from lead_queue where status = 'queued' "
                        "and created_at > NOW() - INTERVAL '7 days'")
            counts["queued leads (fresh)"] = _fetchall(cur)[0]["n"]
            cur.execute("select count(*) as n from lead_queue where status = 'queued' "
                        "and created_at <= NOW() - INTERVAL '7 days'")
            stale = _fetchall(cur)[0]["n"]
            if stale:
                counts["queued leads (expiring)"] = stale
    except Exception as e:
        counts["queued leads"] = f"? ({e})"
    try:
        with _conn() as c:
            cur = c.cursor()
            cur.execute("select status, count(*) as n from pending_topics "
                        "where status <> 'done' group by status")
            for r in _fetchall(cur):
                counts[f"topics ({r['status']})"] = r["n"]
    except Exception as e:
        counts["topics"] = f"? ({e})"
    for status in ("pending_human", "recheck_requested", "dropped"):
        try:
            counts[f"runs ({status})"] = len(get_runs_by_status(status, limit=200))
        except Exception:
            pass
    return counts


def cmd_status(_args):
    reason = quota.is_blocked()
    until = quota.blocked_until()
    print("\n── Thelivu — attended status ──────────────────────────────────\n")
    if reason:
        left = int((until - datetime.now(timezone.utc)).total_seconds() / 60) if until else "?"
        print(f"  breaker : \033[31mOPEN\033[0m — {reason}")
        print(f"            auto-retries in ~{left} min ({until:%H:%M UTC})" if until else "")
    else:
        print("  breaker : \033[32mclosed\033[0m — automated cycles are running normally")
        print("            (attended mode still works; it just isn't needed)")
    print("\n  parked work:")
    for k, v in _parked_counts().items():
        print(f"    {v:>5}  {k}")
    print("\n  last cycle : ", kv_get("last_cycle_at") or "—")
    print("  run a cycle: ./attend cycle\n")


def cmd_cycle(_args):
    _preamble("full RSS cycle")
    from engine.agents.orchestrator import run_daily_cycle
    run_daily_cycle()
    _postamble()


def cmd_topic(args):
    text = " ".join(args.text).strip()
    if not text:
        sys.exit("give me a topic: ./attend topic \"...\"")
    _preamble(f"topic — {text[:60]}")
    queue_topic(text, source="owner")
    pending = pop_next_topic()
    if not pending:
        sys.exit("could not pop the topic back off the queue — is another process running?")
    from engine.agents.orchestrator import _run_topic_intake
    _run_topic_intake(pending)
    _postamble()


def cmd_carousel(args):
    """Compose a queued/failed carousel attended.

    Approving an article only queues the carousel; composing the slide copy is a
    model stage, so while the breaker is open a carousel sits at 'queued' with
    zero slides and posting it fails with "no hosted slide images". This runs the
    real composer through the attended handoff so the slides get built with no
    API credit — same path the tick would take, just human-driven.
    """
    from shared.db import get_carousel_run, update_carousel_run
    from engine.agents.orchestrator import process_queued_carousels

    cid = args.carousel_id
    if cid is not None:
        car = get_carousel_run(cid)
        if not car:
            sys.exit(f"no carousel #{cid}")
        if car["status"] != "queued":
            # process_queued_carousels only picks up 'queued'. Put it back so a
            # failed or half-composed carousel can be redone without SQL.
            print(f"  carousel #{cid} is '{car['status']}' — requeueing it")
            update_carousel_run(cid, status="queued")
        _preamble(f"carousel #{cid}")
    else:
        _preamble("all queued carousels")

    process_queued_carousels()
    _postamble()


def cmd_reel(args):
    """Build a narrated reel (Anil's cloned voice) for a published run — attended.

    Reels are attended-only for now (config.REEL_MODE='attended'): the video-script
    is a model step, and instead of the API it's handed to this terminal session.
    The voice + ffmpeg render locally, the MP4 is stored in the DB, and the reel
    lands as 'ready' for preview + the gated Post in the dashboard. Nothing posts.

    The dashboard's "Make reel" button, being non-attended, deliberately can't do
    the model step — it points you here. This is the path that actually builds it.
    """
    from publishing.make_reel import make_narrated_reel
    from shared.db import get_reel_for_run

    run_id = args.run_id
    _preamble(f"reel for run #{run_id}")

    # Reuse the story's carousel mood (dark/light) so the reel matches its carousel.
    dark, article_url = None, None
    try:
        with _conn() as c:
            cur = c.cursor()
            cur.execute("SELECT dark, article_url FROM carousel_runs WHERE run_id=%s "
                        "ORDER BY id DESC LIMIT 1", (run_id,))
            row = _fetchall(cur)
            if row:
                dark = row[0].get("dark")
                article_url = row[0].get("article_url")
    except Exception as e:
        log.warning("Could not read the carousel mood for run #%s: %s", run_id, e)

    def _p(frac, msg):
        print(f"    [{int(frac*100):3d}%] {msg}", flush=True)

    res = make_narrated_reel(run_id, dark=bool(dark), article_url=article_url,
                             progress=_p, mode="attended")

    if res.get("ok"):
        rid = res["reel_id"]
        print(f"\n  ✓ reel #{rid} built — {res.get('kind', 'narrated')}, "
              f"{res['beats']} beats, {res['size_kb']} KB.")
        print(f"    preview : {os.environ.get('SLIDE_SERVER_BASE_URL','').rstrip('/')}/reel/{rid}.mp4")
        print(f"    then approve + post it from the dashboard (Carousels tab) — "
              f"posting is still yours alone.")
    elif res.get("voice_down"):
        print(f"\n  ✗ voice server is down. Start it with `{res.get('hint')}` and re-run.")
    else:
        print(f"\n  ✗ could not build the reel: {res.get('error')}")
    _postamble()


def cmd_clear(_args):
    quota.clear()
    print("  breaker closed — the agent will resume automated cycles within 2 minutes.")


def _preamble(what):
    d = _fresh_attend_dir()
    print(f"\n── Attended run: {what} ───────────────────────────────────────")
    print(f"  handoff dir: {d}")
    print("  Each stage writes a .request.md and waits. Read it, do the work,")
    print("  write the matching .response.md, and the pipeline moves on.\n")
    init_db()


def _postamble():
    print("\n  ✓ attended run finished. Anything that reached the gate is now in")
    print("    Telegram / the dashboard awaiting your approve — publishing is")
    print("    still yours alone.\n")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        stream=sys.stdout)
    p = argparse.ArgumentParser(prog="attend", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="what's parked and what the breaker says").set_defaults(fn=cmd_status)
    sub.add_parser("cycle", help="run the full RSS cycle attended").set_defaults(fn=cmd_cycle)
    t = sub.add_parser("topic", help="run one topic through the spine attended")
    t.add_argument("text", nargs="+")
    t.set_defaults(fn=cmd_topic)
    c = sub.add_parser("carousel", help="compose a queued/failed carousel attended")
    c.add_argument("carousel_id", nargs="?", type=int,
                   help="carousel id; omit to do every queued one")
    c.set_defaults(fn=cmd_carousel)
    rl = sub.add_parser("reel", help="build a narrated reel for a run attended (no API)")
    rl.add_argument("run_id", type=int, help="published run id to make a reel for")
    rl.set_defaults(fn=cmd_reel)
    sub.add_parser("clear", help="close the breaker early (after a top-up)").set_defaults(fn=cmd_clear)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
