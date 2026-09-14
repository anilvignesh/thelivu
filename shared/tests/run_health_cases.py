"""Does the health layer distinguish quiet from broken?

    python -m shared.tests.run_health_cases

Anil, 2026-09-14: "Let's get this into a proper commercial grade system." The
definition came from that day's six failures, every one of which was found by
somebody asking a question and none of which raised an error.

The single distinction everything here rests on: **"nothing to report" and "not
working" are indistinguishable in any one cycle.** A check that cannot say
BROKEN for a component succeeding at nothing is not a health check.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from shared import health                            # noqa: E402

_fails = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        _fails.append(f"{label}: got {got!r}, want {want!r}")


def t_a_component_succeeding_at_nothing_is_broken_not_quiet():
    """cag-reports fetched a document every hour for weeks and found nothing,
    and every individual cycle logged "0 candidate(s)" — which is also what a
    healthy target looks like on a quiet day."""
    from shared import db

    real = db.barren_targets
    db.barren_targets = lambda **k: [("cag-reports", 13, 13), ("dead-index", 9, 0)]
    try:
        got = {c.name: c for c in health.check_digger_targets()}
    finally:
        db.barren_targets = real

    check("a target reading the wrong pages is BROKEN",
          got["digger/cag-reports"].status, health.BROKEN)
    check("and the detail says it fetched but found nothing",
          "nothing found" in got["digger/cag-reports"].detail, True)
    # The two failures need different repairs, so they must not read the same.
    check("a target that cannot fetch at all reads differently",
          "fetched nothing at all" in got["digger/dead-index"].detail, True)
    check("every broken check carries a remedy",
          all(c.fix for c in got.values()), True)


def t_quiet_is_a_legitimate_answer():
    """Sources publish in bursts. A digest that shouts on a slow Sunday gets
    muted, and then it is worth nothing on the day it matters."""
    from shared import db

    real = db.candidates_since
    db.candidates_since = lambda days=2: 0 if days <= 2 else 5
    try:
        got = health.check_digger_output()[0]
    finally:
        db.candidates_since = real
    check("a couple of quiet days is QUIET, not broken", got.status, health.QUIET)

    db.candidates_since = lambda days=2: 0
    try:
        got = health.check_digger_output()[0]
    finally:
        db.candidates_since = real
    check("a whole week of nothing is BROKEN", got.status, health.BROKEN)


def t_cannot_check_is_never_ok_and_never_broken():
    """The mistake this module exists to prevent, made by this module on its
    first run: freellmapi is bound to localhost on the digger VM, so probing it
    from the laptop reports a missing credential. That is a fact about the
    laptop. Reporting it as BROKEN is how a digest teaches its reader to skim.
    """
    had = os.environ.pop("FREELLMAPI_KEY", None)
    try:
        got = health.check_digger_models()[0]
    finally:
        if had is not None:
            os.environ["FREELLMAPI_KEY"] = had
    check("an unreachable probe is UNKNOWN", got.status, health.UNKNOWN)
    check("and it is not OK either", got.status == health.OK, False)
    check("it says where to run it instead", "digger host" in got.fix, True)


def t_a_check_that_throws_does_not_silence_the_digest():
    """A health system that goes quiet because one probe raised has exactly the
    failure it was built to catch."""
    def boom():
        raise RuntimeError("the probe itself is broken")

    got = health._safe(boom, "explodes")
    check("it becomes a check, not an exception", len(got), 1)
    check("reported as unknown", got[0].status, health.UNKNOWN)
    check("and names itself as the thing that failed",
          "check itself failed" in got[0].detail, True)


def t_the_digest_answers_the_question_on_its_first_line():
    """A report that must be read in full to be understood stops being read."""
    checks = [health.Check("archive", health.OK, "fine"),
              health.Check("digger/x", health.BROKEN, "nothing found", "fix the pattern"),
              health.Check("reels", health.QUIET, "queue empty")]
    text, worst = health.digest(checks=checks)
    first = text.splitlines()[0]
    check("the headline counts what needs attention", "1 of 3" in first, True)
    check("worst status is reported", worst, health.BROKEN)
    check("the broken line sorts first",
          text.splitlines()[2].strip().startswith("BROKEN"), True)
    check("the remedy is printed under it", "fix the pattern" in text, True)

    clear, worst2 = health.digest(checks=[health.Check("a", health.OK, "fine")])
    check("all-clear says so plainly", clear.splitlines()[0].startswith("ALL CLEAR"), True)
    check("and reports ok", worst2, health.OK)


def main():
    print("health layer\n")
    for t in (t_a_component_succeeding_at_nothing_is_broken_not_quiet,
              t_quiet_is_a_legitimate_answer,
              t_cannot_check_is_never_ok_and_never_broken,
              t_a_check_that_throws_does_not_silence_the_digest,
              t_the_digest_answers_the_question_on_its_first_line):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all health cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
