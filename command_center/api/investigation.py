"""The investigation surface: source health, findings, syntheses, freshness.

Read-mostly, and mostly a surfacing problem. 261 documents, five per-state
series and every cross-document finding the synthesise tier produces already
existed behind no interface at all.

**Freshness is a first-class field here, not a footnote.** Measured 2026-09-15:
the NH-projects dataset was last updated SIXTEEN MONTHS ago. A tile reading
*"88% of highway projects delayed in Arunachal Pradesh — from a dataset the
Ministry last updated 16 months ago"* is a stronger story than the number alone,
and it is a finding nobody else publishes. So the age is computed and shown
beside every band rather than being available on request:

    this month   parliamentary questions, enforcement orders
    this year    datasets, budgets
    the record   audit findings from the corpus

Three bands, never one "live" claim. A surface that implies everything on it is
current would make us wrong about the one thing we are uniquely positioned to
be right about.

The only writes here are a person's decisions — activating a source, promoting
or rejecting a synthesis. Nothing on this surface publishes anything.
"""
from datetime import datetime, timezone

from starlette.routing import Route

from command_center.api.util import J, endpoint, err
from shared.db import (
    digger_targets, set_digger_target_status, source_health, source_checks,
    syntheses, set_synthesis_status, corpus_coverage, state_findings,
)

# How old the newest material from a source may be and still sit in each band.
BANDS = (("this month", 31), ("this year", 365))


def _age_days(stamp):
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - t).days)


def _band(age_days):
    """Which band a source's newest material belongs in.

    `the record` is not a failure state — an audit report from 2019 is exactly
    what the corpus is for. It is a different CLAIM, which is the whole reason
    the bands exist."""
    if age_days is None:
        return "unknown"
    for name, limit in BANDS:
        if age_days <= limit:
            return name
    return "the record"


@endpoint
def investigation_state(request, data):
    """Everything the surface needs, in one call."""
    health = source_health()
    proposals = digger_targets(status="proposed")
    coverage = corpus_coverage()

    # Freshness, per source, from the newest document we hold of it.
    newest = {}
    for c in coverage:
        key = c.get("source_key")
        age = _age_days(c.get("last_read"))
        if key and (key not in newest or (age is not None and age < newest[key])):
            newest[key] = age
    bands = {"this month": [], "this year": [], "the record": [], "unknown": []}
    for key, age in sorted(newest.items()):
        bands[_band(age)].append({"source_key": key, "age_days": age})

    findings = state_findings(limit=5000)
    by_cat = {}
    for f in findings:
        by_cat[f.get("category") or "other"] = by_cat.get(f.get("category") or "other", 0) + 1

    return J({
        "sources": {
            "health": health,
            "needs_review": [h for h in health
                             if h["verdict"] in ("barren", "unreachable")],
            "proposals": proposals,
        },
        "corpus": {
            "documents": sum(c.get("docs") or 0 for c in coverage),
            "chars": sum(c.get("chars") or 0 for c in coverage),
            "entities": len({c.get("source_key") for c in coverage}),
            "bands": bands,
        },
        "findings": {"total": len(findings), "by_category": by_cat},
        "syntheses": {
            "new": syntheses(status="new", limit=100),
            "promoted": syntheses(status="promoted", limit=50),
        },
    })


@endpoint
def synthesis_dossier(request, data):
    """The evidence behind one synthesis, assembled for a person to judge.

    Deliberately not a summary. Every claim arrives with the verbatim span it
    was taken from and the document that span is in, because the decision this
    view exists to support — is this a story, or an accounting convention — is
    not one anybody should make from a headline."""
    from engine import synthesis as syn

    sid = int(request.path_params["sid"])
    rows = [s for s in syntheses(limit=500) if s["id"] == sid]
    if not rows:
        return err("no such synthesis", 404)
    return J({"synthesis": rows[0], "dossier": syn.draft_dossier(rows[0])})


@endpoint
def synthesis_action(request, data):
    sid = int(request.path_params["sid"])
    action = (data.get("action") or "").strip()
    if action not in ("promote", "reject"):
        return err("action must be promote or reject")
    n = set_synthesis_status(sid, "promoted" if action == "promote" else "rejected")
    return J({"ok": bool(n)}) if n else err("no such synthesis", 404)


@endpoint
def source_decide(request, data):
    """Activate or reject a proposed source. A PERSON does this, always.

    The scout gathers evidence and stops. Nothing that reaches the rotation got
    there without someone reading what it is — a bad story is caught at the
    verification gate, but a bad source quietly shapes every story that ever
    flows through it."""
    key = (data.get("key") or "").strip()
    action = (data.get("action") or "").strip()
    if not key or action not in ("activate", "reject"):
        return err("key and action (activate|reject) required")
    n = set_digger_target_status(
        key, "active" if action == "activate" else "rejected", decided_by="owner")
    return J({"ok": bool(n)}) if n else err("no such source", 404)


@endpoint
def scout_run(request, data):
    """Re-check every active source now, instead of waiting for the schedule."""
    from engine.digger import scout
    return J(scout.run_scout_cycle(notify=bool(data.get("notify"))))


@endpoint
def synthesis_run(request, data):
    """Re-run the detectors over the corpus. No model is called."""
    from engine import synthesis as syn
    found = syn.run(store=True)
    return J({"found": len(found),
              "kinds": sorted({s["kind"] for s in found})})


@endpoint
def source_checks_list(request, data):
    return J({"checks": source_checks(
        target_key=request.query_params.get("key"), limit=200)})


routes = [
    Route("/investigation", investigation_state, methods=["GET"]),
    Route("/investigation/checks", source_checks_list, methods=["GET"]),
    Route("/investigation/scout/run", scout_run, methods=["POST"]),
    Route("/investigation/sources/decide", source_decide, methods=["POST"]),
    Route("/investigation/syntheses/run", synthesis_run, methods=["POST"]),
    Route("/investigation/syntheses/{sid:int}", synthesis_dossier, methods=["GET"]),
    Route("/investigation/syntheses/{sid:int}/action", synthesis_action,
          methods=["POST"]),
]
