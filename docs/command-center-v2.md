# Thelivu Command Center v2 — build spec

*Context doc (Anil's 5-step workflow, step 2). Written 2026-07-26. Supersedes the
Streamlit `dashboard.py` as the operations surface — `docs/command-center.md`
remains the record of the v1 feature set, all of which carries forward.*

## Why v2

The Streamlit dashboard proved the feature set but hit its ceiling: every click
reruns the whole script, every tab renders on every rerun, actions lag, and the
framework fights the product (see docs/HANDOFF.md §5.15 — "the real fix is a
proper web app"). Thelivu's operations currently lean on Claude sessions for
anything the dashboard can't do. **The command center becomes the main operation
base**: everything short of the publish gate is drivable from one app, and the
architecture is open for whatever comes next.

## Stack (no new dependencies)

- **Backend:** Starlette + uvicorn (already in `venv` as Streamlit deps).
  Package `command_center/`, served on **0.0.0.0:8600** — laptop, LAN, and
  phone over Tailscale (100.70.158.55:8600), same reach as the old dashboard.
- **Frontend:** hand-rolled SPA — one `index.html`, one `app.js`, one
  `style.css`. Zero external assets. Dossier brand (kraft `#E6DCC3` / ink
  `#17140D` / gold `#D2AA6D` / brick `#8C2A1B`, mono headers). Responsive:
  sidebar on desktop, bottom tab bar on the phone.
- **DB:** the shared Railway Postgres, via a warm psycopg2 pool
  (`command_center/db.py`, same stale-socket retry discipline the Streamlit app
  learned). Mutations that have logic go through `shared/db.py` helpers.
- **Long actions** (post carousel, build reel, publish, AI suggestions) run as
  **background jobs** (`command_center/jobs.py`, threads + a status registry);
  the UI polls `/api/jobs/<id>` and shows live progress. No frozen pages.
- **Auth:** `DASHBOARD_PASSWORD` (refuses to start without it) → login → signed
  HttpOnly cookie. All `/api/*` except login require it.

## Invariants (unchanged, non-negotiable)

- **Publishing/posting is the ONLY gated action.** Approve-article, post-carousel,
  post-reel go through the ONE shared paths (`publishing.publish.publish_run` /
  `post_carousel_run` / `post_reel_run`) and always behind an explicit confirm
  modal. No bypass flag. Everything else is autonomous.
- **Never run an LLM over an approved draft.** Human edits to a draft are fine
  (they're the gate working); AI suggestions run pre-approval only.
- **Model split:** journalism (suggestions, recheck) = Claude/Gemini only —
  quota-aware, degrades to "breaker open, run attended" when dry. Presentation
  (carousel compose, reel script) = free NVIDIA Gemma path, unaffected.
- **`engine/attend.py` is never automated.** When the breaker is open the UI
  *names* the attend command; it never runs it.

## Layout — 11 views

| View | What it does |
|---|---|
| **Overview** | Needs-you banner (gate count), status tiles, breaker + voice-server status, live agents, digs in flight, recent runs, today's cost. The one screen. |
| **Gate** | The review desk. Pending + held runs: full draft (rendered), verification report, review notes. Actions: **Approve→publish** (gated, confirm), Kill, Hold, Requeue, **Recheck with editorial direction**, **Edit draft** (inline, human edit), **AI suggestions** (editorial-reviewer, quota-aware). |
| **Stories** | Full pipeline browser: filter/search all runs, per-run detail (texts, publication, linked carousel + reel), article-page link, "make carousel", "make reel" from any published run. |
| **Carousels** | Review desk for slides: preview strip, **edit any slide's headline** (re-renders via fileserver `?fresh=1`), edit caption, Rebuild (recompose), **Post** (gated), Kill. Breaker-aware compose warnings with the exact attend command. |
| **Reels** | The reach surface, first-class: list all reels with inline video preview (served locally from the DB), **Make reel** (voice-server-aware; progress live), edit caption, **Post** (gated), Kill, remake with a suggestion box. Voice server start/stop from the UI. Search / status / kind / sort via the shared list control. |
| **Digs** | Persistent investigations: open (free or from watchlist), advance, promote, park, kill, add owner note, full timeline. |
| **Chief of staff** | Latest sweep: acted-autonomously list, reasoning, new digs; Run sweep now. |
| **Sources** | Performance table (runs→published/killed rates), active sources, the 33 candidates from sources.yaml (tier/role/lean), proposals approve/skip, manual RSS add. |
| **Ingest** | Paste URLs (+angle) → pipeline; quick topic submit; ingest + topic history. |
| **System** | Scheduled jobs (last-run + Run now signals), live agents, queue, quota breaker detail, voice server control, env sanity checks, bio-links manager (add/pin/delete), background-job history. |
| **Costs** | Today/month/all-time, daily bars (hand-rolled SVG), by-model, by-skill, published log. |

## API sketch

`/api/login` · `/api/overview` · `/api/system` (+`/signal`, `/voice`) ·
`/api/jobs[/<id>]` · `/api/runs` (+`/<id>`, `/<id>/approve|action|recheck|suggest`,
PATCH draft) · `/api/carousels` (+make, `/<id>/post|rebuild|kill`, PATCH caption,
PATCH `/slides/<pos>`) · `/api/reels` (+make, `/<id>/post|kill`, PATCH caption,
`/<id>.mp4` local Range stream) · `/api/bio` · `/api/digs` (+actions) ·
`/api/cos` · `/api/sources` (+actions) · `/api/ingest` · `/api/topics` ·
`/api/costs`.

Route modules: `api/system.py`, `api/runs.py`, `api/media.py`, `api/ops.py` —
new domains = new module + a nav entry in `app.js`'s view registry. That's the
extensibility contract.

## Browse: one list control on every content screen (added 2026-07-30)

At 123 runs / 18 carousels / 14 reels, finding a specific thing had become the slow
part. Stories had an ad-hoc status+search bar and no sort; Carousels and Reels had
nothing and were silently truncating at `limit=20`. Three screens, three answers.

**Server** — `api/util.py`: `list_query(request, sorts=…)` → a `ListQuery` that parses the
same five params (`q`, `status`, `sort`, `limit`, `offset`) for every list endpoint and
builds the WHERE / ORDER BY / LIMIT plus a matching `COUNT(*)`. Used by `/api/runs`,
`/api/carousels`, `/api/reels`, which all now return
`{…rows, total, limit, offset, sort, status, q}`.

- **`sort` is a whitelist lookup, never interpolation.** Each endpoint declares a
  `{key: sql}` dict; an unrecognised key falls back to the default, so request text
  cannot reach the ORDER BY.
- **Status filters by GROUP, not literal.** `pipeline_runs.status` carries legacy
  duplicate spellings from the engine's history — `hold` *and* `held`, `kill` *and*
  `killed`. Filtering on the literal the UI showed silently hid rows: "killed" returned
  16 of the actual 25. `RUN_STATUS_GROUPS` in `api/runs.py` is the one place that
  aliasing lives.
- Sort keys are near-identical by design: `newest`/`oldest` everywhere, `updated` on
  Stories (only `pipeline_runs` has `updated_at`), `posted` on Carousels + Reels
  (`posted_at DESC NULLS LAST` — works on both Postgres and the bundled SQLite 3.45).
- Reels also filter on **`kind`** (illustrated / narrated) — the one axis that actually
  separates reels.

**Frontend** — `listBar(view, opts)` in `app.js` returns `{node, foot, qs(), onChange,
setCount()}`. The bar owns the controls and the "Showing N of M" + Load more footer; the
view still owns fetching and card markup. Selection lives in **`state.list[view]`**, not
in the DOM, because nearly every action calls `route()` and rebuilds the view — without
that the screen snapped back to "all / newest" the moment you posted or killed something,
which was half the reason browsing hurt. A fourth list screen gets this by calling
`listBar`, not by inventing a fourth bar.

## Deployed-code touch (one, tiny)

`publishing/fileserver.py`: slide GET accepts `?fresh=1` → re-render from the DB
even if the cached file exists. Needed so a slide-headline edit actually changes
what Meta fetches. Idempotent, no data exposure. Everything else in this build
is local-only (Railway services never import `command_center/`).

## Launch / ops

- `command_center/run.sh` — mirrors the Streamlit launcher: pulls env from
  Railway each boot, double-launch guard on :8600, logs to
  `~/.jarvis/thelivu-command-center.log`.
- Autostart entry `~/.config/autostart/thelivu-command-center.desktop`.
- The Streamlit dashboard stays untouched on :8501 until Anil retires it —
  parallel running is safe (both are readers of the same DB + the same shared
  publish paths guard double-posts).

## Test plan

1. `py_compile` everything.
2. Scratch SQLite DB (`DB_PATH`) + fixtures: login, every GET, gate actions
   (kill/hold/requeue/recheck/edit), dig lifecycle, ingest, bio links, reel MP4
   Range serving, job lifecycle.
3. Prod smoke (read-only): boot with Railway env, `/api/overview` and
   `/api/carousels` return real data. No mutating calls against prod in tests.
