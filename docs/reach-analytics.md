# Reach — what happens after the gate

*Context file for the 2026-08-08 analytics build. Requirement, what the APIs
actually give us, design, and the checks the build has to satisfy. Written
before the code, compared against it after.*

---

## 1. The requirement

**Anil, 2026-08-08:** count reads on the published stories, and give me an
analytics dashboard for the Instagram views, likes etc.

Thelivu has measured its own production in detail since day one — cost per
skill, tokens per cycle, gate verdicts, cache hit rates — and has measured its
**readership not at all**. Every article published since the Telegraph switch has
been read an unknown number of times, including possibly zero. This closes that.

Two deliverables:

1. **Article reads.** `/a/<slug>` counts its own readers.
2. **A Reach view** in the command centre: Instagram per-post and over-time
   numbers, plus the article reads and whatever else is honestly obtainable.

---

## 2. What the APIs actually give us — probed, not assumed

### Instagram: full access, confirmed working

`graph.instagram.com` with the Railway `IG_ACCESS_TOKEN`. The token carries
insights scope. Account `thelivu.reports`, **22 media, 19 followers**.

**Per-media** — both media types accept an identical metric set, which is why
one uniform table works:

| media_type / product | count | metrics that return 200 |
|---|---|---|
| `CAROUSEL_ALBUM` / `FEED` | 14 | reach, likes, comments, saved, shares, views |
| `VIDEO` / `REELS` | 8 | reach, likes, comments, saved, shares, views |

Sample: latest reel `reach 79 / views 96 / likes 3`; a carousel
`reach 13 / views 37 / likes 4`.

**Account level** — `reach` (day and days_28), `accounts_engaged`,
`total_interactions`. `profile_views` and `follows_and_unfollows` return 200 with
an **empty** data array on this token and are therefore not available to us; do
not build UI that expects them.

**The fact that decides the architecture: account `reach` with `period=day`
returns only two days** (yesterday and today), and `followers_count` is a bare
current number with no history at all. So the API cannot be the source of trend
— **if we do not snapshot daily, the history does not exist.** A view that
fetches live on load would be permanently two days deep.

Metric *titles* come back in Malayalam (account locale). Values are unaffected;
never display the API's `title`/`description`, only our own labels.

### Telegram: subscriber count only

`getChatMemberCount` on **തെളിവ്** / `thelivu_reports` → **6**. Per-post view
counts are **not in the Bot API** — `message.views` is MTProto-only and needs a
user session, not a bot token. The eye-count visible in the channel is not
reachable with what we hold. Show the subscriber count and say nothing we cannot
back.

### Article pages: nothing exists

`publishing/fileserver.py` serves `/a/<slug>` and records nothing. No analytics
table among the 20 in the DB, no tracker in the HTML, no request log.

---

## 3. Design — article reads

**Privacy first, because this is a journalism project and the alternative is
embarrassing.** No third party, no cookies, no JavaScript beacon, no IP stored.

`page_reads`: `id, slug, run_id, read_at, is_bot, visitor_hash, referrer_host`.

- `visitor_hash` = `sha256(ip + user_agent + daily_salt)[:16]`, where
  `daily_salt` is a random value regenerated each UTC day and never persisted
  beyond the current day's rows. That yields "unique readers today" without
  storing anything identifying, and makes cross-day tracking impossible **by
  construction** rather than by policy.
- `referrer_host` is the host only, never the full URL — a full referrer can
  carry a search query, which is content about the reader.
- Raw rows rather than counters: traffic is tiny (19 followers, 6 subscribers)
  and raw rows let us ask questions we have not thought of yet. Revisit if this
  ever gets big, which would be a nice problem.

**Bots must be counted separately, not silently dropped.** A large share of
`/a/` hits will be Telegram's link-preview fetcher, `facebookexternalhit`,
and search crawlers. Counting those as readers would make the numbers a lie in
the flattering direction, which is the worst kind. Classified by user-agent at
write time into `is_bot`, both kept, humans shown by default.

**The write must not be on the response path.** The fileserver is a
`BaseHTTPRequestHandler` and the DB is Railway Postgres at 0.25–1s per round
trip; an inline INSERT would put that latency in front of every article read. A
bounded in-process queue plus one background writer thread that batches. If the
queue is full the read is dropped rather than blocking a reader — analytics must
never be able to slow down or break the actual page. A restart loses whatever is
still queued; that is the correct trade and is stated here so nobody later
mistakes the counts for exact.

## 4. Design — Instagram snapshots

Three tables, because the three things have different shapes and lifetimes:

- `ig_media` — one row per post. `media_id, media_type, product_type,
  permalink, caption, posted_at, run_id`. `run_id` links back to our own
  `carousel_runs` / `reels` where resolvable, so a post can be traced to the
  story it came from.
- `ig_media_metrics` — snapshots. `media_id, captured_at, reach, views, likes,
  comments, saved, shares`. Append-only; a post's numbers keep moving for days
  and the shape of that curve is the interesting part.
- `ig_account_daily` — `day, followers, reach_day, accounts_engaged,
  total_interactions`. One row per UTC day, upserted, because the API will not
  give us yesterday.

**A sweep in the engine tick, not a fetch in the command centre.** The CC runs on
Anil's laptop and is not always on; a laptop-driven fetch would leave holes in
the history for every day he did not open it. The engine runs on Railway
continuously and already owns every other periodic sweep. Every **6 hours**: 22
media × 1 insights call + 2 account calls ≈ 24 calls, ~96/day against a 200/hour
limit. Comfortable.

`force_ig_sync` kv flag gives the view a Refresh button, matching the
`force_belief_scout` pattern.

**Costs nothing.** No model call — this is HTTP against Meta. It must not touch
the budget governor or the quota breaker, and it must not be parked when the
engine parks model stages, or the history gets holes on exactly the busy days.

## 5. Files

| file | change |
|---|---|
| `shared/db.py` | four tables + accessors |
| `publishing/fileserver.py` | count reads off the response path |
| `publishing/reads.py` | new — queue, writer thread, bot classification, hashing |
| `engine/agents/ig_insights.py` | new — the sweep |
| `run.py` | wire the sweep + `force_ig_sync` |
| `command_center/api/reach.py` | new — the view's data |
| `command_center/static/app.js` | the Reach view + inline SVG charts |
| `shared/tests/run_reads_cases.py` | new |
| `PROJECT-STATUS.md` | log it |

## 6. What the build must satisfy

Article reads:

1. A normal browser GET of a published `/a/<slug>` records one row, `is_bot`
   false.
2. `TelegramBot`, `facebookexternalhit`, `Googlebot`, `bingbot` and a bare
   `python-requests` UA record with `is_bot` true.
3. A 404 slug records nothing — an unpublished or wrong URL is not a read.
4. The same reader hitting the same article twice in a day is one unique and two
   reads.
5. `visitor_hash` is stable within a UTC day and different across days for the
   same ip+UA. No IP or raw UA anywhere in the table.
6. Recording never blocks the response: with the DB unreachable the page still
   renders 200, and with the queue full the read is dropped, not queued
   unboundedly.
7. `referrer_host` keeps the host and discards path and query.

Instagram:

8. The sweep upserts `ig_media` (no duplicate rows on a second run) and appends
   to `ig_media_metrics` (a second run adds new snapshot rows).
9. `ig_account_daily` upserts on `day` — running twice in a day leaves one row.
10. A media whose insights call fails does not abort the sweep; the rest still
    land.
11. The sweep runs with the budget governor parked and does not record
    `token_usage`.

The view:

12. Renders with zero data (before the first sweep) without throwing.
13. Bot reads are excluded from the headline number and available behind a
    toggle.
14. Every number is one we actually hold — no `profile_views`, no Telegram
    per-post views.
