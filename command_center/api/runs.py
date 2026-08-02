"""Pipeline runs: browse, review, gate actions, human edits, AI suggestions.

Approve is the ONLY publishing action and goes through the ONE shared path
(publishing.publish.publish_run). The UI puts a confirm modal in front of it;
there is no bypass.
"""
import json
import os
import time

from starlette.routing import Route

from command_center import db, jobs
from command_center.api.util import (J, endpoint, err, breaker_state, list_query,
                                     SORTS_BASE)
from shared.db import get_run, update_run, kv_get, kv_set

_TG_LIMIT = 4096


def _tg_notify(text):
    """Best-effort note to the owner's draft chat (never fails the action)."""
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text[:_TG_LIMIT]}, timeout=15)
    except Exception:
        pass


# The status literals in pipeline_runs are not clean: the engine has written both `hold`
# and `held`, and both `kill` and `killed`, over its life. The UI offers one label per
# real state and this maps it to every spelling that means it — filtering on the literal
# alone silently hides rows (9 killed runs, today).
RUN_STATUS_GROUPS = {
    "held": ["held", "hold", "needs_attention"],
    "killed": ["killed", "kill"],
    "dropped": ["dropped", "drop"],
}

RUN_SORTS = dict(SORTS_BASE, updated="updated_at DESC NULLS LAST")

# The desks that may appear in a `desk=` filter. A whitelist for the same reason
# the sorts are one: this value reaches a WHERE clause.
DESKS = ("news", "ek", "gk")


@endpoint
def list_runs(request, data):
    lq = list_query(request, sorts=RUN_SORTS)
    lq.filter_status("status", RUN_STATUS_GROUPS)
    lq.search("throughline", "source")
    # Desk filter. Whitelisted like the sorts are — request text never reaches SQL,
    # and an unknown value falls through to "all" rather than erroring.
    desk = (request.query_params.get("desk") or "all").lower()
    if desk in DESKS:
        lq.add("desk = %s", desk)
    rows = db.q("SELECT id, created_at, updated_at, source, throughline, trust_gate, "
                "status, slug, desk FROM pipeline_runs" + lq.where_sql() + lq.page_sql(),
                lq.page_params())
    total = db.q(lq.count_sql("pipeline_runs"), tuple(lq.params))[0]["n"]
    return J({"runs": rows, **lq.envelope(total)})


@endpoint
def run_detail(request, data):
    rid = int(request.path_params["rid"])
    r = db.parallel(
        run=lambda: get_run(rid),
        carousels=lambda: db.q("SELECT id, status, caption, ig_permalink, dark, article_url "
                               "FROM carousel_runs WHERE run_id = %s ORDER BY id DESC", (rid,)),
        reels=lambda: db.q("SELECT id, kind, caption, status, ig_permalink, created_at, "
                           "posted_at FROM reels WHERE run_id = %s ORDER BY id DESC", (rid,)),
        pub=lambda: db.q("SELECT id, published_at, confidence FROM publications "
                         "WHERE run_id = %s", (rid,)),
        suggestions=lambda: kv_get(f"cc_suggest_{rid}"),
    )
    run = r["run"]
    if not run:
        return err("no such run", 404)
    base = os.environ.get("SLIDE_SERVER_BASE_URL", "").rstrip("/")
    article_url = f"{base}/a/{run['slug']}" if base and run.get("slug") else None
    return J({"run": run, "carousels": r["carousels"], "reels": r["reels"],
              "publication": r["pub"][0] if r["pub"] else None,
              "article_url": article_url,
              "suggestions": r["suggestions"]})


@endpoint
def approve(request, data):
    """Publish — the gated action, via the ONE shared path, as a job."""
    rid = int(request.path_params["rid"])
    run = get_run(rid)
    if not run:
        return err("no such run", 404)
    if run["status"] not in ("pending_human", "held", "hold", "needs_attention"):
        return err(f"run #{rid} is '{run['status']}' — only gate/held runs can be approved")

    def do_publish(progress):
        progress(0.1, f"Publishing run #{rid}…")
        from publishing.publish import publish_run
        res = publish_run(rid)
        if res.get("ok"):
            extra = f"article page /a/{res['slug']}" if res.get("slug") else "plain-text post"
            progress(1.0, f"Published ({res['how']}, {extra})")
            _tg_notify(f"✅ Published run #{rid} from the command center ({res['how']}).")
        return res

    return J({"ok": True, "job": jobs.submit(f"publish run #{rid}", do_publish,
                                             {"run_id": rid}, kind="publish")})


_SIMPLE_ACTIONS = {
    "kill":    ("killed",        "❌ Story #%d killed from command center."),
    "hold":    ("held",          "⏸ Story #%d held from command center."),
    "requeue": ("pending_human", None),
}


@endpoint
def run_action(request, data):
    rid = int(request.path_params["rid"])
    action = data.get("action")
    if action not in _SIMPLE_ACTIONS:
        return err("action must be kill|hold|requeue")
    if not get_run(rid):
        return err("no such run", 404)
    status, note = _SIMPLE_ACTIONS[action]
    update_run(rid, status=status)
    if note:
        _tg_notify(note % rid)
    return J({"ok": True, "status": status})


@endpoint
def recheck(request, data):
    """Re-develop the story, optionally with the owner's editorial direction.
    This is the 'regenerate article' path — the engine reruns the spine."""
    rid = int(request.path_params["rid"])
    run = get_run(rid)
    if not run:
        return err("no such run", 404)
    note = (data.get("note") or "").strip()
    if note:
        kv_set(f"recheck_note_{rid}", note)
    update_run(rid, status="recheck_requested")
    b = breaker_state()
    hint = (f"Breaker is open ({b['reason']}) — the recheck runs when credit is back, "
            f"or run it attended: ./attend cycle") if b["open"] else \
           "Queued — the engine recchecks it on its next tick."
    return J({"ok": True, "note": hint, "breaker": b})


@endpoint
def edit_draft(request, data):
    """Human edit of the draft text — the gate working, not an LLM."""
    rid = int(request.path_params["rid"])
    run = get_run(rid)
    if not run:
        return err("no such run", 404)
    if run["status"] == "published":
        return err("run is already published — corrections go through a new run")
    text = data.get("draft_text")
    if not isinstance(text, str) or not text.strip():
        return err("draft_text required")
    update_run(rid, draft_text=text)
    return J({"ok": True})


@endpoint
def suggest(request, data):
    """AI editorial suggestions on a PRE-approval draft (editorial-reviewer).
    Journalism = Claude/Gemini only (owner's model split) — quota-aware:
    when the breaker is open we say so and name the attended path instead."""
    rid = int(request.path_params["rid"])
    run = get_run(rid)
    if not run:
        return err("no such run", 404)
    if run["status"] == "published":
        return err("never run an LLM over an approved draft")
    if not (run.get("draft_text") or "").strip():
        return err("run has no draft text yet")
    b = breaker_state()
    if b["open"]:
        return J({"ok": False, "blocked": b["reason"], "until": b["until"],
                  "hint": "APIs are dry — get suggestions attended (Claude session) instead."},
                 409)

    def do_suggest(progress):
        progress(0.2, "Running editorial-reviewer…")
        from engine.agents.skill_runner import run_skill
        text = run_skill(
            "editorial-reviewer",
            f"Review this draft and give concrete, ranked suggestions for "
            f"improvement (do NOT rewrite it):\n\n{run['draft_text']}\n\n"
            f"Verification report for context:\n{run.get('verification_report') or '—'}",
            run_id=rid, topic="cc-suggestions")
        kv_set(f"cc_suggest_{rid}", text)
        progress(1.0, "Suggestions ready")
        return {"ok": True, "suggestions": text}

    return J({"ok": True, "job": jobs.submit(f"suggestions for run #{rid}", do_suggest,
                                             {"run_id": rid}, kind="suggest")})


routes = [
    Route("/runs", list_runs, methods=["GET"]),
    Route("/runs/{rid:int}", run_detail, methods=["GET"]),
    Route("/runs/{rid:int}", edit_draft, methods=["PATCH"]),
    Route("/runs/{rid:int}/approve", approve, methods=["POST"]),
    Route("/runs/{rid:int}/action", run_action, methods=["POST"]),
    Route("/runs/{rid:int}/recheck", recheck, methods=["POST"]),
    Route("/runs/{rid:int}/suggest", suggest, methods=["POST"]),
]
