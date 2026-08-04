"""Overview, system status, schedules/signals, voice server, background jobs."""
import datetime
import json
import os
import subprocess

from starlette.routing import Route

from command_center import db, jobs
from command_center.api.util import (DESK_GROUPS, J, endpoint, err, cost_usd, INR,
                                     breaker_state, budget_state)
from shared import budget
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
    ("Tech steward",           "last_tech_steward_at", "weekly",     "force_tech_steward", "1"),
    ("Belief scout",           "last_belief_scout_at", "weekly",     "force_belief_scout", "1"),
    # Cadence is a setting, not a constant — the Beliefs view owns it.
    ("Belief desk piece",      "last_belief_run_at",   "cadence",    "force_belief_run", "1"),
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
            "SELECT id, created_at, source, throughline, trust_gate, status, desk "
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
        # (desk, status) counts serve BOTH the stat tiles and the desk tabs — the
        # tiles are just this aggregated over whichever desk is being viewed, so
        # the old separate status-only query was a second round trip for a number
        # already in this one.
        desk_counts=lambda: db.q("SELECT desk, status, COUNT(*) AS n FROM pipeline_runs "
                                 "GROUP BY desk, status"),
        lists=fetch_lists,
        agents=lambda: db.q("SELECT skill, model, topic, started_at "
                            "FROM active_agents ORDER BY started_at"),
        digs=safe_digs,
        daily=lambda: get_daily_costs(days=1),
        breaker=breaker_state,
        cap=budget.cap_usd,
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
    # Desk scope. The lists are already in memory, so this filters rather than
    # re-queries; the tab counts are always for BOTH desks, because a tab that
    # only knows its own number can't tell you there is work on the other one.
    desks = DESK_GROUPS.get((request.query_params.get("desk") or "all").lower())

    def in_scope(row):
        return desks is None or (row.get("desk") or "news") in desks

    counts, tabs = {}, {"news": 0, "belief": 0}
    for row in r["desk_counts"]:
        d, st, n = (row.get("desk") or "news"), row["status"], row["n"]
        if desks is None or d in desks:
            counts[st] = counts.get(st, 0) + n
        if st == "pending_human":
            tabs["belief" if d in ("ek", "gk") else "news"] += n

    lists = [x for x in r["lists"] if in_scope(x)]
    gate = [x for x in lists if x["status"] == "pending_human"][:30]
    held = [x for x in lists if x["status"] in ("held", "hold", "needs_attention")][:20]
    recent = lists[:10]
    today = datetime.date.today().isoformat()
    today_usd = sum(cost_usd(x["model"], x["in_tok"], x["out_tok"])
                    for x in r["daily"] if str(x["day"])[:10] == today)
    return J({
        "counts": counts,
        "desk_tabs": tabs,
        # In-RAM, so the banner that tells him a reel is still building costs the
        # overview nothing. It is on this screen because "I started a build and
        # can't find it" was the failure — Activity has the detail.
        "jobs_running": _label_jobs(jobs.active()),
        "gate": gate,
        "held": held,
        "agents": r["agents"],
        "recent": recent,
        "digs": r["digs"],
        "breaker": r["breaker"],
        "voice_up": voice_status(),
        "published": counts.get("published", 0),
        "today_cost": {"usd": round(today_usd, 4), "inr": round(today_usd * INR, 2)},
        # Cap came from the fan-out and today's spend is already computed —
        # the banner costs no extra round trip.
        "budget": {"cap_usd": r["cap"], "spent_today_usd": round(today_usd, 4),
                   "over": r["cap"] is not None and today_usd >= r["cap"]},
    })


def _steward_paste(recs):
    """The recommendations as a copy-pasteable checklist."""
    if not recs:
        return ""
    out = ["TECH STEWARD — recommendations", ""]
    for i, r in enumerate(recs, 1):
        g = lambda k: str(r.get(k) or "").strip()
        line = f"{i}. [{g('area') or '?'}] {g('action')}"
        bits = []
        if g("from") or g("to"):
            bits.append(f"{g('from') or '?'} -> {g('to') or '?'}")
        if g("where"):
            bits.append(f"where: {g('where')}")
        if g("risk"):
            bits.append(f"risk: {g('risk')}")
        if r.get("saves_usd_mo") not in (None, ""):
            bits.append(f"saves ~${r['saves_usd_mo']}/mo")
        if bits:
            line += "\n   " + " · ".join(bits)
        if g("why"):
            line += f"\n   why: {g('why')}"
        if g("verify"):
            line += f"\n   verify: {g('verify')}"
        out.append(line)
    return "\n".join(out)


@endpoint
def system_status(request, data):
    r = db.parallel(
        stamps=lambda: db.kv_many([s[1] for s in SCHEDULES]),
        queue=lambda: db.q("SELECT id, topic, source, status, submitted_at "
                           "FROM pending_topics WHERE status IN ('queued','running') "
                           "ORDER BY id"),
        breaker=breaker_state,
        budget=budget_state,
        steward=lambda: db.kv_many(["latest_tech_brief", "latest_tech_recs",
                                    "last_tech_steward_at",
                                    "latest_tech_recs_error"]),
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
    sw = r["steward"]
    try:
        steward_recs = json.loads(sw.get("latest_tech_recs") or "[]")
    except (ValueError, TypeError):
        steward_recs = []
    from publishing import voices
    return J({
        "reel_voices": voices.available(),
        "reel_voice": (db.kv_many(["reel_voice"]).get("reel_voice") or "").strip()
                      or voices.default_name(),
        "breaker": r["breaker"],
        "budget": r["budget"],
        "steward": {"last": sw.get("last_tech_steward_at"),
                    "brief": sw.get("latest_tech_brief"),
                    "recs": steward_recs,
                    "error": sw.get("latest_tech_recs_error") or "",
                    # A plain-text rendering of the same list, so the memo can be
                    # copied out of the dashboard and pasted straight into a
                    # working session. The JSON is for the UI; this is for a human
                    # who wants the work started.
                    "paste": _steward_paste(steward_recs)},
        "voice_up": voice_status(),
        "schedules": scheds,
        "queue": r["queue"],
        "env": env_checks,
        "attend_hint": "./attend cycle",
        # Kept as a pointer only — Activity owns background work now. Slim: the
        # timelines and results would triple this payload for a footnote.
        "jobs": jobs.recent(10, slim=True),
        "jobs_summary": jobs.summary(),
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


# ── Background jobs (the Activity view) ───────────────────────────────────────
#
# The registry itself is RAM (see command_center/jobs.py for why). The only DB
# work here is turning `meta` ids into a story title, and that is cached for the
# life of the process: Activity polls every 2s, and a throughline that has
# already been read cannot usefully change under a job that is mid-flight, so
# re-reading it would spend a ~0.5s Railway round trip per poll on the one
# screen that has to feel live. Cold, it is at most three batched queries in
# parallel; warm, it is zero.
_LABELS = {}


def _in_sql(column, ids):
    """Portable `column IN (…)` — ANY() on Postgres, placeholders on the scratch
    sqlite the tests run against (db.q rewrites %s → ? for it)."""
    if db.is_postgres():
        return f"{column} = ANY(%s)", (list(ids),)
    return f"{column} IN ({','.join(['%s'] * len(ids))})", tuple(ids)


def _label_jobs(rows):
    """Attach `story` (+ the owning `run_id`) to each job from its meta ids."""
    want = {}   # (kind, id) -> None
    for j in rows:
        m = j.get("meta") or {}
        for key in ("run_id", "carousel_id", "reel_id"):
            if m.get(key) and (key, m[key]) not in _LABELS:
                want.setdefault(key, set()).add(m[key])

    def _fetch(sql_tpl, column, ids):
        clause, params = _in_sql(column, ids)
        return db.q(sql_tpl.format(where=clause), params)

    tasks = {}
    if want.get("run_id"):
        tasks["run_id"] = lambda ids=want["run_id"]: _fetch(
            "SELECT id, id AS run_id, throughline FROM pipeline_runs WHERE {where}",
            "id", ids)
    if want.get("carousel_id"):
        tasks["carousel_id"] = lambda ids=want["carousel_id"]: _fetch(
            "SELECT cr.id, cr.run_id, r.throughline FROM carousel_runs cr "
            "LEFT JOIN pipeline_runs r ON r.id = cr.run_id WHERE {where}", "cr.id", ids)
    if want.get("reel_id"):
        tasks["reel_id"] = lambda ids=want["reel_id"]: _fetch(
            "SELECT re.id, re.run_id, r.throughline FROM reels re "
            "LEFT JOIN pipeline_runs r ON r.id = re.run_id WHERE {where}", "re.id", ids)
    if tasks:
        try:
            for key, found in db.parallel(**tasks).items():
                for row in found:
                    _LABELS[(key, row["id"])] = {"story": row.get("throughline"),
                                                 "run_id": row.get("run_id")}
        except Exception:
            pass    # a label is decoration; never let it fail the Activity poll

    for j in rows:
        m = j.get("meta") or {}
        for key in ("run_id", "carousel_id", "reel_id"):
            hit = _LABELS.get((key, m.get(key)))
            if hit:
                j["story"] = hit["story"]
                j["run_id"] = hit["run_id"]
                break
    return rows


@endpoint
def job_status(request, data):
    """Full detail for one job — includes the stage timeline and the result."""
    j = jobs.view(jobs.get(request.path_params["jid"]))
    if not j:
        return err("no such job", 404)
    return J(_label_jobs([j])[0])


@endpoint
def jobs_recent(request, data):
    """The Activity list. Same five wire params as every other list surface
    (q / status / sort / limit / offset) so the shared `listBar` drives it, plus
    `kind`; `running` rides along unfiltered because "what is building right
    now" must not be hideable behind a filter — that was the whole complaint."""
    qp = request.query_params
    try:
        limit = min(max(int(qp.get("limit") or 40), 1), 200)
    except ValueError:
        limit = 40
    try:
        offset = max(int(qp.get("offset") or 0), 0)
    except ValueError:
        offset = 0
    status = (qp.get("status") or "all").strip()
    kind = (qp.get("kind") or "all").strip()
    q = (qp.get("q") or "").strip()
    rows, total = jobs.query(q=q, state=status, kind=kind, limit=limit, offset=offset)
    if (qp.get("sort") or "newest") == "oldest":
        rows = list(reversed(rows))     # `query` returns newest-first
    running = jobs.active()
    _label_jobs(rows + running)
    return J({"jobs": rows, "running": running, "summary": jobs.summary(),
              "total": total, "limit": limit, "offset": offset,
              "sort": qp.get("sort") or "newest", "status": status or "all",
              "kind": kind, "q": q})


@endpoint
def jobs_summary(request, data):
    """Nav-badge poll — pure RAM, no DB, safe to hit every few seconds."""
    return J(jobs.summary())


@endpoint
def set_reel_voice(request, data):
    """The default voice for reels. Stored in kv so it survives a restart and so
    the engine and the command centre agree without a config file each."""
    from publishing import voices
    name = (data.get("voice") or "").strip()
    if name:
        try:
            voices.resolve(name)
        except ValueError as e:
            return err(str(e))
    kv_set("reel_voice", name)
    return J({"ok": True, "voice": name or voices.default_name(),
              "note": f"Reels will be narrated by {name or voices.default_name()}."})


@endpoint
def set_budget(request, data):
    """Set the daily spend cap. 0 disables the governor entirely."""
    try:
        usd = float(data.get("usd"))
    except (TypeError, ValueError):
        return err("usd must be a number")
    try:
        budget.set_cap_usd(usd)
    except ValueError as e:
        return err(str(e))
    return J({"ok": True, "budget": budget_state()})


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
    Route("/system/budget", set_budget, methods=["POST"]),
    Route("/system/voice-default", set_reel_voice, methods=["POST"]),
    Route("/jobs", jobs_recent, methods=["GET"]),
    # Before the {jid} pattern — Starlette matches in order and "summary" is a
    # legal job id as far as the path converter is concerned.
    Route("/jobs/summary", jobs_summary, methods=["GET"]),
    Route("/jobs/{jid}", job_status, methods=["GET"]),
]
