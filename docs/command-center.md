# Thelivu Command Center — build spec

*Context doc for the command-center build (Anil's 5-step workflow, step 2).
Written 2026-07-15. This is the target; build against it, then compare.*

The current `dashboard.py` is a read-mostly Streamlit app (Overview / Drafts /
Pipeline / Sources / Costs). This turns it into an **active newsroom command
center** with four new capabilities, plus a proactive follow-up brain.

## Autonomy context
Per Anil (2026-07-15): full autonomy on Thelivu — build features, work stories,
change backend — **the only gate is the final publish/post**. As of 2026-08-29
(Anil, explicit) that gate is removed too: every story that clears editorial
review posts autonomously, including ones with real legal exposure — see
`engine/distribution/sweep.py`. See memory `thelivu-autonomy`.

---

## 1. Ingestion — paste a link, we pick it up
**Want:** paste an article URL or a video (YouTube) link; the engine ingests it
and runs it into the pipeline as a lead (never auto-published).

- Dashboard **Ingest** tab: a box that accepts one or more URLs (+ optional note
  / angle). Detects type:
  - **YouTube** → existing path: transcript (`youtube_transcript_api`) or Gemini
    video ingest → `source-ingestor` → structured lead → pipeline.
  - **Web article** → fetch readable text (server-side), hand to `topic-intake`
    as "I came across this: <url>\n<angle>" so it triages scope + worth, then
    verifies on the open web.
- Backend: a `queue_ingest(url, note)` helper writing to `pending_topics`
  (source=`ingest`) with a `[LINK]` marker; `_run_topic_intake` already runs
  every 2-min tick. URL-fetch lives in a new `ingestion/fetch.py` (readability
  extract, with the Indian-ISP retry discipline for any flaky host).
- Show ingest history + status (queued / running / became run #N / declined).

## 2. Persistent digs — a thread investigated over days
**Want:** hand the engine a thread and have it investigated **thoroughly over
multiple days**, with visible state, accumulating records and findings.

Today the dig is fire-and-forget (`kv_store.dig_request` → one `story-scout`
brief → a Telegram button). Make it a **persistent object**:

- New tables:
  - `digs(id, title, question, kerala_anchor, hypothesis, status, priority,
    watchlist_id, created_at, updated_at, next_action_at, owner_note)`
    status: `scoping | records-pending | verifying | ready-to-write | parked | killed`
  - `dig_updates(id, dig_id, kind, body, created_at)` — an append-only log
    (kind: `brief | records | finding | rti | kill-test | note | promoted`).
- Lifecycle: create a dig (from watchlist theme or free text) → each **advance**
  step runs `story-scout` with the dig's full history as context, pulls the next
  primary records via web tools, tries to disprove, appends a `dig_updates` row,
  updates `status`/`next_action_at`. Runs attended (a "Advance dig" button) and
  on a daily orchestrator tick for digs whose `next_action_at` is due.
- When a dig reaches `ready-to-write`, promote → `pending_topics` (source=`dig`)
  so it enters the normal pipeline and lands at the human gate.
- Dashboard **Digs** tab: list with status/priority, full update timeline, and
  buttons: New dig · Advance · Park · Kill · Promote to draft. Watchlist themes
  shown alongside so a theme can be started as a dig in one click.

## 3. Chief of staff — proactive follow-ups
**Want:** something that actively works the backlog — drafts, held items, dropped
threads — checks whether they're still relevant, whether anything moved, and
drives new investigation threads. (`story-tracker` already does this for
*published* stories; extend the reach.)

- New skill `chief-of-staff` (or a broadened tracker). Daily/attended sweep over:
  - **Held** runs (`status in held/hold`) — still relevant? developed? → requeue,
    refresh (new recheck), or recommend kill, with reason.
  - **Stale pending_human** drafts (> N days at the gate) — nudge with a one-line
    "why this still matters / what changed."
  - **Dropped threads** — killed digs / parked digs / declined topics — scan for a
    revival trigger (a new event that changes the calculus).
  - **New-thread generation** — from recurring patterns across the archive +
    watchlist gaps, propose net-new investigation threads (→ new digs).
- Output: a **Chief-of-staff brief** (Telegram card + dashboard panel) with ranked
  recommended actions, each a one-tap button (requeue / recheck / kill / open as
  dig / queue topic). Never publishes.
- Dashboard **Follow-ups** tab surfaces the latest brief + backlog aging.

## 4. Dashboard → command center (surface)
Rework tabs into:
`Overview · Ingest · Drafts · Pipeline · Digs · Follow-ups · Sources · Tasks · Costs`

- **Overview:** live agents, backlog aging (pending/held counts by age), digs in
  flight, next scheduled jobs, today's cost — the "one screen" status.
- **Sources (+ analyse):** existing add/approve **plus** per-source analytics —
  leads produced, → runs, → published, kill rate, trust-gate mix, last-seen. So a
  source can be judged and retired on evidence (`get_source_reliability` exists).
- **Tasks / Schedules:** the periodic jobs (RSS cycle, weekly source+story scout,
  story-tracker, monthly meta-synthesis, daily auto-recheck, chief-of-staff) with
  last-run, next-due (from `kv_store` `last_*_at` stamps), and a **Run now**
  button each (writes the existing `kv_store` signal the tick loop reads). Plus
  live `active_agents` and the pending queue.
- **Drafts/Pipeline:** keep current read + approve/kill/hold; add "open as dig"
  and "send back for recheck." Publishing stays the one gated action.

## Data model additions (summary)
- `digs`, `dig_updates` (new).
- `pending_topics.source` values extended: `ingest`, `dig`, `chief-of-staff`.
- `kv_store` signal keys: `advance_dig_id`, `run_chief_of_staff`, plus existing
  `dig_request`, `force_rss_run`, `force_scout_run`.
- Reuse: `pipeline_runs`, `lead_queue`, `approved_sources`, `token_usage`,
  `active_agents`, `get_source_reliability`, `get_published_stories`.

## Build order
1. **DB layer** — `digs`/`dig_updates` tables + migration in `init_db`, helpers in
   `shared/db.py`. Create tables in prod DB. *(foundation)*
2. **Dig backend** — advance step in orchestrator + `run_dig_advance`, promote path.
3. **Ingestion** — `ingestion/fetch.py` + `queue_ingest`; URL-aware topic-intake.
4. **Chief-of-staff** — skill + `run_chief_of_staff` runner + kv signal + tick.
5. **Dashboard** — rebuild into the tab set above, wired to all of the above.
6. **Test** each layer locally against prod DB before moving on; deploy backend to
   Railway (`main`) once the orchestrator-side pieces are proven. Publishing gate
   untouched.

## Invariants (do not drift — see docs/HANDOFF.md §6)
Verification engine with a human gate. Publisher never runs an LLM over an
approved draft. Sources are leads; the open web verifies. Nothing posts without
Anil. Digs can end in "not established" — that's a success.
