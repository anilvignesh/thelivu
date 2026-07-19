# Thelivu — Operations & Continuation Handoff

*Written 2026-07-14 for any assistant (or human) taking over development and
maintenance. It captures the operational layer the other docs don't: how the
deployed system is wired, how to reach it, and the hard-won gotchas. Assume
nothing about the model reading this — everything needed is written down or
pointed to.*

---

## 1. Bootstrap reading order

1. `engine/START-HERE.md` — how the engine runs (charter, skills, cycle).
2. `engine/CONTEXT-AND-HISTORY.md` — why every rule exists. **Read before
   changing any editorial behavior.**
3. `PROJECT-STATUS.md` — living state; update it as you work. **The "command
   center era" section (2026-07-20) is current; a pre-launch snapshot below it is
   historical.**
4. `docs/command-center.md` — build spec for the digs / ingestion / chief-of-staff /
   dashboard layer added this era.
5. `MANUAL.md` — every bot command, for the owner.
6. `docs/bio-page.md`, `docs/article-hosting.md` — design notes for the web
   surface (written before building; keep them true).
7. This file, §5 (gotchas) and §7 (data model / kv signals) — the operational
   reality and the traps.

The owner is **Anil** (Telegram: the draft chat the bot posts to). He is
technical, direct, and approves every publish personally. **The human gate is
absolute — there is deliberately no bypass flag. Do not add one.** Per the
2026-07-15 autonomy grant, publishing is the ONLY action gated on Anil; act
autonomously on everything else and report.

---

## 2. Deployed topology

One Railway project (**`brave-determination`**), three services, auto-deploys
from GitHub `main` (repo: `anilvignesh/thelivu`; local checkout `~/thelivu`
with venv at `~/thelivu/venv`):

| Service | Runs | Entry |
|---|---|---|
| `thelivu-agent` | Orchestrator loop (2-min tick) + public web server on :8080 | `run.py` with `RAILWAY_SERVICE_NAME=thelivu-agent` |
| `thelivu` | The Telegram bot (approval gate, commands) | `python -m thelivu_bot.bot` |
| `Postgres` | The database both services share | — |

Public domain: **`https://thelivu.up.railway.app`** (Railway service domain on
`thelivu-agent`; the `up.` is mandatory — bare `*.railway.app` is Railway's own
namespace). Routes served by `publishing/fileserver.py`:

- `/` and `/bio` — the link-in-bio page (`publishing/biopage.py`)
- `/a/<run_id>-<kebab-headline>` — self-hosted article pages
  (`publishing/articlepage.py`); **only `status='published'` runs are served**
- `/<name>.png` — rendered carousel slides (for Instagram's image fetch).
  **Rendered ON DEMAND from the DB** if the file is missing (regenerated from
  `carousel_slides.headline` + `carousel_runs.dark/stamp`) — so slides survive a
  redeploy or the cleanup sweep, same philosophy as `/a/<slug>`. Added 2026-07-19
  after redeploys kept wiping pending carousels' images and breaking IG posting.

All pages send `Cache-Control: no-cache` and are rendered per request from the
DB — there is no publish/build step for the web surface.

**The command center** (`dashboard.py`) is a separate 10-tab Streamlit control
panel — NOT deployed to Railway. Run locally against the prod DB (Overview · Ingest
· Drafts · Pipeline · Carousels · Digs · Follow-ups · Sources · Tasks · Costs).
Reached from Anil's phone over **Tailscale** (laptop `100.70.158.55:8501`) or the
home LAN; auto-starts on login via `~/.jarvis/thelivu-dashboard.sh` +
`~/.config/autostart/thelivu-dashboard.desktop`. Deps are in
`requirements-dashboard.txt` (kept out of the lean agent `requirements.txt`). It
needs the same env as the bot (DB + Telegram + `SLIDE_SERVER_BASE_URL` +
`CONTACT_HANDLE` + `IG_USER_ID`/`IG_ACCESS_TOKEN`) — the launcher pulls them from
Railway each boot. Password gate via `DASHBOARD_PASSWORD`; refuses to start without it.

## 3. The publish flow, end to end

1. Engine produces a draft → owner gets a 📰 card with Approve/Kill/Hold.
2. **Approve → `publishing.publish.publish_run(run_id)`** — the ONE shared publish
   path that BOTH the bot's approve handler and the dashboard call (do not write a
   second copy; that divergence produced link-less posts). It prepares the draft,
   writes a `slug`, posts an HTML teaser linking `SLIDE_SERVER_BASE_URL/a/<slug>`,
   adds a relative `/a/<slug>` to `bio_links`, marks the run `published`, and queues
   a carousel. Falls back to a chunked plain-text post if the article-page path fails.
3. Orchestrator's next tick composes the carousel (Claude decides slide text,
   `DARK:` mood, `HASHTAGS:`, and the count sized for engagement 8–10), persists the
   slides + `dark`/`stamp` to the DB, renders PNGs, sends the album with Post/Kill.
4. **Post → `publishing.publish.post_carousel_run(carousel_id)`** — again the ONE
   shared path (bot + dashboard). Dedupes slides by position, caps at 10, publishes
   via the Graph API (Meta fetches the images from our own domain). Slide files are
   auto-deleted once a carousel is terminal (`cleanup_finished_carousels`) — safe now
   that the fileserver re-renders on demand.

**Publishing is the ONLY gated action.** Per the 2026-07-15 autonomy grant everything
else (features, story work, digs, chief-of-staff, recheck) runs without asking; only
posting to the channel / Instagram waits for the owner's tap/click.

**Telegraph (telegra.ph) is out of the reader path** — see §5. It is still
used for owner-facing report/preview links (read inside Telegram, where it
works). The old seven telegra.ph article pages were edited into "this story
has moved" stubs pointing at the self-hosted URLs (Telegraph has **no delete
API** — stubs are the only retirement).

## 4. Operational access (from Anil's laptop)

- **Railway CLI**: `~/.railway/bin/railway` (add to PATH), already logged in
  as Anil, project linked. Key commands:
  - `railway variables --service <svc> --json` — read env vars
  - `railway variable set KEY=VAL --service <svc>` — set (triggers redeploy)
  - `railway variable delete KEY --service <svc>` — delete (**does NOT
    redeploy — follow with `railway redeploy --service <svc> --yes`**)
  - `railway deployment list --service <svc> --json` — deploy status
  - `railway logs --service <svc>` — recent logs
  - `railway domain ...` — domains (`domain update <cur> --domain <new>`
    renames; old domain dies instantly — update `SLIDE_SERVER_BASE_URL` too)
- **Production DB**: internal `DATABASE_URL` is unreachable from outside; use
  `DATABASE_PUBLIC_URL` from the **Postgres service's** variables. With
  `DATABASE_URL=<public url>` in the environment, `shared/db.py` speaks
  Postgres directly — all helper functions work locally against prod.
- **Telegraph token**: `kv_store` key `telegraph_token` (prod DB).
- **Bot token**: `TELEGRAM_BOT_TOKEN` on the `thelivu` service. The channel is
  `TELEGRAM_CHANNEL_ID=-1004360555583`, public handle `@thelivu_reports`
  (title "തെളിവ്"). `CHANNEL_PUBLIC_URL` is currently **unset on purpose**
  (owner removed the header link from the bio page for now; setting the var
  brings it back).
- Local testing pattern: set `DB_PATH` to a scratch file for SQLite mode,
  `init_db()`, insert fixtures, `publishing.fileserver.start(dir, port)`, hit
  it with urllib. `venv/bin/python -m py_compile <files>` before committing.

## 5. Hard-won gotchas (each cost real debugging time)

1. **Indian ISPs block Telegram domains.** On Anil's connection `t.me` does
   not resolve at all and `telegra.ph` intermittently connection-resets. This
   is WHY articles are self-hosted. Any network call to `api.telegra.ph` needs
   a retry loop (10+ tries, backoff) even from the laptop. Never put a
   Telegram-owned domain in the reader path again.
2. **LLM output is Markdown; Telegram cards are HTML.** Any skill output going
   into an owner card must pass `_md_to_tg_html()` (orchestrator) — raw text
   shows literal `**`/`###`, and a naive 4096 cut mid-tag makes Telegram
   reject the whole message.
3. **Draft anatomy**: drafts start with `# DRAFT — for human review`
   (sometimes inside a ``` fence), then an italic "*From Thelivu…*" standfirst,
   then the real headline — which is *usually* `#` but at least once was `##`
   (run 53). **Never extract titles ad-hoc**: use
   `publishing.parser.extract_headline` / `strip_scaffolding` /
   `prepare_for_publish`. Every past title bug came from a second,
   slightly-different implementation.
4. **Slug lookups match the run-id prefix only** (`get_run_by_slug`), so
   retitling never breaks shared links. Keep it that way.
5. **`bio_links` URLs are relative** (`/a/<slug>`) so a domain change needs no
   data migration. The bio page orders pinned-first then id DESC — inserting
   in chronological order matters when backfilling.
6. **Telegraph `editPage` keeps the URL path** regardless of title; there is
   no delete. `getPageList` on the account token enumerates everything ever
   published (includes owner-facing reports — that's expected).
7. **Instagram**: profile bio link is manual-only (no API). Carousel images
   must be fetchable by Meta → they're served from our own domain, never a
   third-party host, never a URL with an embedded secret (locked decision,
   commit c6b00c2).
8. Deploys take ~2–3 minutes; verify with the `deployment list` status plus a
   `curl` of the live surface before telling the owner something is live. When
   confirming a deploy, check the commit hash matches HEAD — `SUCCESS` alone can
   be the *previous* deploy that hasn't rolled over yet.
9. **`SLIDE_SERVER_BASE_URL` must be set on BOTH `thelivu-agent` AND `thelivu`
   (the bot).** The bot needs it at approval time to build the `/a/<slug>` page +
   bio link + linked carousel; the agent needs it to host the images. If unset on
   the bot, every approval silently falls back to a plain-text post with no article
   page (this happened 2026-07-15→18 — the July-14 domain rename set it on the agent
   only; fixed + backfilled 2026-07-19). Re-verify on the bot after any domain change.
10. **Meta / Graph API is flaky from the laptop** (same ISP issue as §5.1). A
    reset/empty response makes `r.json()` throw a bare "Expecting value: line 1
    column 1"; Meta also returns transient error objects (`code:2`,
    `is_transient:true`). `publishing/instagram.py` retries BOTH (transport failures
    and transient error payloads). The bot posts from Railway (clean network); the
    dashboard posts from the laptop (exposed to this) — the retries cover both.
11. **Instagram uses `graph.instagram.com` (Instagram-Login API), NOT
    `graph.facebook.com`.** The account is `thelivu.reports` (MEDIA_CREATOR).
    `IG_USER_ID` differs from the token's own id but both work for `/media`. A
    `graph.facebook.com` call returns "Cannot parse access token" — wrong host,
    not a bad token.
12. **Chief-of-staff / any skill emitting machine blocks can truncate.** A long
    prose brief can run past `max_tokens` before closing `END_RECOMMENDATIONS` /
    `NEW_DIGS`, yielding zero parsed actions. Give such skills a generous budget,
    tell them the blocks are mandatory + complete, and parse tolerantly (salvage a
    truncated array) — see `_extract_block_array` in the orchestrator.
13. **Claude web-search loops re-bill the whole context each round** — an uncapped
    loop ballooned to ~400k input tokens/call (~95% of all spend). `_run_claude`
    caps tool rounds at 6 then forces a final answer, and prompt-caches the growing
    prefix. Keep both. Cost is dominated by these fallbacks, not routine research.
14. **Research skills run on Gemini + Google Search with no cross-engine fallback
    for QUOTA outages** (pause + queue) — BUT a Gemini *content block* (empty
    response / SAFETY) now falls back to Claude+web-search, because a block is
    permanent and an outage is transient. That's why named-politician stories that
    used to "return empty" now go through.
15. **Dashboard = ephemeral local process.** It dies on reboot (autostart relaunches
    it) and on any redeploy of nothing — it's not on Railway. DB calls use
    `connect_timeout` so a Railway blip fails fast instead of freezing the page. A
    Streamlit click reruns the WHOLE script before the handler — that's the delay
    before actions/animations start; the real fix is a proper web app (Kiln-era).
16. **YouTube `channel_id`s go stale/get repurposed.** Verify a feed resolves
    (`feedparser.parse` returns entries) before trusting it. Johnny Harris's id was
    wrong; `@perfectunion` now resolves to a different channel (deactivated).
    Confirmed working: ColdFusion, Coffeezilla, FYI.

## 6. Editorial invariants (do not drift)

The spine: **a verification engine with a human gate** — compelling-but-false
claims get downgraded, attributed, or dropped (see the case list in
`PROJECT-STATUS.md`). Transparent perspective, English, **global scope with a
Kerala emphasis — NOT "Kerala-first"** (repositioned 2026-07-16; national +
international fully in scope, not "as a lens"). Sources are leads; the open web
verifies. The publisher stage is deliberately dumb: **never run an LLM over an
approved draft**. **Publishing is the only owner-gated action** (2026-07-15 autonomy
grant) — everything else is autonomous.

## 7. Data model / kv signals added this era (for a fresh model)

- Tables: `digs`, `dig_updates` (persistent digs); `carousel_runs.dark/stamp`
  (on-demand slide re-render). Helpers in `shared/db.py` (`create_dig`,
  `run`-style dig fns, `get_slide_render_data`, `clear_carousel_slides`, `queue_ingest`).
- `pending_topics.source` values: `ingest`, `dig`, `chief-of-staff` (+ existing
  `owner`, `owner-telegram`, `story-scout`, `dashboard`).
- kv_store signals the tick loop reads: `advance_dig_id`, `promote_dig_id`,
  `dig_request`, `run_chief_of_staff`, `force_scout_run`, `force_tracker_run`,
  `force_meta_run`, `force_rss_run`, `recheck_note_<id>`; state stamps
  `last_cos_at`, `last_dig_sweep_at`, `latest_cos_brief`, `latest_cos_actions`,
  `latest_scout_brief`.
- New code files: `publishing/publish.py` (shared publish/post), `ingestion/fetch.py`
  (link fetch), `engine/skills/chief-of-staff/`, `engine/skills/video-script/`
  (scaffold), `docs/command-center.md` (build spec), `docs/video-reels-research.md`.

Brand: the "dossier" system — palette lives in `publishing/slides.py`
(`PALETTE`), mirrored inline in `biopage.py`/`articlepage.py` (kraft
`#E6DCC3`/ink `#1B1710`/brick `#8C2A1B`; dark: `#17140D`/`#E9E0C8`/gold
`#D2AA6D`). DejaVu Sans Mono is bundled in `publishing/fonts/` because
Liberation Mono lacks the ₹ glyph.

## 7. Working conventions with Anil

- Follow his 5-step workflow: understand → write/update a context md in
  `docs/` → build → compare against the context md → test.
- Test before claiming done: exercise the real flow (spin up the server, hit
  the route), not just compilation.
- Commit with clear multi-line messages explaining *why*; he approves
  commits/pushes conversationally — pushing deploys to production, so say so.
- Update `PROJECT-STATUS.md` as part of any feature, not after.
- He reads everything in Telegram — keep owner-facing text clean (see §5.2).

## 8. State as of 2026-07-14 (verify before trusting)

- 7 stories published; all on the bio page and self-hosted.
- 1 carousel posted to Instagram; 6 rendered, awaiting owner approval in the
  draft chat (advice given: approve ~one/day).
- Instagram bio link: owner was setting it to the base URL manually.
- Open threads: validation week (`engine/DRY-RUN-PLAYBOOK.md`); the
  Vizhinjam/Adani dig (watchlist); media-lawyer review before going public;
  Instagram ingestion path decision. Phase 2 (automation, tip line) is
  deferred — see `engine/DEPLOYMENT.md`.
