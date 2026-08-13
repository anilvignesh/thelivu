"""Reach — what happened after the gate.

Everything the engine measures is about production: cost per skill, tokens per
cycle, gate verdicts. This is the only view about *readers*. See
docs/reach-analytics.md.

It reads tables and calls nothing: the Instagram sweep runs on the engine
(`engine/agents/ig_insights.py`) because the API keeps two days of account reach
and no follower history, so a laptop-driven fetch would leave a hole for every
day the command centre was closed. `force_ig_sync` is the Refresh button, same
pattern as the belief scout's "Run now".

Everything here is a number we actually hold. Deliberately absent: Instagram
`profile_views` (returns empty on our token) and Telegram per-post views
(MTProto-only). An analytics view that quietly invents a number is worse than
one that admits a gap.
"""
from starlette.routing import Route

from command_center import db
from command_center.api.util import J, endpoint
from shared.db import kv_get, kv_set

# Only the latest snapshot per post is "how it is doing"; the earlier ones are
# the curve. Postgres has DISTINCT ON, SQLite does not, so this is the portable
# spelling — the CC talks to Railway Postgres in practice but the suites run on
# SQLite and a query that only works in one is a query that gets tested in one.
_LATEST_METRICS = """
SELECT m.media_id, m.media_type, m.product_type, m.permalink, m.caption,
       m.run_id, m.posted_at,
       x.reach, x.views, x.likes, x.comments, x.saved, x.shares, x.captured_at
FROM ig_media m
LEFT JOIN ig_media_metrics x ON x.id = (
    SELECT id FROM ig_media_metrics WHERE media_id = m.media_id
    ORDER BY captured_at DESC, id DESC LIMIT 1)
ORDER BY m.posted_at DESC
"""


def _posts():
    rows = db.q(_LATEST_METRICS)
    for r in rows:
        r["kind"] = "Reel" if (r.get("product_type") == "REELS") else "Carousel"
        # The caption's first line is the closest thing a post has to a title.
        cap = (r.get("caption") or "").strip().splitlines()
        r["title"] = (cap[0] if cap else "").strip()[:110]
        r.pop("caption", None)
    return rows


def _audience():
    return db.q("SELECT day, followers, reach_day, accounts_engaged, "
                "total_interactions, tg_subscribers FROM audience_daily "
                "ORDER BY day")


def _reads_by_day(days=30):
    """Human reads and bot hits per day, as two series over one date axis."""
    return db.q(
        "SELECT substr(CAST(read_at AS TEXT), 1, 10) AS day, "
        "SUM(CASE WHEN is_bot THEN 0 ELSE 1 END) AS humans, "
        "SUM(CASE WHEN is_bot THEN 1 ELSE 0 END) AS bots, "
        "COUNT(DISTINCT CASE WHEN is_bot THEN NULL ELSE visitor_hash END) AS uniques "
        "FROM page_reads GROUP BY 1 ORDER BY 1 DESC LIMIT %s" % int(days))


def _reads_by_article():
    return db.q(
        "SELECT slug, run_id, "
        "SUM(CASE WHEN is_bot THEN 0 ELSE 1 END) AS humans, "
        "SUM(CASE WHEN is_bot THEN 1 ELSE 0 END) AS bots, "
        "COUNT(DISTINCT CASE WHEN is_bot THEN NULL ELSE visitor_hash END) AS uniques, "
        "MAX(read_at) AS last_read "
        "FROM page_reads GROUP BY slug, run_id "
        "ORDER BY 3 DESC LIMIT 50")


def _referrers():
    return db.q(
        "SELECT COALESCE(referrer_host, 'direct') AS host, COUNT(*) AS n "
        "FROM page_reads WHERE is_bot = FALSE GROUP BY 1 ORDER BY 2 DESC LIMIT 10")


@endpoint
def reach_state(request, data):
    r = db.parallel(
        posts=_posts,
        audience=_audience,
        reads_day=_reads_by_day,
        reads_article=_reads_by_article,
        referrers=_referrers,
        settings=lambda: {k: kv_get(k) for k in
                          ("last_ig_sync_at", "last_ig_sync_result")},
    )
    posts, audience = r["posts"], r["audience"]
    latest = audience[-1] if audience else {}

    # Totals are over the LATEST snapshot of each post, never over the snapshot
    # table — that would sum the same post once per sweep and grow by itself
    # every six hours, which is the most flattering possible bug.
    def total(field):
        return sum((p.get(field) or 0) for p in posts)

    reads = r["reads_day"]
    return J({
        "posts": posts,
        "audience": audience,
        "reads_by_day": list(reversed(reads)),
        "reads_by_article": r["reads_article"],
        "referrers": r["referrers"],
        "totals": {
            "posts": len(posts),
            "reels": sum(1 for p in posts if p["kind"] == "Reel"),
            "carousels": sum(1 for p in posts if p["kind"] == "Carousel"),
            "reach": total("reach"), "views": total("views"),
            "likes": total("likes"), "comments": total("comments"),
            "saved": total("saved"), "shares": total("shares"),
            "followers": latest.get("followers"),
            "tg_subscribers": latest.get("tg_subscribers"),
            "reads_humans": sum((d.get("humans") or 0) for d in reads),
            "reads_bots": sum((d.get("bots") or 0) for d in reads),
        },
        "last_sync_at": r["settings"].get("last_ig_sync_at"),
        "last_sync_result": r["settings"].get("last_ig_sync_result"),
    })


@endpoint
def reach_sync(request, data):
    """Ask the engine for a fresh pull. The CC never calls Meta itself — the
    token lives on Railway and the history belongs to the process that is always
    on."""
    kv_set("force_ig_sync", "1")
    return J({"ok": True,
              "note": "Refresh queued — the engine picks it up within ~2 minutes."})


routes = [
    Route("/reach", reach_state),
    Route("/reach/sync", reach_sync, methods=["POST"]),
]
