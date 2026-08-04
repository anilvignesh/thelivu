"""The belief desks' discovery + cadence: keep candidates flowing, and take an
approved one to the human gate on a clock.

Two entry points, both called from the engine tick (run.py):

    run_belief_scout()   weekly — proposes candidates into belief_queue
    run_belief_cycle()   on cadence — takes ONE approved belief through the desk

The split matters. The scout proposes and stops; a proposal waits for the owner
(docs/everyone-knows-desk.md §6). The cycle only ever picks up what the owner
approved, so the desk cannot decide by itself what belief is worth a research
pass. The one exception is deliberate and off by default — `belief_auto_pursue`
lets the cycle promote the top proposal when the approved queue is empty, for
when Anil is away and would rather come back to drafts than to an idle desk.
Either way nothing publishes: the cycle's last act is `status='pending_human'`.
"""
import logging
import re

import yaml

from pathlib import Path

log = logging.getLogger("belief-desk")

THEMES_YAML = Path(__file__).parent / "themes.yaml"

# How much of the daily cap the belief desks may find already spent before they
# stand down for the day. The news desk is the priority claim on that budget —
# it has a clock and this desk does not, so a busy news day defers a belief
# piece rather than competing with it.
BUDGET_HEADROOM = 0.55

CADENCE_KEY = "belief_cadence_days"
LAST_RUN_KEY = "last_belief_run_at"
AUTO_PURSUE_KEY = "belief_auto_pursue"
DEFAULT_CADENCE_DAYS = 3


def themes():
    try:
        data = yaml.safe_load(THEMES_YAML.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.error("themes.yaml unreadable: %s", e)
        return []
    return [t for t in (data.get("themes") or [])
            if (t.get("status") or "active") == "active"]


def _themes_block():
    out = []
    for t in themes():
        line = (f"- id: {t.get('id')}\n"
                f"  question: {t.get('question', '')}\n"
                f"  why: {t.get('why', '')}\n")
        if t.get("records"):
            line += f"  records: {', '.join(t['records'])}\n"
        if t.get("caution"):
            line += f"  CAUTION: {t['caution']}\n"
        if t.get("routes_to") and t["routes_to"] != "any":
            line += f"  lane: {t['routes_to']}\n"
        out.append(line)
    return "\n".join(out)


def parse_candidates(text):
    """Parse the scout's CANDIDATE blocks. Unknown/missing fields come back
    empty; a block with no CANDIDATE line is skipped rather than guessed at."""
    out = []
    blocks = re.split(r"\n(?=CANDIDATE:)", text or "")
    for b in blocks:
        if not re.match(r"^\s*CANDIDATE:", b):
            continue

        def f(label):
            m = re.search(rf"^{label}:[ \t]*(.+)$", b, re.IGNORECASE | re.MULTILINE)
            return m.group(1).strip() if m else ""

        belief = f("CANDIDATE")
        if not belief:
            continue
        lane = f("LANE").lower()
        out.append({
            "belief": belief,
            "theme": f("THEME"),
            "lane": lane if lane in ("ek", "gk") else "",
            "note": "\n".join(x for x in (
                f"currency: {f('CURRENCY')}" if f("CURRENCY") else "",
                f"record: {f('RECORD')}" if f("RECORD") else "",
                f"so what: {f('SO_WHAT')}" if f("SO_WHAT") else "") if x),
        })
    return out


def run_belief_scout():
    """Propose candidate beliefs into the queue. Returns the number added."""
    from engine.agents.skill_runner import run_skill
    from shared.db import add_belief_candidate, kv_set, taken_beliefs
    from datetime import datetime, timezone

    tb = taken_beliefs()
    taken = ("BELIEFS THIS DESK HAS ALREADY TAKEN (do not re-propose these or "
             "near-duplicates):\n" + "\n".join(f"- {b}" for b in tb)) if tb else \
            "This desk has taken no beliefs yet."

    prompt = (f"Propose candidate received beliefs for the belief desks.\n\n"
              f"STANDING THEMES:\n\n{_themes_block()}\n\n{taken}\n\n"
              f"Work several themes, not one. Search for how each belief is stated "
              f"today AND for the record that would complicate it, separately.")

    out = run_skill("ek:belief-scout", prompt, max_tokens=8192, topic="belief scout")
    cands = parse_candidates(out)
    if not cands:
        log.info("belief-scout: no candidates parsed")
        kv_set("last_belief_scout_at", datetime.now(timezone.utc).isoformat())
        return 0

    added = 0
    for c in cands:
        qid = add_belief_candidate(c["belief"], source="scout", theme=c["theme"],
                                   lane=c["lane"], note=c["note"])
        if qid:
            added += 1
        else:
            log.info("belief-scout: duplicate, skipped — %s", c["belief"][:70])
    kv_set("last_belief_scout_at", datetime.now(timezone.utc).isoformat())
    log.info("belief-scout: %d/%d candidates queued as proposals", added, len(cands))

    if added:
        try:
            from engine.agents.orchestrator import _notify
            _notify(f"🧠 Belief scout: {added} new candidate(s) waiting for your nod "
                    f"in the command centre.")
        except Exception as e:
            log.warning("belief-scout notify failed: %s", e)
    return added


def cadence_days():
    from shared.db import kv_get
    raw = (kv_get(CADENCE_KEY) or "").strip()
    try:
        val = float(raw)
        return val if val > 0 else DEFAULT_CADENCE_DAYS
    except ValueError:
        return DEFAULT_CADENCE_DAYS


def cycle_due(now_utc):
    """Is a belief piece due? Cadence only — the budget and queue checks belong
    to the run itself so their reasons can be logged separately."""
    from datetime import datetime
    from shared.db import kv_get
    last = kv_get(LAST_RUN_KEY)
    if not last:
        return True
    try:
        return (now_utc - datetime.fromisoformat(last)).total_seconds() >= cadence_days() * 86400
    except ValueError:
        return True


def _promote_a_proposal():
    """Only when belief_auto_pursue is on. Returns the promoted row or None."""
    from shared.db import kv_get, list_belief_queue, set_belief_status
    if str(kv_get(AUTO_PURSUE_KEY) or "").strip() not in ("1", "true", "on", "yes"):
        return None
    props = list_belief_queue(status="proposed", limit=50)
    if not props:
        return None
    row = props[-1]  # the list comes back newest-first; take the oldest proposal
    set_belief_status(row["id"], "queued", result="auto-pursued (belief_auto_pursue)")
    log.info("belief cycle: auto-pursuing proposal #%s", row["id"])
    return row


def run_belief_cycle():
    """Take ONE approved belief to the human gate, if the day allows it.

    Returns a short string saying what happened — the tick logs it, and it is
    the honest answer to "why didn't the belief desk run today?".
    """
    from datetime import datetime, timezone
    from shared import budget
    from shared.db import kv_set, pop_next_belief, set_belief_status
    from engine.desks.ek.pipeline import run_belief

    spent, cap, over = budget.status()
    if cap is not None and spent >= cap * BUDGET_HEADROOM:
        return (f"skipped: ${spent:.2f} of the ${cap:.2f} cap already spent — the "
                f"news desk has the prior claim on it")

    row = pop_next_belief()
    if not row and _promote_a_proposal():
        row = pop_next_belief()   # claim it properly, with the same lock
    if not row:
        return "skipped: nothing approved in the queue"

    # Stamp BEFORE the work, like every other sweep in run.py: a failure halfway
    # through must not re-enter on the next 2-minute tick and spend again.
    kv_set(LAST_RUN_KEY, datetime.now(timezone.utc).isoformat())
    log.info("belief cycle: running queue #%s — %s", row["id"], row["belief"][:80])

    try:
        res = run_belief(row["belief"])
    except Exception as e:
        set_belief_status(row["id"], "queued", result=f"failed: {e}")
        log.error("belief cycle failed on queue #%s: %s", row["id"], e, exc_info=True)
        return f"failed: {e}"

    verdict = res.get("verdict") or ""
    if not res.get("run_id"):
        set_belief_status(row["id"], "done",
                          result=f"{verdict or 'stopped'} at {res.get('stopped_at')}"
                                 + (f" — {res['reason']}" if res.get("reason") else ""))
        return f"{verdict} (no run — {res.get('stopped_at')})"

    set_belief_status(row["id"], "done", run_id=res["run_id"],
                      result=f"{verdict} → {res.get('gate')} → {res.get('status')}")
    try:
        from engine.agents.orchestrator import _notify
        _notify(f"🧠 Belief desk: run #{res['run_id']} ({res.get('series', '')}) is "
                f"{res.get('status', 'parked')} — {row['belief'][:90]}")
    except Exception as e:
        log.warning("belief cycle notify failed: %s", e)
    return f"run #{res['run_id']}: {verdict} → {res.get('gate')} → {res.get('status')}"
