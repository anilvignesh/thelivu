# 4. Data

One Postgres database on Railway, the source of truth. The laptop falls back to SQLite (`thelivu.db`) only when `DATABASE_URL` is unset;
that is how 1,966 findings once ended up on the laptop only (fixed 2026-10-14). **Always set `DATABASE_URL`** (public URL from the
Postgres service: `railway variables --service Postgres --json`). All access goes through `shared/db.py`, which speaks both dialects.

Counts verified 2026-10-22.

## Editorial pipeline

| Table | Rows | Holds |
|---|---|---|
| `pipeline_runs` | 343 | one row per story: topic, drafts, verification report, status (`published`, `hold`, `animate`, `kill`, `dropped`), `desk`, `legal_flag` |
| `publications` | 155 | published articles: run, Telegram message ids, confidence |
| `pending_topics` | 112 | topic queue the spine pops one per tick |
| `lead_queue` | 26,071 | every lead ever seen from news feeds; ~25k are `dropped`, ~1.5k `queued` since 15 Oct |
| `seen_items` | 31,292 | de-duplication ledger for feed items |
| `digs`, `dig_updates` | 114, 446 | long-running investigations the chief of staff advances |
| `bio_links` | 155 | what the bio/feed pages list |
| `page_reads` | 1,796 | cookie-free reader counts |

## Public records

| Table | Rows | Holds |
|---|---|---|
| `documents` | 338 | full text of audit reports (title, source key, url, `read_at`) |
| `findings` | 3,663 | grounded findings: claim, verbatim excerpt, `amount_cr`, `cause` (`state` / `unclear`...), `category` |
| `syntheses` | 305 | detector output, each citing finding ids; **leads, not stories** |
| `digger_runs`, `digger_candidates`, `digger_targets` | 2,825, 43, 4 | the digger's activity |
| `source_checks`, `source_proposals`, `approved_sources` | 925, 58, 42 | scout verdicts and proposals |
| `rti_requests` | 1 | RTI tracker, barely used |

## Reels and video

| Table | Rows | Holds |
|---|---|---|
| `reels` | 169 | rendered MP4 bytes plus status (`ready`, `posted`, `killed`, `superseded`), IG and YouTube ids |
| `longform_queue` | 4 | long-form scripts and renders |
| `ig_media`, `ig_media_metrics`, `yt_video_metrics`, `audience_daily` | 99, 15,050, 11,345, 66 | reach analytics |

## Operations

| Table | Rows | Holds |
|---|---|---|
| `kv_store` | 613 | flags, timestamps, per-run state. 351 are `reel_*` keys and 39 are old `quota_alert_*` keys: unbounded growth |
| `engine_events` | 1,827 | every card/alert the engine sent (and whether Telegram delivered it) |
| `token_usage` | 5,186 | cost accounting per skill and model |
| `model_health_checks` | 1,452 | health pings |
| `active_agents` | 0 | running-agent registry |

## Dead tables (nothing writes to them any more)

`carousel_runs` (last 23 Jul), `carousel_slides`, `slide_runs` (13 Jul): carousels are retired. `belief_pieces`, `belief_queue` (last 8 Sep): the belief/"Everyone Knows" desks were retired 2026-09-08. `archived_docs` (1 row).
