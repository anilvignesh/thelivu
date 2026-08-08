"""The budget governor's reserve — refusing a cycle before it starts.

    python -m shared.tests.run_budget_cases

No API key, no network, no production database: a throwaway SQLite file, so the
kv reads are real but nothing else is.

What it is FOR is the arithmetic that decides whether a day spends $0.65 or
$1.32. The governor used to be checked once per tick and then a whole cycle ran
underneath it unwatched, so against a $1.00 cap 2026-08 produced $1.32, $1.28
and $1.16 days. The reserve moves the refusal earlier rather than making the
check sharper — a mid-spine abort is the failure shared/budget.py exists to
prevent, not a fix for it. See docs/the-silent-scout-and-the-soft-cap.md §4.
"""
import os
import sys
import tempfile

# BEFORE any shared.* import — same reasoning as the cadence suite: shared.config
# reads DATABASE_URL at import time, and a developer with the production URL
# exported is the normal state, since that is how you talk to Railway.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from shared import budget                       # noqa: E402
from shared.db import init_db, kv_set           # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def _set(cap, reserve):
    kv_set(budget.CAP_KEY, cap)
    kv_set(budget.RESERVE_KEY, reserve)


def t_reserve_parsing():
    print("\nreserve_usd — a kv value nobody validated:")
    kv_set(budget.CAP_KEY, "10")     # high, so the cap/2 clamp is not in play
    for raw, want in (("0.35", 0.35), ("0.5", 0.5), ("1", 1.0),
                      # '' and '0' both mean "no reserve" — the old post-hoc
                      # behaviour, kept reachable on purpose.
                      ("", 0.0), ("0", 0.0), ("-1", 0.0),
                      # Junk falls back rather than disabling the reserve: a
                      # typo must not silently restore the overrun. 'nan' is the
                      # dangerous one — it parses, and then every comparison
                      # against it is False, so the governor would never park.
                      ("abc", 0.35), ("nan", 0.35), ("inf", 0.35)):
        kv_set(budget.RESERVE_KEY, raw)
        check(f"  {raw!r} → {want}", budget.reserve_usd(), want)


def t_reserve_clamp():
    print("\na reserve at or above the cap is an off switch, not a budget:")
    _set("1.00", "5.00")
    check("clamped to half the cap", budget.reserve_usd(), 0.5)
    _set("1.00", "0.60")
    check("0.60 of a 1.00 cap clamps to 0.50", budget.reserve_usd(), 0.5)
    _set("1.00", "0.35")
    check("a sane reserve is left alone", budget.reserve_usd(), 0.35)
    kv_set(budget.CAP_KEY, "")       # governor disabled
    check("no cap → nothing to clamp against", budget.reserve_usd(), 0.35)


def t_over_budget():
    print("\nthe governor parks before a cycle, not after one:")
    _set("1.00", "0.35")
    import shared.costs as costs
    for spent, want in ((0.0, False), (0.40, False), (0.60, False),
                        # 0.65 + 0.35 == 1.00: the day can no longer afford a
                        # typical cycle, which is the whole point.
                        (0.65, True), (0.70, True), (1.20, True)):
        # daily_spend_usd hits the DB; substitute the measured figure directly.
        costs.daily_spend_usd = lambda s=spent: s
        check(f"  ${spent:.2f} spent of $1.00, reserve $0.35 → parked={want}",
              budget.status()[2], want)


def t_reserve_zero_is_the_old_behaviour():
    print("\nreserve 0 restores the pre-2026-08-08 check exactly:")
    _set("1.00", "0")
    import shared.costs as costs
    for spent, want in ((0.99, False), (1.00, True), (1.50, True)):
        costs.daily_spend_usd = lambda s=spent: s
        check(f"  ${spent:.2f} of $1.00 → over={want}", budget.status()[2], want)


def t_no_cap_and_attended():
    print("\nthe two ways the governor stands aside:")
    import shared.costs as costs
    costs.daily_spend_usd = lambda: 99.0
    _set("", "0.35")
    check("a disabled cap is uncapped however big the reserve",
          budget.status()[2], False)
    check("...and is_over_budget agrees", budget.is_over_budget(), None)

    _set("1.00", "0.35")
    check("a real cap parks it", budget.is_over_budget() is not None, True)
    os.environ["THELIVU_ATTENDED"] = "1"
    check("attended mode spends nothing, so nothing to bound",
          budget.is_over_budget(), None)
    os.environ.pop("THELIVU_ATTENDED")


def t_belief_headroom_is_independent():
    print("\nthe belief desk's 55% headroom is not the governor's reserve:")
    # alternating-desks.md §3.3 — the desk reads spent/cap off status() and does
    # its own comparison. If the reserve ever leaked into that number the desk
    # would stand down twice as early, for a reason nothing logs.
    import shared.costs as costs
    _set("1.00", "0.35")
    costs.daily_spend_usd = lambda: 0.50
    spent, cap, over = budget.status()
    check("status still reports the true spend", spent, 0.50)
    check("and the true cap", cap, 1.00)
    check("the desk's own test is unaffected",
          spent >= cap * 0.55, False)


def main():
    init_db()
    for t in (t_reserve_parsing, t_reserve_clamp, t_over_budget,
              t_reserve_zero_is_the_old_behaviour, t_no_cap_and_attended,
              t_belief_headroom_is_independent):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all budget cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
