"""A submitted topic's fate must survive the session it was decided in.

The bug these cases exist to prevent: every terminal path in _run_topic_intake
called finish_topic(topic_id) and put its reasoning in a Telegram card, so
pending_topics ended up 46 rows all reading 'done'. A published topic and one
binned in five seconds were indistinguishable in the DB, and the reasoning was
unrecoverable once the card scrolled away — worse, its "Full report" link is on
telegra.ph, which the owner's ISP blocks.

    ./venv/bin/python -m engine.tests.run_topic_outcome_cases
"""
import os
import tempfile

os.environ.pop("DATABASE_URL", None)          # force SQLite mode
_TMP = tempfile.mkdtemp(prefix="thelivu-topic-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")

from shared.db import (init_db, queue_topic, pop_next_topic,     # noqa: E402
                       finish_topic, get_topic_outcomes, TOPIC_OUTCOMES)
from engine.agents.orchestrator import _intake_reason            # noqa: E402

PASS, FAIL = [], []


def check(label, got, want, note=""):
    (PASS if got == want else FAIL).append(label)
    flag = "PASS" if got == want else "FAIL"
    print(f"  {flag}  {label}")
    if flag == "FAIL":
        print(f"        got {got!r}, want {want!r}")
    elif note:
        print(f"        {note}")


def _fresh(topic):
    queue_topic(topic, "test")
    return pop_next_topic()["id"]


init_db()

print("\nfinish_topic refuses to lose the outcome:")

try:
    finish_topic(_fresh("a"), None)
    check("a missing outcome is refused", "accepted", "raised")
except (ValueError, TypeError):
    check("a missing outcome is refused", "raised", "raised",
          "the parameter has no default — a seventh exit cannot quietly skip it")

try:
    finish_topic(_fresh("b"), "done")
    check("an unknown outcome is refused", "accepted", "raised")
except ValueError:
    check("an unknown outcome is refused", "raised", "raised",
          "'done' was the old catch-all; it is not a fate")

print("\nevery fate round-trips:")

for outcome in sorted(TOPIC_OUTCOMES):
    tid = _fresh(f"topic for {outcome}")
    finish_topic(tid, outcome, reason=f"because {outcome}", report="FULL REPORT BODY")
    row = next(r for r in get_topic_outcomes(200) if r["id"] == tid)
    check(f"{outcome} is stored", row["outcome"], outcome)

tid = _fresh("one with a run")
finish_topic(tid, "investigating", reason="the angle", report="R", run_id=4242)
row = next(r for r in get_topic_outcomes(200) if r["id"] == tid)
check("the resulting run id is kept", row["run_id"], 4242,
      "this is the link from a topic to the story it became")
check("the reason is kept", row["reason"], "the angle")
check("the full report is kept", row["report"], "R",
      "stored here, not only behind a telegra.ph link the owner cannot open")
check("status still reads done", row["status"], "done",
      "outcome is additive — nothing that reads status breaks")

print("\n_intake_reason pulls the decision, not the brief:")

REAL = """# Topic Intake — CAG report on unaccounted spending

## Front-gate triage
- In scope: yes — national public-finance accountability, a primary CAG record
- Worth it (impact x under-coverage): no — the figure is already in every major
  national outlet this week
- Decision: DECLINE

## Scoped lead for investigation
Pull the CAG paragraph itself rather than the wire copy.
"""
got = _intake_reason(REAL)
check("both triage lines are captured", "In scope: yes" in "In scope: " + got, True)
check("the worth-it reason is captured", "already in every major" in got, True,
      "this is the sentence that explains a decline")
check("the brief is not swallowed", "Scoped lead" not in got, True)

check("a drifted reply still records something",
      _intake_reason("## Heading\n\nThe model rambled instead.") != "",
      True, "an empty reason would re-create the original bug")
check("an empty reply says so", _intake_reason(""), "no reason given")

print("\n" + "=" * 68)
if FAIL:
    print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
    raise SystemExit(1)
print(f"all {len(PASS)} topic-outcome cases pass")
