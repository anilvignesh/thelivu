"""When the reel worker should stop trying — and when it must not.

    python -m shared.tests.run_reel_retry_cases

No network and no model: `_build_one` is driven with stubbed results, so what
this exercises is the retry POLICY, which is the part that was wrong.

Found 2026-09-11 in production: run #237 had failed the fact check **128
consecutive times**, once every ten minutes, each attempt a paid Haiku call. The
complaint's wording drifted between attempts; its substance never did — the
model kept inventing the same two figures from the same article. The single
stuck-alert had fired at attempt 3 and then, by the old policy, never again, so
from the outside it looked exactly like a run that was quietly working.

The distinction the policy was missing already existed in the data:
make_narrated_reel marks the TRANSIENT kind with `retry: True` (a fact check
that could not run, a voice server that is down). Everything else fails the same
way next time, because the input has not changed.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from publishing import reel_worker                  # noqa: E402
from shared.db import init_db, kv_get, kv_set       # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(("  ok   " if ok else "  FAIL ") + name)


CONTENT = {"ok": False, "error": "the reel uses figures absent from the article: 1.94"}
TRANSIENT = {"ok": False, "retry": True, "error": "the fact check could not run"}
GOOD = {"ok": True, "reel_id": 1, "kind": "narrated", "beats": 5, "size_kb": 900}


def _drive(run_id, results):
    """Run _build_one once per result, with the model and Telegram stubbed."""
    import publishing.make_reel as mr

    pushed = []
    seq = list(results)
    real_make = getattr(mr, "make_narrated_reel", None)
    real_push = reel_worker._tg_post_text
    real_mood = reel_worker._carousel_mood
    mr.make_narrated_reel = lambda *a, **k: seq.pop(0)
    reel_worker._tg_post_text = lambda text: pushed.append(text)
    reel_worker._carousel_mood = lambda rid: (None, None)
    try:
        for _ in results:
            reel_worker._build_one(run_id, f"slug-{run_id}")
    finally:
        if real_make:
            mr.make_narrated_reel = real_make
        reel_worker._tg_post_text = real_push
        reel_worker._carousel_mood = real_mood
    return pushed


def _reset(run_id):
    for k in ("reel_build_fails_", "reel_build_alerted_",
              "reel_content_fails_", "reel_build_parked_"):
        kv_set(f"{k}{run_id}", "")


def t_a_content_failure_is_parked_not_retried_forever():
    _reset(101)
    n = reel_worker._CONTENT_FAILURES_BEFORE_PARK
    pushed = _drive(101, [CONTENT] * n)
    check("parked at the threshold", reel_worker._parked(101), True)
    check("and Anil was told once",
          sum(1 for p in pushed if "parked" in p), 1)


def t_it_is_not_parked_one_attempt_early():
    _reset(102)
    _drive(102, [CONTENT] * (reel_worker._CONTENT_FAILURES_BEFORE_PARK - 1))
    check("still trying below the threshold", reel_worker._parked(102), False)


def t_a_transient_failure_is_never_parked():
    """The free NVIDIA tier and the voice server both recover on their own.
    Parking those would turn a five-minute outage into a story that silently
    never gets a reel."""
    _reset(103)
    _drive(103, [TRANSIENT] * (reel_worker._CONTENT_FAILURES_BEFORE_PARK * 3))
    check("transient failures never park", reel_worker._parked(103), False)


def t_a_transient_failure_clears_the_content_streak():
    """A content streak broken by an outage is not a content streak. Otherwise
    a run that failed the fact check twice, hit a voice outage for a week, then
    failed twice more would park on the strength of four attempts spread across
    two unrelated causes."""
    _reset(104)
    _drive(104, [CONTENT, CONTENT, TRANSIENT])
    check("the content streak was cleared",
          (kv_get("reel_content_fails_104") or ""), "")
    _drive(104, [CONTENT] * (reel_worker._CONTENT_FAILURES_BEFORE_PARK - 1))
    check("and counting restarted from zero", reel_worker._parked(104), False)


def t_a_success_clears_everything():
    _reset(105)
    _drive(105, [CONTENT, CONTENT, GOOD])
    check("content streak cleared", (kv_get("reel_content_fails_105") or ""), "")
    check("failure streak cleared", (kv_get("reel_build_fails_105") or ""), "")
    check("not parked", reel_worker._parked(105), False)


def t_a_parked_run_is_not_picked_up_again():
    """The point of the whole thing: the pass must stop choosing it."""
    _reset(106)
    kv_set("reel_build_parked_106", "1")
    real = reel_worker._find_candidates
    reel_worker._find_candidates = lambda: [{"id": 106, "slug": "s"},
                                            {"id": 107, "slug": "t"}]
    picked = []
    real_build = reel_worker._build_one
    reel_worker._build_one = lambda rid, slug: picked.append(rid)
    real_remake = reel_worker._find_remake_candidates
    reel_worker._find_remake_candidates = lambda: []
    real_lf = None
    try:
        import publishing.longform_build as lb
        real_lf = lb.render_pending
        lb.render_pending = lambda *a, **k: []
    except Exception:
        pass
    try:
        reel_worker.run_once()
    finally:
        reel_worker._find_candidates = real
        reel_worker._build_one = real_build
        reel_worker._find_remake_candidates = real_remake
        if real_lf:
            import publishing.longform_build as lb
            lb.render_pending = real_lf
    check("the parked run was skipped", picked, [107])


def main():
    init_db()
    print("reel retry policy\n")
    for t in (t_a_content_failure_is_parked_not_retried_forever,
              t_it_is_not_parked_one_attempt_early,
              t_a_transient_failure_is_never_parked,
              t_a_transient_failure_clears_the_content_streak,
              t_a_success_clears_everything,
              t_a_parked_run_is_not_picked_up_again):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all reel retry cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
