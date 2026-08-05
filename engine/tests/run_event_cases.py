"""Nothing the engine says may be visible only in Telegram.

Owner's rule, 2026-08-05. The engine had 19 `_notify_card` call sites — dropped
leads, halted runs, gate decisions, steward recommendations — that wrote to no
table at all. A card that scrolled away took the information with it, and the
"Full report" link it carried points at telegra.ph, which the owner's ISP blocks.

    ./venv/bin/python -m engine.tests.run_event_cases
"""
import os
import tempfile

os.environ.pop("DATABASE_URL", None)          # force SQLite mode
_TMP = tempfile.mkdtemp(prefix="thelivu-events-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")

from shared.db import init_db, record_event, get_engine_events   # noqa: E402

PASS, FAIL = [], []


def check(label, got, want, note=""):
    (PASS if got == want else FAIL).append(label)
    print(f"  {'PASS' if got == want else 'FAIL'}  {label}")
    if got != want:
        print(f"        got {got!r}, want {want!r}")
    elif note:
        print(f"        {note}")


init_db()

print("\nan event round-trips:")
record_event("lead-dropped", "Dropped today's top lead — not our kind of story",
             body="Some throughline", report="FULL GATE REASONING", run_id=77,
             level="warn")
ev = get_engine_events(limit=10)[0]
check("the title is stored", ev["title"],
      "Dropped today's top lead — not our kind of story")
check("the reason body is stored", ev["body"], "Some throughline")
check("the full report is stored", ev["report"], "FULL GATE REASONING",
      "stored here, not only behind a telegra.ph link the owner cannot open")
check("the run is linked", ev["run_id"], 77)
check("the level is kept", ev["level"], "warn")

print("\nfiltering, so the feed is usable:")
record_event("steward", "Tech steward — 5 recommendation(s)", level="info")
record_event("run-halted", "Run #12 halted", level="error")
check("by kind", len(get_engine_events(kind="steward")), 1)
check("by level", len(get_engine_events(level="error")), 1)
check("unfiltered returns all", len(get_engine_events()), 3)
check("newest first", get_engine_events()[0]["kind"], "run-halted")

print("\nthe Telegram-outage case — the reason the write comes first:")
import engine.agents.orchestrator as orch                        # noqa: E402

sent = []


def _boom(*a, **k):
    sent.append("attempted")
    raise RuntimeError("telegram unreachable")


orch._tg_post = _boom
before = len(get_engine_events(limit=500))
try:
    orch._notify_card("🗑", "Fallback lead also dropped", body="why it went")
except Exception:
    pass
after = get_engine_events(limit=500)
check("Telegram was attempted", sent, ["attempted"])
check("and the event survived the failure", len(after) - before, 1,
      "recording after the post would have lost this entirely")
check("with its reasoning intact", after[0]["body"], "why it went")

print("\nlevel is derived from the card's emoji:")
orch._tg_post = lambda *a, **k: None
orch._notify_card("⚠️", "Intake said PROCEED but gave no brief")
check("a warning card is warn", get_engine_events(limit=1)[0]["level"], "warn")
orch._notify_card("📊", "Monthly meta-synthesis complete")
check("a neutral card is info", get_engine_events(limit=1)[0]["level"], "info")

print("\n" + "=" * 68)
if FAIL:
    print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
    raise SystemExit(1)
print(f"all {len(PASS)} engine-event cases pass")
