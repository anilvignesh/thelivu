"""Overview, system status, schedules/signals, voice server, background jobs."""
import datetime
import os
import subprocess

from starlette.routing import Route

from command_center import db, jobs
from command_center.api.util import J, endpoint, err, cost_usd, INR, breaker_state
from shared.db import kv_set, list_digs

VOICE_SCRIPT = os.path.expanduser("~/.jarvis/reel-voice.sh")

# (label, kv last-run key, cadence, signal key, signal value) — same catalogue
# the Streamlit Tasks tab had; signals are read by the orchestrator tick.
SCHEDULES = [
    ("RSS / daily cycle",      "last_cycle_at",        "hourly-ish", "force_rss_run", "1"),
    ("Source scout",           "last_scout_at",        "weekly",     "force_scout_run", "1"),
    ("Story tracker",          "last_tracker_at",      "weekly",     "force_tracker_run", "1"),
    ("Chief of staff",         "last_cos_at",          "daily",      "run_chief_of_staff", "1"),
    ("Dig auto-advance",       "last_dig_sweep_at",    "~6h",        None, None),
    ("Auto-recheck (held)",    "last_auto_recheck_at", "~daily",     None, None),
    ("Meta-synthesis",         "last_meta_at",         "monthly",    "force_meta_run", "1"),
]

# Only signals in this catalogue (or the per-item ones the routes build
# themselves) can be written from the UI — not arbitrary kv keys.
ALLOWED_SIGNALS = {s[3] for s in SCHEDULES if s[3]} | {"dig_request"}


def voice_status():
    """Is the Chatterbox voice server answering on :3901?"""
    import socket
    s = socket.socket()
    s.settimeout(0.6)
    try:
        return s.connect_ex(("127.0.0.1", 3901)) == 0
    finally:
        s.close()


@endpoint
def overview(request, data):
    from shared.db import get_daily_costs

    # One combined list query covers gate + held + recent (round trips are
    # ~1s each on this ISP — every saved query is user-visible latency).
    def fetch_lists():
        return db.q(
            "SELECT id, created_at, source, throughline, trust_gate, status "
            "FROM pipeline_runs "
            "WHERE status IN ('pending_human','held','hold','needs_attention') "
            "   OR id > (SELECT COALESCE(MAX(id),0) - 10 FROM pipeline_runs) "
            "ORDER BY id DESC")

    def safe_digs():
        try:
            return list_digs(include_closed=False)
        except Exception:
            return []

    r = db.parallel(
        counts=lambda: db.q("SELECT status, COUNT(*) AS n FROM pipeline_runs GROUP BY status"),
        lists=fetch_lists,
        agents=lambda: db.q("SELECT skill, model, topic, started_at "
                            "FROM active_agents ORDER BY started_at"),
        digs=safe_digs,
        daily=lambda: get_daily_costs(days=1),
        breaker=breaker_state,
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    for a in r["agents"]:
        t = a.get("started_at")
        if isinstance(t, str):
            try:
                t = datetime.datetime.fromisoformat(t)
            except ValueError:
                t = None
        if t is not None and t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        a["secs"] = int((now - t).total_seconds()) if t else 0
    counts = {row["status"]: row["n"] for row in r["counts"]}
    gate = [x for x in r["lists"] if x["status"] == "pending_human"][:30]
    held = [x for x in r["lists"] if x["status"] in ("held", "hold", "needs_attention")][:20]
    recent = r["lists"][:10]
    today = datetime.date.today().isoformat()
    today_usd = sum(cost_usd(x["model"], x["in_tok"], x["out_tok"])
                    for x in r["daily"] if str(x["day"])[:10] == today)
    return J({
        "counts": counts,
        "gate": gate,
        "held": held,
        "agents": r["agents"],
        "recent": recent,
        "digs": r["digs"],
        "breaker": r["breaker"],
        "voice_up": voice_status(),
        "published": counts.get("published", 0),
        "today_cost": {"usd": round(today_usd, 4), "inr": round(today_usd * INR, 2)},
    })


@endpoint
def system_status(request, data):
    r = db.parallel(
        stamps=lambda: db.kv_many([s[1] for s in SCHEDULES]),
        queue=lambda: db.q("SELECT id, topic, source, status, submitted_at "
                           "FROM pending_topics WHERE status IN ('queued','running') "
                           "ORDER BY id"),
        breaker=breaker_state,
    )
    scheds = []
    for label, key, cadence, sig, sigval in SCHEDULES:
        scheds.append({"label": label, "cadence": cadence, "last": r["stamps"].get(key),
                       "signal": sig, "signal_value": sigval})
    env_checks = {
        "SLIDE_SERVER_BASE_URL": bool(os.environ.get("SLIDE_SERVER_BASE_URL")),
        "TELEGRAM_BOT_TOKEN": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "TELEGRAM_CHANNEL_ID": bool(os.environ.get("TELEGRAM_CHANNEL_ID")),
        "IG_USER_ID": bool(os.environ.get("IG_USER_ID")),
        "IG_ACCESS_TOKEN": bool(os.environ.get("IG_ACCESS_TOKEN")),
        "NVIDIA_API_KEY": bool(os.environ.get("NVIDIA_API_KEY")),
        "DATABASE_URL": bool(os.environ.get("DATABASE_URL")),
    }
    return J({
        "breaker": r["breaker"],
        "voice_up": voice_status(),
        "schedules": scheds,
        "queue": r["queue"],
        "env": env_checks,
        "attend_hint": "./attend cycle",
        "jobs": jobs.recent(30),
    })


@endpoint
def send_signal(request, data):
    key = (data.get("key") or "").strip()
    value = str(data.get("value") or "1")
    if key not in ALLOWED_SIGNALS:
        return err(f"signal '{key}' is not in the allowed catalogue")
    kv_set(key, value)
    return J({"ok": True, "note": "Signalled — the orchestrator picks it up on its next 2-min tick."})


@endpoint
def voice_control(request, data):
    action = data.get("action")
    if action not in ("start", "stop"):
        return err("action must be start|stop")
    if not os.path.exists(VOICE_SCRIPT):
        return err(f"voice launcher not found at {VOICE_SCRIPT}", 500)
    try:
        out = subprocess.run([VOICE_SCRIPT, action], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return err("voice script timed out", 500)
    return J({"ok": out.returncode == 0, "up": voice_status(),
              "output": (out.stdout + out.stderr)[-2000:]})


@endpoint
def job_status(request, data):
    j = jobs.get(request.path_params["jid"])
    if not j:
        return err("no such job", 404)
    return J(j)


@endpoint
def jobs_recent(request, data):
    return J({"jobs": jobs.recent(50)})


@endpoint
def clear_breaker(request, data):
    """Close the quota breaker (same as `./attend clear`) — after a top-up."""
    from shared import quota
    quota.clear()
    return J({"ok": True, "breaker": breaker_state()})


routes = [
    Route("/overview", overview, methods=["GET"]),
    Route("/system", system_status, methods=["GET"]),
    Route("/system/signal", send_signal, methods=["POST"]),
    Route("/system/voice", voice_control, methods=["POST"]),
    Route("/system/breaker/clear", clear_breaker, methods=["POST"]),
    Route("/jobs", jobs_recent, methods=["GET"]),
    Route("/jobs/{jid}", job_status, methods=["GET"]),
]
