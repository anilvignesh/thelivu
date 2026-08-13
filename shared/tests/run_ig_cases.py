"""The Instagram snapshot sweep — idempotence, and not losing a sweep to one post.

    python -m shared.tests.run_ig_cases

No network: the three fetch functions are stubbed, so this exercises the sweep's
bookkeeping rather than Meta's API. A live probe is a different activity and was
done by hand on 2026-08-08 (docs/reach-analytics.md §2).

What it is FOR: this sweep runs every 6 hours forever, over the same posts. Get
the upsert wrong and `ig_media` grows a duplicate set every sweep; get the
account upsert wrong and one day becomes four rows; let one post's failure
propagate and a single reel that Meta is still processing costs the whole
history for that run.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name
os.environ.setdefault("IG_ACCESS_TOKEN", "test-token")
os.environ.setdefault("IG_USER_ID", "test-user")

from engine.agents import ig_insights as ig          # noqa: E402
from shared.db import init_db, _conn                 # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def one(sql):
    cur = _conn().cursor()
    cur.execute(sql)
    return cur.fetchone()[0]


MEDIA = [
    {"id": "111", "media_type": "VIDEO", "media_product_type": "REELS",
     "timestamp": "2026-08-08T05:21:11+0000", "permalink": "https://instagram.com/reel/A",
     "caption": "a reel"},
    {"id": "222", "media_type": "CAROUSEL_ALBUM", "media_product_type": "FEED",
     "timestamp": "2026-08-02T18:39:14+0000", "permalink": "https://instagram.com/p/B",
     "caption": "a carousel"},
]


def _stub(*, failing=()):
    ig.fetch_media = lambda tok, uid: list(MEDIA)

    def insights(tok, mid):
        if mid in failing:
            raise RuntimeError("400: media not ready")
        return {"reach": 79, "views": 96, "likes": 3, "comments": 0,
                "saved": 0, "shares": 0}
    ig.fetch_media_insights = insights
    ig.fetch_account = lambda tok, uid: {
        "followers": 19, "reach": 45, "accounts_engaged": 3, "total_interactions": 3}


def t_idempotent():
    print("\nthe sweep runs every 6 hours over the same posts, forever:")
    _stub()
    ig.run_ig_sync()
    check("first sweep records both posts", one("SELECT COUNT(*) FROM ig_media"), 2)
    check("...with a snapshot each", one("SELECT COUNT(*) FROM ig_media_metrics"), 2)
    check("...and one account day", one("SELECT COUNT(*) FROM audience_daily"), 1)

    ig.run_ig_sync()
    check("a second sweep does NOT duplicate the posts",
          one("SELECT COUNT(*) FROM ig_media"), 2)
    check("...but DOES append snapshots, which is the trend",
          one("SELECT COUNT(*) FROM ig_media_metrics"), 4)
    check("...and still one row for the day",
          one("SELECT COUNT(*) FROM audience_daily"), 1)
    check("the day carries the numbers",
          one("SELECT followers FROM audience_daily"), 19)


def t_one_bad_post_does_not_cost_the_sweep():
    print("\na reel Meta is still processing must not cost the other 21:")
    _stub(failing={"111"})
    before = one("SELECT COUNT(*) FROM ig_media_metrics")
    result = ig.run_ig_sync()
    after = one("SELECT COUNT(*) FROM ig_media_metrics")
    check("the healthy post still snapshotted", after - before, 1)
    check("and the summary says one failed", "1 failed" in result, True)
    check("the account snapshot still happened",
          one("SELECT COUNT(*) FROM audience_daily"), 1)


def t_account_failure_is_survivable():
    print("\nand neither does a broken account call:")
    _stub()

    def boom(tok, uid):
        raise RuntimeError("500")
    ig.fetch_account = boom
    before = one("SELECT COUNT(*) FROM ig_media_metrics")
    result = ig.run_ig_sync()
    check("posts were still snapshotted",
          one("SELECT COUNT(*) FROM ig_media_metrics") - before, 2)
    check("and it says so rather than pretending", "account snapshot failed" in result, True)


def t_metric_values_shapes():
    print("\nboth response shapes the Graph API uses:")
    check("period metrics come from values[]",
          ig._metric_values({"data": [{"name": "reach", "values": [{"value": 45}]}]}),
          {"reach": 45})
    check("total_value metrics come from total_value",
          ig._metric_values({"data": [{"name": "accounts_engaged",
                                       "total_value": {"value": 3}}]}),
          {"accounts_engaged": 3})
    check("an empty data array is empty, not an error",
          ig._metric_values({"data": []}), {})
    # profile_views returns exactly this on our token — 200 with nothing in it.
    check("a metric present but valueless is skipped",
          ig._metric_values({"data": [{"name": "profile_views"}]}), {})


def t_sync_due():
    print("\nwhen the sweep is due:")
    from datetime import datetime, timedelta, timezone
    from shared.db import kv_set
    now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    kv_set(ig.LAST_SYNC_KEY, "")
    check("never synced → due", ig.sync_due(now), True)
    kv_set(ig.LAST_SYNC_KEY, (now - timedelta(hours=2)).isoformat())
    check("2h ago → not due", ig.sync_due(now), False)
    kv_set(ig.LAST_SYNC_KEY, (now - timedelta(hours=7)).isoformat())
    check("7h ago → due", ig.sync_due(now), True)
    kv_set(ig.LAST_SYNC_KEY, "not a date")
    check("an unparseable stamp → due, not never", ig.sync_due(now), True)
    kv_set(ig.LAST_SYNC_KEY, (now - timedelta(hours=3)).replace(tzinfo=None).isoformat())
    check("a naive stamp → read as UTC, not a TypeError", ig.sync_due(now), False)
    kv_set(ig.LAST_SYNC_KEY, (now + timedelta(days=3)).isoformat())
    check("a stamp in the future → due, not never", ig.sync_due(now), True)


def main():
    init_db()
    for t in (t_idempotent, t_one_bad_post_does_not_cost_the_sweep,
              t_account_failure_is_survivable, t_metric_values_shapes, t_sync_due):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all instagram sweep cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
