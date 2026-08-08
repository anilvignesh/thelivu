"""The belief desks: intake, the scout's proposals, and the cadence.

Everything here is a queue operation plus a signal. The desk's actual work — the
gate call, the record, the writer — runs on the Railway engine, which is where
the API keys and the cost table live, so this module never calls a model: it
writes a row and sets the kv flag the engine's tick reads (`force_belief_run`,
`force_belief_scout`). Same pattern as the source scout's "Run now".
"""
from starlette.routing import Route

from command_center.api.util import J, endpoint, err
from shared.db import (add_belief_candidate, list_belief_queue, set_belief_status,
                       kv_get, kv_set)

# What the owner can do to a queue row, and what it means. `run` is `approve`
# plus a nudge to the engine so he doesn't wait out the cadence.
ACTIONS = {"approve", "drop", "run", "requeue"}


def _themes():
    try:
        import yaml
        from shared.config import REPO_ROOT
        p = REPO_ROOT / "engine" / "desks" / "ek" / "themes.yaml"
        if p.exists():
            return yaml.safe_load(p.read_text()).get("themes", []) or []
    except Exception:
        pass
    return []


@endpoint
def beliefs_state(request, data):
    from datetime import datetime, timezone

    from command_center import db as ccdb
    from engine.desks.ek.scout import cadence_days, next_turn_utc

    now_utc = datetime.now(timezone.utc)
    r = ccdb.parallel(
        proposed=lambda: list_belief_queue(status="proposed", limit=60),
        queued=lambda: list_belief_queue(status="queued", limit=60),
        recent=lambda: list_belief_queue(limit=40),
        settings=lambda: {k: kv_get(k) for k in
                          ("last_belief_scout_at", "last_belief_run_at",
                           "belief_auto_pursue", "belief_cadence_days",
                           # What the last cadence check decided, and what the
                           # last scout run found. Both are the answer to "why
                           # is this desk quiet?", which the timestamps alone
                           # cannot give — a desk that stood down for budget and
                           # a desk with an empty queue look identical from a
                           # `last_run_at` that never moved.
                           "last_belief_cycle_result", "last_belief_scout_result")},
    )
    s = r["settings"]
    # Whose turn it is. The desks alternate (docs/alternating-desks.md), so "the
    # desk is quiet" has two very different meanings — it is not its turn, or it
    # is and something stopped it — and `last_run_at` alone cannot tell them
    # apart. `next_turn` is None exactly when the turn is today.
    nxt = next_turn_utc(now_utc)
    return J({
        "proposed": r["proposed"],
        "queued": r["queued"],
        # 'recent' is every row: the view shows what became of a belief, which is
        # the question the queue alone can't answer.
        "recent": r["recent"],
        "themes": _themes(),
        "cadence_days": cadence_days(),
        "turn_today": nxt is None,
        "next_turn": nxt.isoformat() if nxt else None,
        "auto_pursue": str(s.get("belief_auto_pursue") or "").strip() in
                       ("1", "true", "on", "yes"),
        "last_scout_at": s.get("last_belief_scout_at"),
        "last_run_at": s.get("last_belief_run_at"),
        "last_cycle_result": s.get("last_belief_cycle_result"),
        "last_scout_result": s.get("last_belief_scout_result"),
    })


@endpoint
def belief_add(request, data):
    """Owner-supplied belief. Lands 'queued' — his submission IS the approval
    (docs/everyone-knows-desk.md §6: owner-supplied jumps the queue)."""
    belief = (data.get("belief") or "").strip()
    if not belief:
        return err("a belief is required")
    if len(belief) > 400:
        return err("keep the belief to one sentence (400 chars)")
    qid = add_belief_candidate(belief, source="owner",
                               note=(data.get("note") or "").strip())
    if qid is None:
        return err("this desk has already taken that belief (or something very "
                   "like it) — check the list below")
    note = "Queued. The desk will pick it up on the next cadence."
    if data.get("run_now"):
        kv_set("force_belief_run", "1")
        note = "Queued and signalled — the engine picks it up within ~2 minutes."
    return J({"ok": True, "id": qid, "note": note})


@endpoint
def belief_action(request, data):
    qid = int(request.path_params["qid"])
    action = (data.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return err(f"unknown action {action!r}")
    if action == "drop":
        set_belief_status(qid, "dropped", result="dropped by owner")
        return J({"ok": True, "note": "Dropped."})
    if action in ("approve", "run"):
        set_belief_status(qid, "queued", result="approved by owner")
        if action == "run":
            kv_set("force_belief_run", "1")
            return J({"ok": True, "note": "Approved and signalled — the engine "
                                          "picks it up within ~2 minutes."})
        return J({"ok": True, "note": "Approved. It runs on the next cadence."})
    # requeue: a row that failed or was dropped goes back to waiting
    set_belief_status(qid, "queued", result="requeued by owner")
    return J({"ok": True, "note": "Back in the queue."})


@endpoint
def belief_scout_run(request, data):
    kv_set("force_belief_scout", "1")
    return J({"ok": True, "note": "Scout signalled — proposals appear here when "
                                  "it finishes (a few minutes)."})


@endpoint
def belief_settings(request, data):
    """Cadence in days, and the auto-pursue switch.

    Auto-pursue is off by default and says so in the UI: with it on, the desk
    promotes its own scout's proposal when nothing is approved, which is a real
    change in who chooses what gets researched.
    """
    if "cadence_days" in data:
        try:
            days = float(data["cadence_days"])
        except (TypeError, ValueError):
            return err("cadence must be a number of days")
        if not 0.5 <= days <= 30:
            return err("cadence must be between 0.5 and 30 days")
        kv_set("belief_cadence_days", f"{days:g}")
    if "auto_pursue" in data:
        kv_set("belief_auto_pursue", "1" if data["auto_pursue"] else "")
    return J({"ok": True, "note": "Saved."})


routes = [
    Route("/beliefs", beliefs_state, methods=["GET"]),
    Route("/beliefs", belief_add, methods=["POST"]),
    Route("/beliefs/scout", belief_scout_run, methods=["POST"]),
    Route("/beliefs/settings", belief_settings, methods=["POST"]),
    Route("/beliefs/{qid:int}/action", belief_action, methods=["POST"]),
]
