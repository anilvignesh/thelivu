"""Regression cases for the belief desks' cadence and their scout's intake.

    python -m engine.desks.ek.tests.run_cadence_cases

No API key, no network, no production database: it runs against a throwaway
SQLite file and stubs the pipeline, so `run_belief_cycle` is exercised end to
end without a model call. Like the caption cases and unlike the gate cases,
this is a plain assertion suite — none of it is a judgment.

What it is FOR is the class of bug that only shows up unattended: a timestamp
that won't parse, a queue that empties, a process that dies mid-run, a scout
whose output arrives truncated. Every one of those looks like "the desk is
quiet" from outside, which is why none of them were caught by running the desk
by hand.
"""
import os
import sys
import tempfile
import types

# BEFORE any shared.* import: shared.config reads DATABASE_URL at import time and
# shared.db decides postgres-vs-sqlite from it. A developer with the production
# URL exported — the normal state, since that is how you talk to Railway — would
# otherwise run this suite against the live database.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from datetime import datetime, timedelta, timezone   # noqa: E402

from engine.desks.ek import scout                     # noqa: E402
from shared import budget                             # noqa: E402
from shared.db import (add_belief_candidate, init_db, kv_get, kv_set,   # noqa: E402
                       list_belief_queue, set_belief_status)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

_fails = []
_notifications = []
_pipeline_calls = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def check_that(name, cond, detail=""):
    if not cond:
        _fails.append(f"{name}: {detail or 'false'}")
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"\n        {detail}"))


# ── stubs ─────────────────────────────────────────────────────────────────────
# run_belief_cycle imports these lazily by module path, so putting fakes in
# sys.modules keeps the whole skill_runner / anthropic / gemini stack out of the
# test. The point is to exercise the CYCLE, not the pipeline it drives.

def _install_stubs(result=None, raises=None):
    del _pipeline_calls[:]

    def run_belief(belief, note=""):
        _pipeline_calls.append((belief, note))
        if raises:
            raise raises
        return dict(result or {})

    pipeline = types.ModuleType("engine.desks.ek.pipeline")
    pipeline.run_belief = run_belief
    sys.modules["engine.desks.ek.pipeline"] = pipeline

    orch = types.ModuleType("engine.agents.orchestrator")
    orch._notify = lambda text: _notifications.append(text)
    sys.modules["engine.agents.orchestrator"] = orch


def _reset(*, cap="", spent=0.0):
    """Empty queue, clean kv, a known budget. `cap=''` disables the governor."""
    from shared.db import _conn
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM belief_queue")
        for k in (scout.LAST_RUN_KEY, scout.CADENCE_KEY, scout.AUTO_PURSUE_KEY,
                  scout.LAST_RESULT_KEY):
            cur.execute("DELETE FROM kv_store WHERE key = ?", (k,))
        conn.commit()
    finally:
        conn.close()
    scout._quiet_until = None
    scout._last_reason = None
    budget.status = lambda: (spent, None if cap == "" else float(cap),
                             cap != "" and spent >= float(cap))


# ── 1. timestamps ─────────────────────────────────────────────────────────────

def t_parse_utc():
    print("\ntimestamps — the stamp that must never silence the desk:")
    check("aware ISO", scout.parse_utc("2026-08-04T12:00:00+00:00"),
          datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))
    # THE regression. The stamp is written tz-aware, but kv is writable from
    # psql, the bot and the command centre; a naive value used to raise
    # TypeError out of cycle_due, which `except ValueError` did not catch. The
    # tick would then have logged "Belief cycle failed" every two minutes while
    # the desk never ran again — a silent, permanent stand-down.
    check("naive ISO is read as UTC, not an error",
          scout.parse_utc("2026-08-04T12:00:00"),
          datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))
    check("Z suffix", scout.parse_utc("2026-08-04T12:00:00Z"),
          datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))
    check("junk is None, not a raise", scout.parse_utc("yesterday"), None)
    check("empty is None", scout.parse_utc(""), None)
    check("None is None", scout.parse_utc(None), None)


def t_cadence_days():
    print("\ncadence_days — a kv value nobody validated:")
    _reset()
    check("unset → default (2 — the desks alternate)", scout.cadence_days(), 2)
    for raw, want in (("5", 5.0), ("0.5", 0.5), ("", 2), ("abc", 2), ("0", 2),
                      ("-2", 2), ("nan", 2),
                      # inf parses as a float and means "never due again"; 400
                      # days is the same bug with a straight face. Both clamp to
                      # the ceiling the command centre already enforces.
                      ("inf", 30), ("400", 30), ("0.01", 0.5)):
        kv_set(scout.CADENCE_KEY, raw)
        check(f"  {raw!r} → {want}", scout.cadence_days(), want)


def t_cycle_due():
    print("\ncycle_due:")
    _reset()
    check("never run → due", scout.cycle_due(NOW), True)
    kv_set(scout.LAST_RUN_KEY, (NOW - timedelta(days=1)).isoformat())
    check("1 day ago, cadence 2 → not due", scout.cycle_due(NOW), False)
    kv_set(scout.LAST_RUN_KEY, (NOW - timedelta(days=2)).isoformat())
    check("2 days ago, cadence 2 → due", scout.cycle_due(NOW), True)
    kv_set(scout.LAST_RUN_KEY, (NOW - timedelta(days=4)).replace(tzinfo=None).isoformat())
    check("4 days ago, NAIVE stamp → due (was a TypeError)", scout.cycle_due(NOW), True)
    kv_set(scout.LAST_RUN_KEY, "not a date")
    check("unparseable stamp → due", scout.cycle_due(NOW), True)
    kv_set(scout.LAST_RUN_KEY, (NOW + timedelta(days=9)).isoformat())
    check("stamp in the future → due, not never", scout.cycle_due(NOW), True)


def t_turn_boundary():
    print("\nthe turn lands on a date, not on elapsed seconds:")
    _reset()
    # The case the date arithmetic exists for. On elapsed seconds this is
    # 47h58m50s against a 48h cadence — not due — so the RSS cycle would start,
    # spend past the headroom, and the desk would stand down on its own turn
    # day. Every other turn, lost to ninety seconds.
    kv_set(scout.LAST_RUN_KEY, "2026-08-03T00:03:10+00:00")
    wed_early = datetime(2026, 8, 5, 0, 2, 0, tzinfo=timezone.utc)
    check("stamped Mon 00:03:10, asked Wed 00:02 → due", scout.cycle_due(wed_early), True)

    # ...and the boundary holds in the other direction: a turn is one per day, so
    # a stamp from earlier the same day is not a fresh turn however long ago.
    kv_set(scout.LAST_RUN_KEY, "2026-08-05T00:03:10+00:00")
    wed_late = datetime(2026, 8, 5, 23, 59, 0, tzinfo=timezone.utc)
    check("same UTC day, 23h later → not due", scout.cycle_due(wed_late), False)
    thu = datetime(2026, 8, 6, 0, 2, 0, tzinfo=timezone.utc)
    check("the next day is not the turn either (cadence 2)", scout.cycle_due(thu), False)
    fri = datetime(2026, 8, 7, 0, 2, 0, tzinfo=timezone.utc)
    check("the day after that is", scout.cycle_due(fri), True)

    # Sub-day cadences have no whole-date expression and keep elapsed seconds.
    kv_set(scout.CADENCE_KEY, "0.5")
    kv_set(scout.LAST_RUN_KEY, (NOW - timedelta(hours=11)).isoformat())
    check("cadence 0.5, 11h ago → not due", scout.cycle_due(NOW), False)
    kv_set(scout.LAST_RUN_KEY, (NOW - timedelta(hours=13)).isoformat())
    check("cadence 0.5, 13h ago → due", scout.cycle_due(NOW), True)


def t_next_turn():
    print("\nnext_turn_utc — so the dashboard can say why the desk is quiet:")
    _reset()
    check("never run → no next turn, it is now", scout.next_turn_utc(NOW), None)
    kv_set(scout.LAST_RUN_KEY, "2026-08-05T00:03:10+00:00")
    check("ran Wed, cadence 2 → next turn Friday",
          scout.next_turn_utc(datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)),
          datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc).date())
    check("asked on the turn day itself → None",
          scout.next_turn_utc(datetime(2026, 8, 7, 0, 2, tzinfo=timezone.utc)), None)
    check("asked after the turn was missed → still None, it is overdue",
          scout.next_turn_utc(datetime(2026, 8, 9, 0, 2, tzinfo=timezone.utc)), None)
    # It must agree with cycle_due rather than disagreeing prettily: a fractional
    # cadence is met only when a whole-day difference reaches it.
    kv_set(scout.CADENCE_KEY, "2.5")
    check("cadence 2.5 rounds the turn up to 3 days",
          scout.next_turn_utc(datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)),
          datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc).date())


def t_quiet_window():
    print("\nthe quiet window — an empty queue costs 3 round trips a tick, forever:")
    _install_stubs()
    _reset()
    r = scout.run_belief_cycle()
    check_that("empty queue skips", r.startswith("skipped:"), r)
    check("and then it is not due", scout.cycle_due(NOW), False)
    scout._quiet_until = NOW - timedelta(seconds=1)
    check("the window expires", scout.cycle_due(NOW), True)
    # `force_belief_run` is handled in run.py as `forced or cycle_due(...)`, so
    # Run now is never held back by the back-off. Asserting the shape of that
    # here would be asserting run.py; what this checks is that a real run clears
    # the window rather than leaving it set.
    _reset()
    _install_stubs(result={"run_id": 501, "verdict": "PURSUE-A", "gate": "READY-FOR-HUMAN",
                           "status": "pending_human", "series": "Everyone Knows"})
    add_belief_candidate("Everyone knows the Great Wall is visible from space.", source="owner")
    scout.run_belief_cycle()
    check("a real run clears the window", scout._quiet_until, None)


# ── 2. the queue ──────────────────────────────────────────────────────────────

def t_empty_queue_reasons():
    print("\nan idle desk says WHICH kind of idle it is:")
    _install_stubs()
    _reset()
    check("nothing anywhere", scout.run_belief_cycle(),
          "skipped: nothing approved and nothing proposed — the queue is empty")

    _reset()
    add_belief_candidate("Everyone knows carrots improve night vision.", source="scout")
    r = scout.run_belief_cycle()
    # The old message was "nothing approved in the queue" for both cases, which
    # is the difference between "the desk is waiting on Anil" and "the desk is
    # waiting on the scout".
    check_that("proposals waiting says so", "waiting for your nod" in r, r)
    check_that("...and names auto-pursue as the reason it did not act",
               "auto-pursue is off" in r, r)
    check("nothing was promoted", len(list_belief_queue(status="queued")), 0)


def t_auto_pursue():
    print("\nauto-pursue — off by default, and it only ever reaches the gate:")
    _reset()
    _install_stubs(result={"run_id": 77, "verdict": "ROUTE-GK", "gate": "READY-FOR-HUMAN",
                           "status": "pending_human", "series": "Turns Out"})
    add_belief_candidate("Everyone knows a goldfish has a three-second memory.", source="scout")
    kv_set(scout.AUTO_PURSUE_KEY, "1")
    r = scout.run_belief_cycle()
    check_that("promotes the oldest proposal", r.startswith("run #77"), r)
    check("the pipeline was called once", len(_pipeline_calls), 1)
    # The one thing that must never change: the cycle's last act is a run parked
    # at the human gate. There is no publish call anywhere on this path.
    check_that("it stops at pending_human", "pending_human" in r, r)


def t_failure_is_bounded():
    print("\na belief that fails goes back — up to a point:")
    _reset()
    _install_stubs(raises=RuntimeError("premise-check returned no marker"))
    qid = add_belief_candidate("Everyone knows lightning never strikes twice.", source="owner")

    for attempt in (1, 2):
        scout._quiet_until = None
        kv_set(scout.LAST_RUN_KEY, "")
        r = scout.run_belief_cycle()
        row = [b for b in list_belief_queue() if b["id"] == qid][0]
        check(f"attempt {attempt} requeues", row["status"], "queued")
        check_that(f"attempt {attempt} is counted", f"[attempt {attempt}]" in (row["result"] or ""),
                   row["result"])
        check_that(f"attempt {attempt} reports the failure", r.startswith("failed"), r)

    scout._quiet_until = None
    kv_set(scout.LAST_RUN_KEY, "")
    scout.run_belief_cycle()
    row = [b for b in list_belief_queue() if b["id"] == qid][0]
    # 'dropped' and not a new status word: the command centre lists exactly
    # proposed / queued / done / dropped / running, and offers Requeue only on
    # 'dropped'. Anything else would be a row nobody can see or act on — the
    # same status-spelling trap that hid 9 of 25 killed runs.
    check("the third attempt parks it", row["status"], "dropped")
    check_that("and says how to get it back", "Requeue" in (row["result"] or ""), row["result"])


def t_restart_reclaims():
    print("\na Railway restart mid-run leaves a row nobody can move:")
    _reset()
    _install_stubs(result={"run_id": 99, "verdict": "PURSUE-B", "gate": "READY-FOR-HUMAN",
                           "status": "pending_human", "series": "Everyone Knows"})
    qid = add_belief_candidate("Everyone knows the Guatemalan government fell on its own in 1954.",
                               source="owner")
    set_belief_status(qid, "running")   # what pop_next_belief left behind when the process died
    r = scout.run_belief_cycle()
    row = [b for b in list_belief_queue() if b["id"] == qid][0]
    check_that("it is picked back up and run", r.startswith("run #99"), r)
    check("and finishes", row["status"], "done")

    # ...but a belief that kills the engine every deploy is not retried for ever.
    _reset()
    _install_stubs()
    qid = add_belief_candidate("Everyone knows glass is a slow-moving liquid.", source="owner")
    set_belief_status(qid, "running", result="[attempt 2] interrupted (engine restart or crash)")
    scout.run_belief_cycle()
    row = [b for b in list_belief_queue() if b["id"] == qid][0]
    check("a third interruption parks it", row["status"], "dropped")


def t_budget_headroom():
    print("\nthe headroom, now that it guards the late day rather than every day:")
    _install_stubs(result={"run_id": 1, "verdict": "PURSUE-A", "gate": "READY-FOR-HUMAN",
                           "status": "pending_human", "series": "Everyone Knows"})
    _reset(cap="0.75", spent=0.50)   # 0.50 > 0.75 * 0.55
    add_belief_candidate("Everyone knows the Wall is visible from orbit.", source="owner")
    r = scout.run_belief_cycle()
    check_that("stands down over the headroom", r.startswith("skipped: $0.50"), r)
    check("nothing was claimed from the queue", len(list_belief_queue(status="queued")), 1)
    # The turn must survive its own stand-down. Stamping here would consume the
    # turn without producing a piece, and the desk would go quiet for another
    # full cadence having done nothing — which is the fortnight this change is
    # fixing, just arriving more slowly.
    check("a stand-down does not spend the turn", kv_get(scout.LAST_RUN_KEY), None)
    # The 15-minute back-off is not the cadence — clear it, or this asserts the
    # quiet window rather than the turn.
    scout._quiet_until = None
    check("so it is still due", scout.cycle_due(NOW), True)

    # On its turn the desk goes first, against a fresh cap. This is the ordering
    # half of the change (run.py) expressed as the condition it creates here.
    _reset(cap="1.00", spent=0.0)
    add_belief_candidate("Everyone knows the Wall is visible from orbit.", source="owner")
    check_that("a fresh $0.00 cap runs the piece",
               scout.run_belief_cycle().startswith("run #1"), "")
    check_that("and a completed run does stamp the turn",
               kv_get(scout.LAST_RUN_KEY) is not None, "")
    # Against the real clock, not NOW: run_belief_cycle stamps datetime.now(), so
    # a fixture date would read as a stamp from the future and short-circuit to
    # "due" — passing the check for the wrong reason.
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    check("so the desk is not due again tomorrow", scout.cycle_due(tomorrow), False)
    check("but it is the day after", scout.cycle_due(tomorrow + timedelta(days=1)), True)

    _reset(cap="0.75", spent=0.10)
    add_belief_candidate("Everyone knows the Wall is visible from orbit.", source="owner")
    check_that("runs under the headroom", scout.run_belief_cycle().startswith("run #1"), "")

    # A cost query that fails must not turn into a spend. The governor in run.py
    # assumes-under on a blip because publishing must not stop; here the safe
    # direction is the opposite one.
    _reset(cap="0.75", spent=0.10)
    add_belief_candidate("Everyone knows the Wall is visible from orbit.", source="owner")
    def _boom():
        raise RuntimeError("connection reset")
    budget.status = _boom
    check("an unreadable budget stands the desk down",
          scout.run_belief_cycle(), "skipped: budget unreadable")


# ── 3. the scout's output ─────────────────────────────────────────────────────

GOOD = """CANDIDATE: "Banana republic" means a chaotic, badly-run poor country.
THEME: phrases-and-origins
CURRENCY: Used as a stock insult in Indian and British opinion columns this year.
RECORD: O. Henry, Cabbages and Kings (1904); United Fruit Company records.
SO_WHAT: The phrase names foreign corporate capture, not native incompetence.
LANE: ek (Everyone Knows)

CANDIDATE: Everyone knows a goldfish has a three-second memory.
THEME: off-list
CURRENCY: Repeated in aquarium marketing copy and school textbooks.
RECORD: Brown et al., Fish Cognition and Behavior (2011).
SO_WHAT: Little — this is a curiosity.
LANE: gk

Those are the strongest of the eight themes this week.
"""

TRUNCATED = """CANDIDATE: Everyone knows the Green Revolution ended famine in India.
THEME: development-orthodoxy
CURRENCY: The standard line in NCERT textbooks and anniversary coverage.
RECORD: Bhalla & Singh, district-level productivity data 1962-2005.
SO_WHAT: It relocates the question from output to distribution.
LANE: ek

CANDIDATE: Everyone knows the East India Company was a trading firm.
THEME: western-framing
CUR"""


def t_parse():
    print("\nparse_candidates:")
    cs = scout.parse_candidates(GOOD)
    check("two candidates", len(cs), 2)
    # "LANE: ek (Everyone Knows)" is the same answer as "LANE: ek". It used to
    # match neither and be stored as no lane at all.
    check("a lane with a gloss still reads as a lane", cs[0]["lane"], "ek")
    check("the plain lane", cs[1]["lane"], "gk")
    check("trailing commentary is ignored", cs[1]["theme"], "off-list")
    check_that("the record is kept as a field, not only inside the note",
               cs[0]["record"].startswith("O. Henry"), cs[0]["record"])
    check_that("the note still carries all three", "so what:" in cs[0]["note"], cs[0]["note"])
    check("no CANDIDATE line → nothing", scout.parse_candidates("THEME: x\nLANE: ek"), [])
    check("empty input → nothing", scout.parse_candidates(""), [])
    check("None → nothing", scout.parse_candidates(None), [])


def t_validate():
    print("\nvalidate_candidate — the two conditions the skill calls mandatory:")
    good, half = scout.parse_candidates(GOOD)[0], scout.parse_candidates(TRUNCATED)
    check("a complete candidate passes", scout.validate_candidate(good), "")
    check("the truncated response yields two blocks", len(half), 2)
    check("its complete block passes", scout.validate_candidate(half[0]), "")
    # Gemini spends thinking tokens from the output budget, so a squeezed
    # response loses its trailing fields first — which means the block that
    # survives truncation is exactly the one with no currency and no record.
    # That block is a hunch, and a hunch costs a research pass.
    check_that("its cut-off block is rejected", scout.validate_candidate(half[1]) != "",
               "a candidate with no CURRENCY and no RECORD was accepted")

    base = dict(belief="Everyone knows X is true and has been for a long time.",
                currency="c", record="r")
    check("a template echo is rejected",
          scout.validate_candidate(dict(base, belief="<the belief, in their words>")),
          "looks like the output template, not a filled-in belief")
    check_that("too short is rejected", scout.validate_candidate(dict(base, belief="hi")) != "", "")
    check_that("a paragraph is rejected",
               scout.validate_candidate(dict(base, belief="x" * 401)) != "", "")
    check_that("no record is rejected",
               "no RECORD" in scout.validate_candidate(dict(base, record="")), "")
    check_that("no currency is rejected",
               "no CURRENCY" in scout.validate_candidate(dict(base, currency="")), "")


def main():
    init_db()
    for t in (t_parse_utc, t_cadence_days, t_cycle_due, t_turn_boundary,
              t_next_turn, t_quiet_window,
              t_empty_queue_reasons, t_auto_pursue, t_failure_is_bounded,
              t_restart_reclaims, t_budget_headroom, t_parse, t_validate):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all cadence + scout cases pass")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        os.unlink(_TMPDB.name)
