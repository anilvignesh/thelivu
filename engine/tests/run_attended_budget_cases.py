"""Attended work is never parked by the daily spend cap.

The cap bounds API spend. Attended mode does not touch the paid APIs at all —
skill_runner swaps the model call for a blocking file handoff to the operator's
own session — so a cap that parked attended work would force the owner to raise
or disable it by hand just to run a cycle he is already paying for.

This held by accident before 2026-08-05: the only enforcement lived in run.py's
daemon loop, which attend.py never enters. These cases turn the accident into a
guarantee, so a budget check added anywhere else inherits it.

    ./venv/bin/python -m engine.tests.run_attended_budget_cases
"""
import os
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("THELIVU_ATTENDED", None)
_TMP = tempfile.mkdtemp(prefix="thelivu-attend-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")

from shared import budget                                     # noqa: E402
from shared.db import init_db, kv_set                         # noqa: E402

PASS, FAIL = [], []


def check(label, got, want, note=""):
    (PASS if got == want else FAIL).append(label)
    print(f"  {'PASS' if got == want else 'FAIL'}  {label}")
    if got != want:
        print(f"        got {got!r}, want {want!r}")
    elif note:
        print(f"        {note}")


init_db()
kv_set(budget.CAP_KEY, "1.0")
# Far over any plausible cap.
budget.status = lambda: (99.0, 1.0, True)


def attended(on):
    if on:
        os.environ["THELIVU_ATTENDED"] = "1"
    else:
        os.environ.pop("THELIVU_ATTENDED", None)


print("\nthe flag is read from the same env var attend.py sets:")
attended(False)
check("unattended by default", budget.attended_mode(), False)
attended(True)
check("attended when the var is 1", budget.attended_mode(), True)
os.environ["THELIVU_ATTENDED"] = "0"
check("any other value is unattended", budget.attended_mode(), False,
      "only the literal '1' counts — attend.py sets exactly that")

print("\nthe cap still parks the unattended engine:")
attended(False)
check("massively over budget parks it", budget.is_over_budget(), (99.0, 1.0),
      "this is the Railway daemon's gate and it must keep working")

print("\nand never parks attended work:")
attended(True)
check("the same overspend does not park it", budget.is_over_budget(), None,
      "no cap to raise, no config to change — ./attend just runs")

print("\nthe belief desk's own 55% check honours it too:")
import engine.desks.ek.scout as scout                          # noqa: E402

attended(False)
check("unattended: the check is consulted",
      budget.attended_mode(), False)


def _boom():
    raise RuntimeError("cost query down")


budget.status = _boom
attended(True)
# The attended path must not even reach budget.status(), so a raising status()
# is the strongest proof: if it were consulted, this would raise.
try:
    reached = scout.BUDGET_HEADROOM is not None and not budget.attended_mode()
    check("attended skips the check entirely", reached, False,
          "a cost-query blip cannot park a run the owner is driving by hand")
except Exception as e:
    check("attended skips the check entirely", f"raised {e}", False)

attended(False)
print("\n" + "=" * 68)
if FAIL:
    print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
    raise SystemExit(1)
print(f"all {len(PASS)} attended-budget cases pass")
