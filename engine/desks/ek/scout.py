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

Everything below the entry points is there because this runs UNATTENDED on
Railway, where nobody is watching the return value:

- **A quiet desk must be cheap and explicable.** The cadence stamp is only
  written when a piece actually runs, so an empty queue leaves the cycle "due"
  for good and the 2-minute tick would call it 720 times a day — three Railway
  round trips and an INFO line each. `_quiet_until` backs that off, and the
  reason is written to kv so "why didn't it run?" is answerable without reading
  logs.
- **A restart is normal, not exceptional.** Every deploy kills the process, and
  `pop_next_belief()` has already flipped its row to `running`. Nothing else in
  the system would ever move it back, and the command centre shows a `running`
  row with no button on it. The cycle reclaims those itself, counting attempts
  so a belief that kills the engine every time is parked rather than retried
  forever.
- **A timestamp that won't parse must not silence the desk.** `cycle_due` used
  to catch only `ValueError`; a naive (tz-less) stamp raises `TypeError` on the
  subtraction, which run.py would have logged every two minutes while the desk
  never ran again. Same class of bug as the `_last_rss_run` retry storm, in the
  opposite direction.
"""
import logging
import re

import yaml

from pathlib import Path

log = logging.getLogger("belief-desk")

THEMES_YAML = Path(__file__).parent / "themes.yaml"

# How much of the daily cap the belief desks may find already spent before they
# stand down. This USED to be the whole scheduling policy — the news desk had the
# standing prior claim and the belief block ran after the RSS cycle, so the desk
# only ran on a day the news desk left 45% of the cap unspent. Measured over the
# fortnight to 2026-08-08, there was no such day: spend cleared 55¢ every single
# day the engine ran, and the belief desk never fired once. An unsatisfiable test
# is not a priority rule, it is an off switch.
#
# The desks alternate now (docs/alternating-desks.md). On its turn the belief
# desk goes FIRST — run.py calls the cycle before the RSS block — so this check
# passes on a fresh $0.00 cap rather than on the news desk's leavings.
#
# The threshold stays because it still has two jobs, both of them late-in-the-day
# cases: a `force_belief_run` tapped by hand at 3pm on a spent day, and a turn
# day whose engine only came up at 20:00 after a restart. Standing down does not
# stamp LAST_RUN_KEY, so in the second case the turn carries to tomorrow.
BUDGET_HEADROOM = 0.55

CADENCE_KEY = "belief_cadence_days"
LAST_RUN_KEY = "last_belief_run_at"
AUTO_PURSUE_KEY = "belief_auto_pursue"
LAST_RESULT_KEY = "last_belief_cycle_result"
LAST_SCOUT_KEY = "last_belief_scout_at"
LAST_SCOUT_RESULT_KEY = "last_belief_scout_result"
# Two, because the desks alternate: news day, belief day, news day. Turn-taking
# rather than calendar parity — a turn missed to a restart or a genuinely spent
# day leaves the desk due, so it takes the next available day instead of waiting
# out another full cycle for its parity to come round.
DEFAULT_CADENCE_DAYS = 2

# Same bounds the command centre enforces (command_center/api/beliefs.py). They
# are repeated here because kv is writable from psql and from the bot, and a
# cadence of `inf` parses fine and means "never run again".
MIN_CADENCE_DAYS = 0.5
MAX_CADENCE_DAYS = 30

# How long the cycle waits before re-asking a question it just answered with
# "nothing to do". Nothing is lost by waiting: an owner who wants it sooner
# presses Run now, which sets force_belief_run and bypasses this entirely.
QUIET_RECHECK_SECONDS = 15 * 60

# A belief that fails this many times stops being retried and is parked as
# 'dropped' — the one non-terminal status the command centre offers a Requeue
# button on. Do NOT invent a new status here: the Beliefs view lists exactly
# proposed / queued / done / dropped / running, so anything else is invisible.
MAX_ATTEMPTS = 3

# Ceiling on what one scout run may add. The skill asks for three to eight; a
# model that returns forty has misunderstood the job, and each row it adds is a
# gate call somebody eventually pays for.
MAX_CANDIDATES_PER_RUN = 12
MIN_BELIEF_CHARS = 20
MAX_BELIEF_CHARS = 400   # pipeline.py truncates throughline at 400; reject rather than truncate

# In-process only, and deliberately so: this is a back-off, not state. A restart
# losing it costs one extra queue check, which is the right way round — the
# cadence itself lives in kv where a restart cannot touch it.
_quiet_until = None
_last_reason = None


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


def parse_utc(raw):
    """A kv timestamp as an aware UTC datetime, or None if it is unusable.

    Tolerant on purpose. These keys are written by this module but are also
    readable/writable from psql, the bot and the command centre, and the failure
    mode of being strict is not a crash the owner sees — it is a desk that
    silently never runs again.
    """
    from datetime import datetime, timezone

    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "on", "yes")


def parse_candidates(text):
    """Parse the scout's CANDIDATE blocks. Unknown/missing fields come back
    empty; a block with no CANDIDATE line is skipped rather than guessed at.

    The three evidence fields are returned separately as well as folded into
    `note`, because `validate_candidate` has to be able to see whether a record
    was named at all — that is the difference between a candidate and a hunch.
    """
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
        # "LANE: ek (Everyone Knows)" is the same answer as "LANE: ek" and used
        # to be thrown away as neither.
        lane_m = re.match(r"[a-z]+", f("LANE").strip().lower())
        lane = lane_m.group(0) if lane_m else ""
        currency, record, so_what = f("CURRENCY"), f("RECORD"), f("SO_WHAT")
        out.append({
            "belief": belief,
            "theme": f("THEME"),
            "lane": lane if lane in ("ek", "gk") else "",
            "currency": currency,
            "record": record,
            "so_what": so_what,
            "note": "\n".join(x for x in (
                f"currency: {currency}" if currency else "",
                f"record: {record}" if record else "",
                f"so what: {so_what}" if so_what else "") if x),
        })
    return out


def validate_candidate(c):
    """Empty string if this candidate is worth a gate call, else why not.

    Mechanical enforcement of the two conditions the skill states as mandatory
    ("Both of these must hold, or it is not a candidate"): evidence that the
    belief circulates now, and a named record. A model under a token squeeze
    drops the trailing fields first, so the block that survives a truncated
    response is exactly the one that has neither — and that is the shape of
    candidate that burns a whole research pass for nothing.
    """
    b = (c.get("belief") or "").strip()
    if len(b) < MIN_BELIEF_CHARS:
        return "too short to be a belief"
    if len(b) > MAX_BELIEF_CHARS:
        return f"longer than {MAX_BELIEF_CHARS} chars — a belief is one sentence"
    if "<" in b and ">" in b:
        return "looks like the output template, not a filled-in belief"
    if not (c.get("currency") or "").strip():
        return "no CURRENCY — nothing showing the belief is actually held (the strawman risk)"
    if not (c.get("record") or "").strip():
        return "no RECORD — names no document a reader could open"
    return ""


# 16k rather than 8k: Gemini 2.5 spends thinking tokens from the same output
# budget, and a grounded search over eight themes at 8192 came close enough to
# the ceiling that a truncated final block is a live risk. A cap costs nothing
# unless it is used.
SCOUT_MAX_TOKENS = 16384


def scout_prompt():
    from shared.db import taken_beliefs

    tb = taken_beliefs()
    taken = ("BELIEFS THIS DESK HAS ALREADY TAKEN (do not re-propose these or "
             "near-duplicates):\n" + "\n".join(f"- {b}" for b in tb)) if tb else \
            "This desk has taken no beliefs yet."
    return (f"Propose candidate received beliefs for the belief desks.\n\n"
            f"STANDING THEMES:\n\n{_themes_block()}\n\n{taken}\n\n"
            f"Work several themes, not one. Search for how each belief is stated "
            f"today AND for the record that would complicate it, separately.")


def run_belief_scout(*, dry_run=False):
    """Propose candidate beliefs into the queue. Returns the number added.

    `dry_run` calls the model and parses/validates the result but writes no
    queue rows — for looking at what the scout actually proposes without
    committing the desk to it.
    """
    from engine.agents.skill_runner import run_skill
    from shared.db import add_belief_candidate, kv_set
    from datetime import datetime, timezone

    out = run_skill("ek:belief-scout", scout_prompt(),
                    max_tokens=SCOUT_MAX_TOKENS, topic="belief scout")
    raw = out or ""
    cands = parse_candidates(raw)

    def _stamp(result):
        if dry_run:
            return
        kv_set(LAST_SCOUT_KEY, datetime.now(timezone.utc).isoformat())
        kv_set(LAST_SCOUT_RESULT_KEY, result[:300])

    def _say(text):
        """Report the outcome — every outcome.

        This used to fire only `if added`, so a run that proposed nothing,
        parsed nothing, or rejected everything said nothing at all: no card, no
        row, one INFO line on Railway. That is indistinguishable from a scout
        that never ran, and on 2026-08-08 the two were in fact confused for each
        other for four days. A desk that is quiet has to say it is quiet.
        """
        if dry_run:
            return
        try:
            from engine.agents.orchestrator import _notify
            _notify(text)
        except Exception as e:
            log.warning("belief-scout notify failed: %s", e)

    if not cands:
        # Distinguish "the model said nothing" from "the model said plenty, in a
        # shape we no longer parse" — the second is a prompt/format regression
        # and should not read like a quiet week.
        if raw.strip():
            log.warning("belief-scout: 0 candidates parsed from %d chars of output — "
                        "format drift? first 200: %s", len(raw), raw.strip()[:200])
            _say(f"🧠 Belief scout: nothing usable. The model returned {len(raw)} "
                 f"characters and none of it parsed as a candidate — that reads like "
                 f"format drift rather than a quiet week, so the skill's output "
                 f"contract is worth a look.")
        else:
            log.info("belief-scout: empty response")
            _say("🧠 Belief scout: the model returned nothing at all. No candidates "
                 "this week.")
        _stamp(f"0 candidates parsed from {len(raw)} chars")
        return 0

    kept, rejected = [], []
    for c in cands:
        why = validate_candidate(c)
        (rejected if why else kept).append((c, why))
    for c, why in rejected:
        log.info("belief-scout: rejected — %s — %s", why, (c.get("belief") or "")[:70])

    if len(kept) > MAX_CANDIDATES_PER_RUN:
        log.warning("belief-scout: %d candidates, keeping the first %d",
                    len(kept), MAX_CANDIDATES_PER_RUN)
        kept = kept[:MAX_CANDIDATES_PER_RUN]

    if dry_run:
        log.info("belief-scout (dry run): %d valid, %d rejected — nothing written",
                 len(kept), len(rejected))
        return 0

    added, dupes = 0, 0
    for c, _ in kept:
        qid = add_belief_candidate(c["belief"], source="scout", theme=c["theme"],
                                   lane=c["lane"], note=c["note"])
        if qid:
            added += 1
        else:
            dupes += 1
            log.info("belief-scout: duplicate, skipped — %s", c["belief"][:70])

    _stamp(f"{added} queued, {dupes} duplicate, {len(rejected)} rejected, "
           f"{len(cands)} proposed")
    log.info("belief-scout: %d/%d candidates queued as proposals "
             "(%d duplicate, %d rejected)", added, len(cands), dupes, len(rejected))

    tally = (f"{len(cands)} proposed · {added} queued · {dupes} already known · "
             f"{len(rejected)} rejected")
    if added:
        _say(f"🧠 Belief scout: {added} new candidate(s) waiting for your nod in the "
             f"command centre.\n{tally}")
    else:
        # The silent case. Nothing was added, but the scout did run and did cost
        # money, and the reason it added nothing is the interesting part.
        _say(f"🧠 Belief scout ran and queued nothing.\n{tally}\n"
             + ("Everything it proposed was already in the queue."
                if dupes and not rejected else
                "Nothing it proposed cleared validation — worth a look at the "
                "skill if this repeats."))
    return added


def cadence_days():
    from shared.db import kv_get
    raw = (str(kv_get(CADENCE_KEY) or "")).strip()
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CADENCE_DAYS
    # NaN fails both comparisons and falls through to the default, which is the
    # answer we want for it anyway.
    if not val > 0:
        return DEFAULT_CADENCE_DAYS
    return min(max(val, MIN_CADENCE_DAYS), MAX_CADENCE_DAYS)


def cycle_due(now_utc):
    """Is a belief piece due? Cadence only — the budget and queue checks belong
    to the run itself so their reasons can be logged separately.

    Also honours the in-process quiet window, so an empty queue is asked about
    four times an hour rather than thirty.

    **Whole-day cadences count UTC dates, not elapsed seconds.** Comparing
    elapsed time against `days * 86400` loses a turn to a rounding margin, and
    on the 2-day alternating cadence it would lose every other one:

        belief run stamps   Mon 00:03:10
        Wed 00:02 tick      47h58m elapsed < 48h  ->  not due
                            the RSS cycle starts and spends past the headroom
        Wed 00:04 tick      due at last, and the budget is gone

    The desk would stand down on its own turn day, and the symptom — a quiet
    desk with a budget excuse in kv — is indistinguishable from the bug this
    whole change exists to fix. Dates put the turn boundary on the same midnight
    the news cycle keys off.

    Sub-day cadences (MIN_CADENCE_DAYS is 0.5) have no whole-date expression and
    keep the elapsed-seconds path.
    """
    from datetime import timedelta
    from shared.db import kv_get

    if _quiet_until and now_utc < _quiet_until:
        return False
    last = parse_utc(kv_get(LAST_RUN_KEY))
    if last is None:
        return True
    # A stamp in the future can only be a bad clock or a hand-edited kv value,
    # and left alone it means "never due again". An hour of tolerance covers
    # ordinary skew.
    if last - now_utc > timedelta(hours=1):
        log.warning("%s is in the future (%s) — treating the cadence as due", LAST_RUN_KEY, last)
        return True
    days = cadence_days()
    if days < 1:
        return (now_utc - last).total_seconds() >= days * 86400
    return (now_utc.date() - last.date()).days >= days


def next_turn_utc(now_utc):
    """The UTC date the desk next has a turn, or None if it has one already.

    Display only — the command centre says when the desk runs next so a quiet
    day is answerable without reading `last_belief_cycle_result`. It deliberately
    ignores the quiet window, which is a 15-minute back-off between queue checks
    and not a statement about the cadence.
    """
    from datetime import timedelta
    from shared.db import kv_get

    last = parse_utc(kv_get(LAST_RUN_KEY))
    if last is None or last - now_utc > timedelta(hours=1):
        return None
    days = cadence_days()
    if days < 1:
        nxt = last + timedelta(days=days)
        return None if nxt <= now_utc else nxt.date()
    # ceil, to agree with cycle_due: a whole-number day difference meets a
    # fractional cadence like 2.5 only once it reaches 3.
    import math
    nxt = last.date() + timedelta(days=math.ceil(days))
    return None if nxt <= now_utc.date() else nxt


def _attempts(row):
    m = re.search(r"\[attempt (\d+)\]", (row or {}).get("result") or "")
    return int(m.group(1)) if m else 0


def _requeue_or_park(row, why):
    """A run that did not finish goes back in the queue — up to a point.

    An attempt counter lives in the row's `result` because that is a column the
    command centre already shows. Without a ceiling, a belief that reliably
    crashes the pipeline re-runs and re-spends once per cadence for ever, and
    the only trace is a log line nobody reads.
    """
    from shared.db import set_belief_status

    n = _attempts(row) + 1
    if n >= MAX_ATTEMPTS:
        set_belief_status(row["id"], "dropped",
                          result=f"[attempt {n}] parked after {n} attempts — {why}. "
                                 f"Requeue here to try again.")
        log.error("belief cycle: parking queue #%s after %d attempts — %s",
                  row["id"], n, why)
        return "parked"
    set_belief_status(row["id"], "queued", result=f"[attempt {n}] {why}")
    return "requeued"


def _reclaim_stale_runs():
    """Put rows stuck in 'running' back in the queue. Returns how many.

    Safe because this is the only code that ever sets 'running', it is
    single-threaded within the tick, and it is not inside a run when it asks —
    so anything still marked running belongs to a process that no longer exists.
    Railway restarts on every deploy, so this is the normal case, not the
    exotic one, and the command centre offers no button on a `running` row.
    """
    from shared.db import list_belief_queue

    try:
        stale = list_belief_queue(status="running", limit=20)
    except Exception as e:
        log.warning("belief cycle: could not check for interrupted runs: %s", e)
        return 0
    for row in stale:
        what = _requeue_or_park(row, "interrupted (engine restart or crash)")
        log.warning("belief cycle: %s interrupted queue #%s — %s",
                    what, row["id"], (row.get("belief") or "")[:70])
    return len(stale)


def _promote_a_proposal():
    """Only when belief_auto_pursue is on. Returns the promoted row or None."""
    from shared.db import kv_get, list_belief_queue, set_belief_status
    if not _truthy(kv_get(AUTO_PURSUE_KEY)):
        return None
    props = list_belief_queue(status="proposed", limit=50)
    if not props:
        return None
    row = props[-1]  # the list comes back newest-first; take the oldest proposal
    set_belief_status(row["id"], "queued", result="auto-pursued (belief_auto_pursue)")
    log.info("belief cycle: auto-pursuing proposal #%s", row["id"])
    return row


def _nothing_to_run():
    """The honest version of 'skipped: nothing approved in the queue'.

    An empty approved queue with proposals sitting in it is a different
    situation from an empty desk: the first is waiting on Anil, the second is
    waiting on the scout, and the old message could not tell him which.
    """
    from shared.db import kv_get, list_belief_queue

    try:
        props = list_belief_queue(status="proposed", limit=60)
    except Exception:
        props = []
    if props:
        if _truthy(kv_get(AUTO_PURSUE_KEY)):
            # auto-pursue is on and there are proposals, yet nothing got promoted
            # — the promote must have lost a race or failed to write.
            return f"skipped: {len(props)} proposal(s) present but none could be promoted"
        return (f"skipped: nothing approved — {len(props)} scout proposal(s) waiting "
                f"for your nod (auto-pursue is off)")
    return "skipped: nothing approved and nothing proposed — the queue is empty"


def _record(reason, *, quiet):
    """Log-and-remember one cycle outcome.

    Writes the reason to kv only when it changes, so a desk that is quiet for a
    week costs one write rather than seven hundred.
    """
    global _quiet_until, _last_reason
    from datetime import datetime, timedelta, timezone
    from shared.db import kv_set

    _quiet_until = (datetime.now(timezone.utc) + timedelta(seconds=QUIET_RECHECK_SECONDS)
                    if quiet else None)
    if reason != _last_reason:
        _last_reason = reason
        try:
            kv_set(LAST_RESULT_KEY, reason[:300])
        except Exception as e:
            log.warning("belief cycle: could not record the reason: %s", e)
    return reason


def run_belief_cycle():
    """Take ONE approved belief to the human gate, if the day allows it.

    Returns a short string saying what happened — the tick logs it, and it is
    the honest answer to "why didn't the belief desk run today?". The same
    string goes to kv `last_belief_cycle_result`, because on Railway nobody is
    reading the return value.
    """
    from datetime import datetime, timezone
    from shared import budget
    from shared.db import kv_set, pop_next_belief, set_belief_status
    from engine.desks.ek.pipeline import run_belief

    _reclaim_stale_runs()

    # Attended work spends nothing on the APIs, so there is no cap to respect and
    # no claim for the news desk to have the prior half of. Skipping the whole
    # check (rather than passing it) also means a cost-query blip cannot park an
    # attended run the owner is driving by hand.
    if not budget.attended_mode():
        try:
            spent, cap, over = budget.status()
        except Exception as e:
            # Erring toward not spending: unlike the governor in run.py — which must
            # never let a cost-query blip halt publishing — a belief piece is never
            # urgent, and running blind is the more expensive mistake.
            log.warning("belief cycle: budget check failed (%s) — standing down", e)
            return _record("skipped: budget unreadable", quiet=True)

        if cap is not None and spent >= cap * BUDGET_HEADROOM:
            return _record(f"skipped: ${spent:.2f} of the ${cap:.2f} cap already spent — the "
                           f"news desk has the prior claim on it", quiet=True)

    row = pop_next_belief()
    if not row and _promote_a_proposal():
        row = pop_next_belief()   # claim it properly, with the same lock
    if not row:
        return _record(_nothing_to_run(), quiet=True)

    # Stamp BEFORE the work, like every other sweep in run.py: a failure halfway
    # through must not re-enter on the next 2-minute tick and spend again.
    kv_set(LAST_RUN_KEY, datetime.now(timezone.utc).isoformat())
    log.info("belief cycle: running queue #%s — %s", row["id"], row["belief"][:80])

    try:
        res = run_belief(row["belief"], note=row.get("note") or "")
    except Exception as e:
        what = _requeue_or_park(row, f"failed: {e}")
        log.error("belief cycle failed on queue #%s: %s", row["id"], e, exc_info=True)
        return _record(f"failed ({what}): {e}", quiet=False)

    verdict = res.get("verdict") or ""
    if not res.get("run_id"):
        set_belief_status(row["id"], "done",
                          result=f"{verdict or 'stopped'} at {res.get('stopped_at')}"
                                 + (f" — {res['reason']}" if res.get("reason") else ""))
        return _record(f"{verdict} (no run — {res.get('stopped_at')})", quiet=False)

    set_belief_status(row["id"], "done", run_id=res["run_id"],
                      result=f"{verdict} → {res.get('gate')} → {res.get('status')}")
    try:
        from engine.agents.orchestrator import _notify
        _notify(f"🧠 Belief desk: run #{res['run_id']} ({res.get('series', '')}) is "
                f"{res.get('status', 'parked')} — {row['belief'][:90]}")
    except Exception as e:
        log.warning("belief cycle notify failed: %s", e)
    return _record(f"run #{res['run_id']}: {verdict} → {res.get('gate')} → "
                   f"{res.get('status')}", quiet=False)


def main(argv):
    """Look at what the scout actually proposes, without committing to it.

        python -m engine.desks.ek.scout              # call the model, write nothing
        python -m engine.desks.ek.scout --commit     # queue what survives validation

    Needs the engine's env (GEMINI_API_KEY, DATABASE_URL). Pull it from Railway
    the way command_center/run.sh does — the local .env keys drift (HANDOFF §5.21).
    """
    import argparse

    ap = argparse.ArgumentParser(description="Run the belief scout and show its proposals.")
    ap.add_argument("--commit", action="store_true",
                    help="write the surviving candidates to belief_queue as proposals")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    from engine.agents.skill_runner import run_skill

    if a.commit:
        n = run_belief_scout()
        print(f"\n{n} candidate(s) queued as proposals.")
        return 0

    out = run_skill("ek:belief-scout", scout_prompt(),
                    max_tokens=SCOUT_MAX_TOKENS, topic="belief scout")

    print("\n" + "=" * 72)
    print("RAW OUTPUT")
    print("=" * 72)
    print(out)
    print("\n" + "=" * 72)
    print("PARSED + VALIDATED")
    print("=" * 72)
    cands = parse_candidates(out)
    for i, c in enumerate(cands, 1):
        why = validate_candidate(c)
        print(f"\n[{i}] {'REJECT — ' + why if why else 'OK'}")
        print(f"    belief : {c['belief']}")
        print(f"    theme  : {c['theme'] or '—'}   lane: {c['lane'] or '—'}")
        print(f"    record : {c['record'] or '—'}")
    ok = sum(1 for c in cands if not validate_candidate(c))
    print(f"\n{ok}/{len(cands)} candidates would be queued. Nothing was written.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
