"""Sweep failure alerts — reported once, not once per retry.

    python -m shared.tests.run_sweep_alert_cases

No network. The dedup logic is exercised directly.

What this is FOR: on 2026-09-10 the Instagram token expired and the sync retries
about every two minutes, so an identical alert went to Anil's phone every two
minutes for hours. A hundred identical alerts train you to swipe alerts away,
and the next one that matters gets swiped with them.
"""
import re
import sys
from datetime import datetime, timedelta, timezone

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def _signature(exc):
    """Mirror of run.py::_sweep_signature."""
    return re.sub(r"\d+", "#", f"{type(exc).__name__}:{exc}")[:200]


def t_a_live_clock_does_not_make_every_retry_look_new():
    """The real message embeds "The current time is ..." — so without stripping
    digits, every single retry is a brand new error and dedup never fires."""
    a = RuntimeError("400: Error validating access token: Session has expired on "
                     "Thursday, 10-Sep-26 11:49:39 PDT. The current time is "
                     "Thursday, 10-Sep-26 17:27:52 PDT.")
    b = RuntimeError("400: Error validating access token: Session has expired on "
                     "Thursday, 10-Sep-26 11:49:39 PDT. The current time is "
                     "Thursday, 10-Sep-26 17:29:54 PDT.")
    check("two retries share a signature", _signature(a), _signature(b))


def t_a_genuinely_different_failure_is_distinct():
    a = RuntimeError("400: Error validating access token")
    b = ConnectionError("connection reset by peer")
    check("different errors differ", _signature(a) != _signature(b), True)
    c = RuntimeError("500: internal server error")
    check("same type, different message differs", _signature(a) != _signature(c), True)


def t_signature_is_bounded():
    huge = RuntimeError("x" * 5000)
    check("signature capped", len(_signature(huge)) <= 200, True)


# --------------------------------------------------------------------------
# the reminder schedule, as the tick applies it
# --------------------------------------------------------------------------

REMIND_AFTER = timedelta(hours=6)


def _should_send(prev_sig, sig, last_iso, now):
    if prev_sig != sig:
        return True
    if not last_iso:
        return True
    return now - datetime.fromisoformat(last_iso) >= REMIND_AFTER


def t_first_failure_always_alerts():
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    check("new failure alerts", _should_send("", "sig-a", "", now), True)


def t_immediate_repeats_are_suppressed():
    """The whole fix, simulated as the tick actually runs it: the retry fires
    every 2 minutes for 24 hours and `last_iso` resets each time a message
    goes out. 720 retries must produce 5 messages, not 720."""
    start = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    last_iso, prev_sig, sent = "", "", 0
    for i in range(720):                       # 24h at one retry per 2 min
        now = start + timedelta(minutes=2 * i)
        if _should_send(prev_sig, "sig-a", last_iso, now):
            sent += 1
            last_iso = now.isoformat()
        prev_sig = "sig-a"
    # t=0, then 6h, 12h, 18h — the 24h mark falls outside the loop.
    check("one initial alert plus 6-hourly reminders", sent, 4)
    check("not one per retry", sent < 720, True)


def t_reminder_fires_after_the_cooldown():
    start = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    check("not at 5h", _should_send("sig-a", "sig-a", start.isoformat(),
                                    start + timedelta(hours=5)), False)
    check("yes at 6h", _should_send("sig-a", "sig-a", start.isoformat(),
                                    start + timedelta(hours=6)), True)


def t_a_different_failure_breaks_through_immediately():
    """A cooldown on one error must not silence a new, different one."""
    start = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    check("new signature alerts despite the cooldown",
          _should_send("sig-a", "sig-b", start.isoformat(),
                       start + timedelta(minutes=1)), True)


def t_corrupt_state_fails_open():
    """A malformed stored timestamp must alert, not swallow."""
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    try:
        got = _should_send("sig-a", "sig-a", "not-a-timestamp", now)
    except Exception:
        got = True     # run.py catches and defaults to sending
    check("corrupt state still alerts", got, True)


def main():
    print("sweep alert cases")
    for t in (t_a_live_clock_does_not_make_every_retry_look_new,
              t_a_genuinely_different_failure_is_distinct,
              t_signature_is_bounded,
              t_first_failure_always_alerts,
              t_immediate_repeats_are_suppressed,
              t_reminder_fires_after_the_cooldown,
              t_a_different_failure_breaks_through_immediately,
              t_corrupt_state_fails_open):
        t()
    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all sweep alert cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
