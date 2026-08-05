"""Cached tokens are real money, and they were being counted as zero.

`response.usage.input_tokens` is the UNCACHED REMAINDER, not the prompt size —
the real prompt is input + cache_creation + cache_read. skill_runner recorded
only the first, so every cached call under-reported: a cache WRITE bills at
1.25x the input rate and contributed nothing to the total the budget governor
reads. These cases pin the arithmetic and the back-compatibility.

    ./venv/bin/python -m engine.tests.run_cost_cases
"""
import os
import tempfile

os.environ.pop("DATABASE_URL", None)          # force SQLite mode
_TMP = tempfile.mkdtemp(prefix="thelivu-cost-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")

from shared.costs import (cost_usd, RATES, tier_for,          # noqa: E402
                          CACHE_WRITE_MULT, CACHE_READ_MULT)
from shared.db import init_db, record_usage                    # noqa: E402
from shared.costs import daily_spend_usd                       # noqa: E402

PASS, FAIL = [], []


def check(label, got, want, note=""):
    ok = (abs(got - want) < 1e-9) if isinstance(want, float) else (got == want)
    (PASS if ok else FAIL).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got {got!r}, want {want!r}")
    elif note:
        print(f"        {note}")


SONNET = "claude-sonnet-4-6"
rate_in, rate_out = RATES[tier_for(SONNET)]

print("\nthe old two-argument call still means what it did:")
check("input+output unchanged",
      cost_usd(SONNET, 1_000_000, 0), rate_in,
      "nine existing call sites pass three positional args — they must not shift")
check("cache args default to zero", cost_usd(SONNET, 1_000_000, 0),
      cost_usd(SONNET, 1_000_000, 0, 0, 0))

print("\ncache tokens are priced off the INPUT rate:")
check("a write costs 1.25x", cost_usd(SONNET, 0, 0, 1_000_000, 0),
      rate_in * CACHE_WRITE_MULT,
      "more than a fresh read of the same tokens — this is what was free before")
check("a read costs 0.10x", cost_usd(SONNET, 0, 0, 0, 1_000_000),
      rate_in * CACHE_READ_MULT)
check("a read is cheaper than paying full price",
      cost_usd(SONNET, 0, 0, 0, 1_000_000) < cost_usd(SONNET, 1_000_000, 0), True,
      "if this ever inverts, caching is costing money rather than saving it")

print("\nthe under-report this fixes:")
old = cost_usd(SONNET, 5_000, 1_000)
new = cost_usd(SONNET, 5_000, 1_000, 120_000, 0)
check("a big cache write is no longer free", new > old, True,
      f"${old:.4f} recorded before vs ${new:.4f} actually billed")

print("\nfree tiers stay free:")
for m in ("google/gemma-4-31b-it", "nvidia/flux", "attended"):
    check(f"{m} costs nothing", cost_usd(m, 9_9, 9_9, 9_9, 9_9), 0.0)

print("\ndaily_spend_usd counts the cached span:")
init_db()
record_usage(skill="t", model=SONNET, input_tokens=1000, output_tokens=100)
before = daily_spend_usd()
record_usage(skill="t", model=SONNET, input_tokens=0, output_tokens=0,
             cache_write_tokens=200_000, cache_read_tokens=200_000)
after = daily_spend_usd()
check("a cache-only call moves the daily total", after > before, True,
      f"${before:.4f} -> ${after:.4f}; the budget governor reads this number")
check("and by the right amount", after - before,
      cost_usd(SONNET, 0, 0, 200_000, 200_000))

print("\nold rows (NULL cache columns) still price correctly:")
from shared.db import _conn                                    # noqa: E402
c = _conn()
cur = c.cursor()
cur.execute("INSERT INTO token_usage (skill, model, input_tokens, output_tokens, "
            "cache_write_tokens, cache_read_tokens) VALUES ('legacy', ?, 1000, 100, NULL, NULL)",
            (SONNET,))
c.commit()
c.close()
check("a NULL cache column reads as zero, not a crash",
      daily_spend_usd() - after, cost_usd(SONNET, 1000, 100),
      "COALESCE in the SQL — every row written before 2026-08-05 is NULL here")

print("\n" + "=" * 68)
if FAIL:
    print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
    raise SystemExit(1)
print(f"all {len(PASS)} cost cases pass")
