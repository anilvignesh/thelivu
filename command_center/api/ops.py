"""Digs, chief of staff, sources, ingest, topics, costs."""
import json
import re

from starlette.routing import Route

from command_center import db
from command_center.api.util import J, endpoint, err, cost_usd, INR
from shared.db import (
    list_digs, get_dig, get_dig_updates, create_dig, update_dig, add_dig_update,
    queue_ingest, queue_topic, kv_get, kv_set, get_daily_costs,
    get_cost_report_data,
)

# ── Digs ──────────────────────────────────────────────────────────────────────

@endpoint
def digs_list(request, data):
    closed = request.query_params.get("closed") == "1"
    digs = list_digs(include_closed=closed)
    watchlist = []
    try:
        import yaml
        from shared.config import REPO_ROOT
        p = REPO_ROOT / "engine" / "watchlist.yaml"
        if p.exists():
            watchlist = yaml.safe_load(p.read_text()).get("themes", []) or []
    except Exception:
        pass
    return J({"digs": digs, "watchlist": watchlist})


@endpoint
def dig_detail(request, data):
    did = int(request.path_params["did"])
    d = get_dig(did)
    if not d:
        return err("no such dig", 404)
    return J({"dig": d, "updates": get_dig_updates(did)})


@endpoint
def dig_create(request, data):
    title = (data.get("title") or "").strip()
    if not title:
        return err("title required")
    did = create_dig(title=title,
                     question=(data.get("question") or "").strip(),
                     kerala_anchor=(data.get("kerala_anchor") or "").strip(),
                     hypothesis=(data.get("hypothesis") or "").strip(),
                     priority=int(data.get("priority") or 2),
                     watchlist_id=(data.get("watchlist_id") or "") or None,
                     owner_note="opened from command center")
    if data.get("advance"):
        kv_set("advance_dig_id", str(did))
    return J({"ok": True, "dig_id": did})


@endpoint
def dig_action(request, data):
    did = int(request.path_params["did"])
    if not get_dig(did):
        return err("no such dig", 404)
    action = data.get("action")
    if action == "advance":
        kv_set("advance_dig_id", str(did))
        return J({"ok": True, "note": "Next step queued (~2 min)."})
    if action == "promote":
        kv_set("promote_dig_id", str(did))
        return J({"ok": True, "note": "Promoting to the pipeline — it still ends at your gate."})
    if action == "park":
        update_dig(did, status="parked", next_action_at=None)
        return J({"ok": True})
    if action == "kill":
        update_dig(did, status="killed", next_action_at=None)
        return J({"ok": True})
    if action == "note":
        body = (data.get("body") or "").strip()
        if not body:
            return err("body required")
        add_dig_update(did, body, kind="note")
        return J({"ok": True})
    return err("action must be advance|promote|park|kill|note")


# ── Chief of staff ────────────────────────────────────────────────────────────

@endpoint
def cos_state(request, data):
    brief = kv_get("latest_cos_brief") or ""
    try:
        acted = json.loads(kv_get("latest_cos_actions") or "[]")
    except Exception:
        acted = []
    recs = []
    m = re.search(r"RECOMMENDATIONS\s*(\[.*?\])\s*END_RECOMMENDATIONS", brief, re.DOTALL)
    if m:
        try:
            recs = json.loads(m.group(1))
        except Exception:
            recs = []
    new_digs = []
    m2 = re.search(r"NEW_DIGS\s*(\[.*?\])\s*END_NEW_DIGS", brief, re.DOTALL)
    if m2:
        try:
            new_digs = json.loads(m2.group(1))
        except Exception:
            new_digs = []
    prose = re.split(r"RECOMMENDATIONS\s*\[", brief)[0].strip()
    return J({"last_at": kv_get("last_cos_at"), "acted": acted,
              "recommendations": recs, "new_digs": new_digs, "brief": prose})


@endpoint
def cos_run(request, data):
    kv_set("run_chief_of_staff", "1")
    return J({"ok": True, "note": "Sweep queued (~2 min)."})


# ── Sources ───────────────────────────────────────────────────────────────────

@endpoint
def sources_state(request, data):
    r = db.parallel(
        perf=lambda: db.q("""
            SELECT source,
                   COUNT(*) AS runs,
                   SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS published,
                   SUM(CASE WHEN status IN ('killed','kill') THEN 1 ELSE 0 END) AS killed,
                   SUM(CASE WHEN status IN ('held','hold') THEN 1 ELSE 0 END) AS held,
                   MAX(created_at) AS last_seen
            FROM pipeline_runs WHERE desk = 'news'
            GROUP BY source ORDER BY COUNT(*) DESC
        """),
        approved=lambda: db.q("SELECT id, name, platform, feed_url, lean, tier, role, added_at "
                              "FROM approved_sources WHERE status='active' ORDER BY id DESC"),
        proposals=lambda: db.q("SELECT id, name, platform, lean, tier, role, notes "
                               "FROM source_proposals WHERE status='pending' ORDER BY id DESC"),
        silent=lambda: db.q("SELECT key, value FROM kv_store WHERE key LIKE 'src_silent_%'"),
    )
    silent = {row["key"][len("src_silent_"):]: int(row["value"] or 0)
              for row in r["silent"] if str(row["value"] or "0").isdigit()}
    yaml_sources = []
    try:
        approved_names = {a["name"] for a in r["approved"]}
        for s in _load_yaml_sources():
            row = {k: s.get(k) for k in
                   ("id", "name", "platform", "tier", "role", "lean", "status")}
            row["has_feed"] = bool(s.get("feed"))
            row["activated"] = s.get("name") in approved_names
            row["silent_cycles"] = silent.get(str(s.get("id", "")).replace(" ", "_"), 0)
            yaml_sources.append(row)
    except Exception:
        pass
    return J({"performance": r["perf"], "yaml_sources": yaml_sources,
              "approved": r["approved"], "proposals": r["proposals"]})


@endpoint
def source_action(request, data):
    sid = int(request.path_params["sid"])
    action = data.get("action")
    if action == "approve":
        db.execute("INSERT INTO approved_sources (name, platform, lean, tier, role, notes) "
                   "SELECT name, platform, lean, tier, role, notes FROM source_proposals "
                   "WHERE id = %s", (sid,))
        db.execute("UPDATE source_proposals SET status='approved' WHERE id = %s", (sid,))
        return J({"ok": True})
    if action == "skip":
        db.execute("UPDATE source_proposals SET status='skipped' WHERE id = %s", (sid,))
        return J({"ok": True})
    if action == "deactivate":
        from shared.db import deactivate_approved_source
        return J({"ok": deactivate_approved_source(sid)})
    return err("action must be approve|skip|deactivate")


def _load_yaml_sources():
    import yaml
    from shared.config import REPO_ROOT
    p = REPO_ROOT / "engine" / "sources.yaml"
    if not p.exists():
        return []
    return yaml.safe_load(p.read_text()).get("sources", []) or []


@endpoint
def candidate_activate(request, data):
    """Activate a sources.yaml candidate from the dashboard: copy it into
    approved_sources, which the engine ingests on its next cycle (any platform
    with a feed). No repo edit, no deploy. Feed-less candidates (X/IG/web
    reference sources) still join the pool as context for source-scout /
    verification, but nothing auto-ingests from them."""
    cand_id = (data.get("id") or "").strip()
    cand = next((s for s in _load_yaml_sources()
                 if s.get("id") == cand_id and s.get("status") == "candidate"), None)
    if not cand:
        return err(f"no candidate '{cand_id}' in sources.yaml", 404)
    name = cand.get("name") or cand_id
    dup = db.q("SELECT id FROM approved_sources WHERE name = %s AND status='active'", (name,))
    if dup:
        return err(f"{name} is already active (approved_sources #{dup[0]['id']})")
    feed = cand.get("feed") or None
    db.execute(
        "INSERT INTO approved_sources (name, platform, handle, feed_url, lean, tier, role, notes) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (name, cand.get("platform") or "web", cand.get("handle") or "",
         feed, (cand.get("lean") or "")[:300], int(cand.get("tier") or 3),
         cand.get("role") or "lead", (cand.get("notes") or "")[:300]))
    if feed:
        note = f"{name} activated — the engine ingests its feed on the next cycle."
    else:
        note = (f"{name} activated as a reference source (no feed) — it joins the "
                f"source pool for scouting/verification context, but nothing "
                f"auto-ingests from it.")
    return J({"ok": True, "note": note, "ingests": bool(feed)})


@endpoint
def source_add(request, data):
    name = (data.get("name") or "").strip()
    url = (data.get("feed_url") or "").strip()
    if not name or not url:
        return err("name and feed_url required")
    db.execute("INSERT INTO approved_sources (name, platform, feed_url, lean, tier, role) "
               "VALUES (%s, %s, %s, %s, %s, 'lead')",
               (name, data.get("platform") or "web", url,
                (data.get("lean") or "").strip(), int(data.get("tier") or 2)))
    return J({"ok": True, "note": f"Added {name} — active on the next cycle."})


# ── Ingest & topics ───────────────────────────────────────────────────────────

@endpoint
def ingest_state(request, data):
    rows = db.q("SELECT id, topic, status, outcome, reason, submitted_at "
                "FROM pending_topics WHERE source='ingest' ORDER BY id DESC LIMIT 25")
    return J({"ingests": rows})


# A topic used to vanish the moment intake said no: status went to 'done' and the
# reasoning went to a Telegram card whose report link is on telegra.ph, which the
# owner's ISP blocks. This is where a submitted topic's fate is now readable.
@endpoint
def topic_outcomes(request, data):
    rows = db.q("SELECT id, topic, source, status, outcome, reason, run_id, "
                "submitted_at, decided_at FROM pending_topics "
                "ORDER BY id DESC LIMIT 100")
    for r in rows:
        # Rows decided before outcomes were recorded are honestly unknown; the
        # reasons are gone and guessing at them would be worse than saying so.
        if not r.get("outcome"):
            r["outcome"] = "unknown"
            r["reason"] = r["reason"] or "decided before outcomes were recorded"
    return J({"topics": rows})


# The engine used to speak only to Telegram. Owner's rule (2026-08-05): nothing
# may be visible only there. Every _notify_card lands here too.
@endpoint
def engine_events(request, data):
    # GET: `endpoint` only parses a JSON body for POST/PATCH/PUT/DELETE, so the
    # filters arrive as query params and `data` is empty here.
    qp = request.query_params
    kind = (qp.get("kind") or "").strip() or None
    level = (qp.get("level") or "").strip() or None
    try:
        limit = min(int(qp.get("limit") or 200), 500)
    except (TypeError, ValueError):
        limit = 200
    from shared.db import get_engine_events
    rows = get_engine_events(limit=limit, kind=kind, level=level)
    for r in rows:
        # The body is enough for the feed; the full report is a second click, so
        # a long steward sweep doesn't bloat every page load.
        r["has_report"] = bool(r.pop("report", None))
        r["created_at"] = str(r.get("created_at") or "")
    return J({"events": rows})


@endpoint
def engine_event_report(request, data):
    """The full report body for one event — the thing that used to exist only
    behind a telegra.ph link the owner cannot open."""
    try:
        eid = int(request.query_params.get("id") or 0)
    except (TypeError, ValueError):
        return err("bad event id")
    rows = db.q("SELECT id, kind, title, body, report, created_at "
                "FROM engine_events WHERE id = %s", (eid,))
    if not rows:
        return err(f"event #{eid} not found")
    return J({"event": rows[0]})


@endpoint
def topic_report(request, data):
    """The model's full intake output for one topic — the thing that used to
    live only behind a Telegraph link."""
    try:
        tid = int(request.query_params.get("id") or data.get("id") or 0)
    except (TypeError, ValueError):
        return err("bad topic id")
    rows = db.q("SELECT id, topic, outcome, reason, report FROM pending_topics "
                "WHERE id = %s", (tid,))
    if not rows:
        return err(f"topic #{tid} not found")
    return J({"topic": rows[0]})


@endpoint
def ingest_add(request, data):
    urls = [u.strip() for u in (data.get("urls") or [])
            if isinstance(u, str) and u.strip().startswith("http")]
    if not urls:
        return err("no valid http(s) URLs")
    note = (data.get("note") or "").strip()
    for u in urls:
        queue_ingest(u, note)
    return J({"ok": True, "queued": len(urls),
              "note": "The agent picks them up within ~2 minutes; drafts land at your gate."})


@endpoint
def topic_add(request, data):
    topic = (data.get("topic") or "").strip()
    if not topic:
        return err("topic required")
    queue_topic(topic, source="dashboard")
    return J({"ok": True, "note": "Queued — the agent picks it up within ~2 minutes."})


# ── Costs ─────────────────────────────────────────────────────────────────────

@endpoint
def costs(request, data):
    res = db.parallel(
        rep=get_cost_report_data,
        daily=lambda: get_daily_costs(days=30),
        by_skill=lambda: db.q(
            "SELECT skill, model, SUM(input_tokens) AS i, SUM(output_tokens) AS o, "
            "SUM(COALESCE(cache_write_tokens,0)) AS cw, "
            "SUM(COALESCE(cache_read_tokens,0)) AS cr, "
            "COUNT(*) AS calls FROM token_usage GROUP BY skill, model "
            "ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC"),
        pubs=lambda: db.q(
            "SELECT p.id, p.published_at, r.id AS run_id, r.throughline, r.source, "
            "r.trust_gate FROM publications p LEFT JOIN pipeline_runs r ON r.id = p.run_id "
            "ORDER BY p.id DESC LIMIT 50"),
    )
    rep = res["rep"]
    summary = {"today": 0.0, "month": 0.0, "total": 0.0}
    by_model = []
    for r in rep["by_model"]:
        t = cost_usd(r["model"], r["today_in"], r["today_out"],
                     r.get("today_cw"), r.get("today_cr"))
        mo = cost_usd(r["model"], r["month_in"], r["month_out"],
                      r.get("month_cw"), r.get("month_cr"))
        al = cost_usd(r["model"], r["total_in"], r["total_out"],
                      r.get("total_cw"), r.get("total_cr"))
        summary["today"] += t
        summary["month"] += mo
        summary["total"] += al
        by_model.append({"model": r["model"], "today_usd": t, "month_usd": mo,
                         "total_usd": al,
                         "total_tokens": (r["total_in"] or 0) + (r["total_out"] or 0)})
    daily = [{"day": str(x["day"])[:10], "model": x["model"],
              "usd": cost_usd(x["model"], x["in_tok"], x["out_tok"])}
             for x in res["daily"]]
    by_skill = res["by_skill"]
    for x in by_skill:
        x["usd"] = cost_usd(x["model"], x["i"], x["o"], x.get("cw"), x.get("cr"))
    return J({"summary": {k: round(v, 4) for k, v in summary.items()},
              "inr_rate": INR, "by_model": by_model, "daily": daily,
              "by_skill": by_skill, "publications": res["pubs"],
              "runs_today": rep["runs_today"]})


routes = [
    Route("/digs", digs_list, methods=["GET"]),
    Route("/digs", dig_create, methods=["POST"]),
    Route("/digs/{did:int}", dig_detail, methods=["GET"]),
    Route("/digs/{did:int}/action", dig_action, methods=["POST"]),
    Route("/cos", cos_state, methods=["GET"]),
    Route("/cos/run", cos_run, methods=["POST"]),
    Route("/sources", sources_state, methods=["GET"]),
    Route("/sources", source_add, methods=["POST"]),
    Route("/sources/candidates/activate", candidate_activate, methods=["POST"]),
    Route("/sources/{sid:int}/action", source_action, methods=["POST"]),
    Route("/ingest", ingest_state, methods=["GET"]),
    Route("/ingest", ingest_add, methods=["POST"]),
    Route("/topics", topic_add, methods=["POST"]),
    Route("/topics", topic_outcomes, methods=["GET"]),
    Route("/topics/report", topic_report, methods=["GET"]),
    Route("/events", engine_events, methods=["GET"]),
    Route("/events/report", engine_event_report, methods=["GET"]),
    Route("/costs", costs, methods=["GET"]),
]
