# Thelivu — Project Status & Continuation Guide

*Read this to pick up the project where the build session left off. It's the living
state of the work — update it as you go. For how the engine runs, see
`engine/START-HERE.md`; for why each rule exists, see `engine/CONTEXT-AND-HISTORY.md`.*

---

## How to continue in Claude Code (or a fresh chat)

A new assistant will **not** have the conversation that built this — it starts cold.
But the files were written to carry the operating context, so it doesn't need the
chat. To bootstrap it:

1. In Claude Code: open this repo and copy `engine/START-HERE.md` to **`CLAUDE.md`**
   at the repo root, so Claude Code auto-loads it. (Or just tell it to read the file.)
   Then read **`docs/HANDOFF.md`** — the operational layer: deployed topology,
   Railway/DB access, and the gotchas that cost real debugging time.
2. Say: *"You are continuing Thelivu. Read CLAUDE.md (START-HERE),
   engine/CONTEXT-AND-HISTORY.md, and PROJECT-STATUS.md, then [your task]."*
3. It now has the charter, the method, the history, and the state below. The only
   thing it lacks is the verbal reasoning of the original session — summarised here.

---

## Reel pacing + command-centre browse (2026-07-30)

Six changes, all on `main`. Four of them are bug fixes to things that looked finished.

**The reel's visual pacing was broken twice over.**

1. **The Ken-Burns push stalled.** `zoompan`'s increment was a constant `0.0006`/frame
   against a constant `1.08` ceiling, so it exhausted itself after 133 frames = **4.44s
   at 30fps**. Speech beats run 6-12s, so every beat drifted for 4.4s and then held a
   pixel-identical frame. Measured: 2.2 mean pixel change per half-second while moving,
   **0.001** after the ceiling — stopped, not slowed. Reel #14 was frozen for 51% of its
   runtime, #13 for 45%, #17 for 55%. Worse, it read as a glitch rather than a look,
   because the stall keys off an absolute 4.4s: #13's 2.9s and 4.1s beats never froze
   while its 12.5s beat froze for 8s. `_zoom_expr()` now derives the increment from the
   beat's own frame count. `ZOOM_MAX` (1.08) is the one knob.
2. **One picture per ~9 seconds.** Reel #14 is 110 words — *inside* the skill's 110-135
   spec, so the model obeyed; the spec's own arithmetic is the problem. 110-135 words at
   the measured 147wpm is 45-55s over the specified 5-6 frames = 8-11s per still.
   `build_reel` now takes **`shots_per_beat`** and subdivides a long beat's *video* into
   2-3 sub-shots, each with its own illustration (`TARGET_SHOT_SECS = 4.0`,
   `MAX_SHOTS_PER_BEAT = 3`). The audio is built and concatenated separately, so **the
   narration is byte-identical and nothing is re-verified.** That was the deciding
   factor: compression is where reel #12 upgraded a tabled Bill to "won", so buying
   pacing by shortening spoken lines would trade verification quality for retention.
   - `_split_duration` makes sub-shots sum to EXACTLY the beat duration — per-part
     rounding drifts against a continuous VO and accumulates over 6 beats.
   - `generate_beat_images` had ONE fixed seed for every scene. Harmless when each beat
     had a distinct prompt, fatal once sub-shots reuse the beat's scene: a shared seed
     renders them identically and the cut becomes a stutter. Seed is now per-scene.
   - Text-slide reels are **never** split (nothing varies per sub-shot → the cut would
     restart the zoom on the same frame); the illustration fallback resets the plan.
   - The silent sign-off card is one shot, never cut. Progress dots still count beats.

**The hook was specified but never enforced.** `_gen_script_nvidia` returned its output
regardless of whether the retry worked, and the only downstream check was `if not beats`
— which passes, because BEAT 1..n *are* beats. A hookless script therefore rendered a
reel opening mid-story, silently, after a ~15-minute render. Separately, `parse_script`'s
`^LABEL:\s*(.+)$` used `\s`, which matches newlines: a bare `HOOK:` **stole BEAT 1's
sentence** (and spoke BEAT 1 twice), a bare `CLOSE:` stole the HASHTAGS line, a bare
`BEAT n:` swallowed its own caption. Horizontal whitespace only now. `parse_script`
returns `hook`, and ONE predicate (`_has_hook`) guards the nvidia generator,
`run_structured_skill`'s marker, and a post-parse check, so no mode can drift weaker.

**NVIDIA calls had no transient retry** — a single 500 killed a whole reel build. Now
`shared/nvidia.py::call_with_retry`, used by all three call sites (video-script,
FLUX illustrations, `skill_runner._run_nvidia`). Retries 5xx/timeouts, **fails fast on
4xx**, never touches the quota breaker (NVIDIA has its own key). Most important on the
illustration path: ~12 FLUX calls per reel now, and all-or-nothing fallback meant one
blip cost the whole illustrated look.

**Command centre browse.** Stories/Carousels/Reels share ONE control — see
`docs/command-center-v2.md`. Includes a real filter fix: `pipeline_runs.status` carries
legacy duplicate spellings (`hold`+`held`, `kill`+`killed`), so filtering the literal hid
rows — "killed" showed 16 of the actual 25.

**Reel remake takes suggestions.** A textarea on Remake, stored on `reels.notes`,
prefilled into the next remake, injected into the script prompt inside a block that
restates that the hard rules outrank every note — the reel is post-gate, so nothing
re-verifies it after the Post tap. See `docs/reel-button.md`.

**Also:** the Streamlit dashboard is retired (killed + autostart moved to
`~/.config/autostart-retired/`; code left in place, not back-ported). The
**Vizhinjam/Adani dig is dropped** — watchlist theme removed, `/dig` with no argument now
lets the scout pick the ripest theme, and story-scout's worked examples were *replaced*
(not deleted) with live-watchlist equivalents so the skill keeps teaching
condition-vs-event, question-vs-conclusion and what a Kerala anchor is.

## Illustrated reels (productionized 2026-07-26 — plan 02)

`make_narrated_reel()` now produces the **ink-dark illustrated** reel (the reel #9
look) by default, end to end from the CC's "Make reel" button. This was a
scratchpad prototype that built one published reel by monkeypatching
`reel._render_frame`; it is now real code.

- `publishing/illustrate.py` — one conceptual illustration per beat via
  **FLUX.1-dev on the free NVIDIA key**. Serial (14 GB box), dark-ground house
  style, and it defends against the two known failure shapes: the NIM safety
  filter returning a black frame with `finishReason=CONTENT_FILTERED` (checked)
  and sub-50KB blanks (rejected). Journalism vocabulary that trips the filter
  ('somber', 'grave', 'victim'…) is softened **in the image prompt only** — never
  in the story.
- `publishing/reel_illustrated.py` — the frame builders and the sign-off card,
  ported verbatim in geometry from the prototype.
- **`reel.build_reel` takes a `render_frame`**, and `_synth` treats an empty beat
  as a deliberate **silent hold** — that's how the sign-off card gets its ~2.8s
  with no speech over it. No monkeypatching anywhere.
- The **video-script skill now emits an `IMAGE:` line per beat** (`HOOK_IMAGE`,
  `BEAT n IMAGE`, `CLOSE_IMAGE`) — a conceptual scene, with the non-photoreal
  rule stated as a brand rule. `parse_script` returns `images` aligned with
  `beats`; older scripts without them fall back to a scene derived from the
  caption.
- **All-or-nothing fallback:** if any beat's illustration fails, the whole reel
  renders as text slides. A reel mixing both looks like a bug, not a style.
  Stored `kind` is `illustrated` or `narrated`, shown on the CC reel card.

## Cost control (added 2026-07-26 — plan 01)

The engine now runs to a budget instead of running until the balance dies.

- **One cost model: `shared/costs.py`.** The USD-per-MTok table used to be
  triplicated (orchestrator report, Streamlit, command center) and had already
  diverged — gemini-pro output was priced at $5 in one place and $10 in the
  others, and neither the report nor the dashboard knew NVIDIA Gemma is free,
  so free presentation calls were billed at Claude rates. All three import from
  here now. `cost_usd()` resolves a raw model string to a tier; `RATES` is the
  introspectable table.
- **Triage runs on Haiku 4.5.** `_HAIKU_SKILLS` in `engine/agents/skill_runner.py`
  = `news-monitor`, `topic-intake`, `chief-of-staff`, `newsworthiness-gate` —
  measured 2026-07-26 as ~$20 of the ~$34/mo burn, against ~$5.4 for the writing
  core. They sift against a strict output contract; they don't write prose and
  don't touch the trust gate. **The trust-critical chain stays on `CLAUDE_MODEL`**
  (article-writer, editorial-reviewer, pattern-synthesizer, meta-synthesizer,
  source-ingestor) and research stays on Gemini. `record_usage` logs the model
  actually called, so cost accounting stays truthful.
  *Watch after the first cycles with credit:* news-monitor has a selection
  contract; if `_resolve_selected_lead` starts logging "throughline unmatched",
  revert just news-monitor to `CLAUDE_MODEL` and leave the other three.
- **Budget governor: `shared/budget.py` + the block in `run.py`.** Daily spend
  cap (default **$0.75**, kv `daily_budget_usd`, 0 disables). Sits *below* the
  quota breaker and *above* every model stage — so at the cap, model work parks
  but publishing, approvals and cleanup keep working. Self-expiring: spend is
  only ever counted for the current UTC day, so midnight releases it. One
  Telegram alert the first time it trips each day.
- **Controls:** command center System view (cap + today's spend + setter),
  Overview banner in gold when parked (it's healthy behavior, not an outage),
  `POST /api/system/budget`, and `/setbudget <usd>` in the bot.
- **Model knobs are env-overridable** (`THELIVU_CLAUDE_MODEL`,
  `THELIVU_HAIKU_MODEL`, `THELIVU_GEMINI_MODEL`) so a routing change is a
  Railway variable, not a code push.
- **Owner decision 2026-07-26:** stay on **Sonnet 4.6** for the writing core.
  Sonnet 5's intro pricing ($2/$10 to 2026-08-31) is offset by a tokenizer that
  uses ~30% more tokens, and it goes ~30% dearer after. Revisit 2026-09-01.

## Tech steward (added 2026-07-26 — plan 05)

The technical counterpart to the chief-of-staff: a **weekly advisory sweep** that
keeps the model stack apt instead of letting it drift until something 404s or a
price moves under us. `run_tech_steward()` builds a telemetry snapshot (30-day
spend by skill × model, the full routing table, the rate table we assume, budget
and breaker state), then searches the live Anthropic / Google / NVIDIA catalogues
and emits a ranked `RECOMMENDATIONS` block — each with `from` → `to`, a risk
rating and an estimated monthly saving.

- **Advisory only.** It never switches a model, never spends. Applying is one
  env var (`railway variable set THELIVU_CLAUDE_MODEL=… --service thelivu-agent`),
  so reverting is too. Never recommends moving journalism off Claude/Gemini.
- Routed to **Gemini + Google Search** — it's a search-heavy scan of pricing
  pages, and it's ops, not journalism, so the charter has no stake in it.
- Weekly in the tick (stamped before running, per the retry-storm rule) plus a
  `force_tech_steward` signal; CC System view shows the last sweep, a Run-now
  button, the recommendation cards and the full brief.

## Command Center v2 (added 2026-07-26 — the operations base)

**The Streamlit dashboard has a successor: `command_center/`** — a proper web app
(Starlette + uvicorn, hand-rolled SPA, zero new deps) that is now the intended main
operations surface. Spec: `docs/command-center-v2.md` (read it before extending).

- **Run:** `command_center/run.sh` (autostarts via
  `~/.config/autostart/thelivu-command-center.desktop`) → **http://localhost:8600**,
  phone via Tailscale `100.70.158.55:8600`. Password gate (`DASHBOARD_PASSWORD`).
- **11 views:** Overview · Gate · Stories · Carousels · Reels · Digs · Chief of
  staff · Sources · Ingest · System · Costs. Everything the Streamlit app did,
  plus: inline draft editing (human edit), AI suggestions (quota-aware,
  editorial-reviewer, pre-approval only), slide-headline editing (re-renders the
  hosted image via the fileserver's new `?fresh=1`), reel previews streamed
  locally, make/post reels and carousels as background jobs with live progress,
  voice-server start/stop, breaker status + clear, bio-links manager, signal
  triggers for every scheduled job.
- **Gate unchanged:** approve/post go through the ONE shared
  `publishing.publish` paths behind explicit confirm modals. No bypass.
- **Perf discipline (hard-won, same day):** round trips to Railway dominate —
  the CC pools connections (autocommit, dials outside the lock — see
  `command_center/db.py` docstring), batches kv reads, and fans out independent
  queries with `db.parallel`. Endpoints run 0.2–0.7s warm; a naive port ran 40s.
- The Streamlit `dashboard.py` still autostarts on :8501 — retire it once the CC
  has proven itself for a few days.

## Where things stand (updated 2026-07-20 — the "command center" era)

**Live and running in production.** Deployed on Railway, publishing daily, with a
full command-center control surface. The pre-launch snapshot below this line is
historical — this is current.

- **Deployed** on Railway project `brave-determination`: `thelivu-agent` (orchestrator
  2-min tick + public web server), `thelivu` (Telegram bot / human gate), `Postgres`.
  Auto-deploys from GitHub `main` (`anilvignesh/thelivu`). See `docs/HANDOFF.md` for
  topology, CLI, and gotchas — **read it before touching prod.**
- **~10 articles published** to the Telegram channel `@thelivu_reports`, self-hosted
  at `/a/<slug>`; **5 Instagram carousels posted** (account `thelivu.reports`).
  Numbers decay — query the DB, don't trust these.
- **20 skills** in `engine/skills/` (was 12): added `chief-of-staff`, `video-script`
  (video-script is scaffolded, NOT wired — see `docs/video-reels-research.md`), and
  the dig/tracker/ingestor family.
- **The command center** (`dashboard.py`) — a 10-tab Streamlit control panel run
  locally against the prod DB (over Tailscale for phone access). Overview · Ingest ·
  Drafts · Pipeline · Carousels · Digs · Follow-ups · Sources · Tasks · Costs.
- **Owner autonomy grant (2026-07-15):** the assistant acts autonomously on
  everything — features, story work, backend, digs — and the **only** action gated on
  the owner is the **final publish/post**. Enforced in code (no bypass flag).

### Capabilities added this era (all deployed, all end at the human gate)
1. **Persistent digs** — a thread investigated over multiple days. Tables `digs` +
   `dig_updates`; `run_dig_advance()` / `promote_dig()` in the orchestrator; daily
   auto-advance of due digs; kv signals `advance_dig_id` / `promote_dig_id`. The E20
   dig (#2) went scoping→verifying→ready-to-write autonomously.
2. **Link ingestion** — paste an article/YouTube URL; `ingestion/fetch.py` fetches
   readable text (requests+lxml, ISP-retry), `queue_ingest()` → `pending_topics`
   (source=`ingest`), and `_run_topic_intake` enriches the URL before triaging.
3. **Chief of staff** — `run_chief_of_staff()` autonomously sweeps the neglected
   backlog (held / stale-at-gate / dropped digs), checks the web for "what moved,"
   and **executes** recheck/requeue/kill/open-dig (capped 8/sweep) + opens new dig
   threads. Daily + `run_chief_of_staff` kv signal. Parser tolerates truncated blocks.
4. **Held-run loop closed** — held / needs_attention runs are readable + actionable
   from the dashboard AND Telegram: `recheck_run(note=…)` takes **owner editorial
   direction** (what to search / how to frame; **links are fetched + verified**) via
   kv `recheck_note_<id>`. `/recheck <id> <direction>` on the bot. Steers framing;
   never overrides the trust gate.
5. **Cost controls (quality-neutral)** — `_run_claude` caps the web-search tool loop
   at 6 rounds then forces a final answer (a runaway loop was ~95% of spend), plus
   prompt-caches the growing context. Gemini content-blocks now fall back to
   Claude+web-search instead of dying empty (was the "Gemini returns empty" bug).
6. **Robust Instagram + carousels** — `publishing/publish.py` holds the ONE shared
   `publish_run()` (article) and `post_carousel_run()` (carousel) both the bot and
   dashboard call (no drift). Slides render **on demand from the DB** in the
   fileserver (survive redeploys/cleanup — `dark`/`stamp` persisted on
   `carousel_runs`). IG calls retry transient errors + empty responses.
7. **Reposition** — global scope, Kerala emphasis, NOT Kerala-first (see Decisions).
8. **Reach** — story-specific + evergreen hashtags on carousels; slide count sized
   for engagement + full explanation (8–10, ceiling 10).
9. **Attended mode + the quota breaker (2026-07-22)** — the answer to "the APIs ran
   out." No cross-engine fallback; work parks, Anil runs the cycle by hand at the
   terminal. See `docs/attended-mode.md`. Details below.

### Attended mode — added 2026-07-22

On 2026-07-21 **both** providers ran dry within hours of each other (Anthropic
balance exhausted; Gemini AI Studio prepay credits depleted). The tick loop then
spent **22 hours** crashing on a 429 every 2 minutes, producing nothing, while RSS
kept queueing leads into a dead pipeline (1,504 of them by the 22nd).

Three things came out of it:

- **The Claude→Gemini auto-fallback (`9b3202f`) is REVERTED.** It contradicted an
  invariant the code already held (`_pause_run`: *"never run on a substitute
  engine"*). Silently moving the **trust gate** onto a cheaper model is exactly the
  quality drift the charter exists to prevent — cheaper output on the gates is not a
  neutral cost saving. Owner's call, and the right one.
- **A quota circuit breaker** (`shared/quota.py`). A *hard* failure (out of credit,
  quota exhausted, bad key) opens it for 60 minutes and the tick skips every model
  stage; a *transient* failure (overload/500/timeout) does not — those still pause +
  requeue per-run. It auto-expires, so a top-up or a midnight reset recovers with no
  manual switch. Work that needs no model — **approve, publish, post a carousel**,
  cleanup, the bio/article pages — deliberately sits ABOVE the breaker and keeps
  running. Losing the API must never take the publishing surface down.
- **Attended mode** (`engine/attend.py`, `./attend`). Runs the *real* orchestrator
  with only the model call replaced: each skill writes its prompt to
  `.attend/NNN-<skill>.request.md` and blocks until the assistant in Anil's
  interactive Claude Code session writes the `.response.md`. Zero pipeline
  duplication — trust gate, anti-monotony, parsing and the human gate are untouched.

  **⚠️ It is a human-operated tool and must never be automated** — not from cron,
  not from Railway, not via `claude -p`. A subscription driven by a human doing
  their own work is legitimate; a subscription wired up as an unattended API
  replacement is not. The blocking wait *is* the boundary. See
  `docs/attended-mode.md`.

Also fixed: `_last_rss_run` was only stamped on **success**, so a failing cycle
stayed permanently "due" and retried every 2 minutes. That was the actual engine of
the 22-hour loop. It now stamps on failure too, with a 30-minute backoff.

### Reels wired into the command center — added 2026-07-25
The "reels built but not wired in" gap is closed. A **Reels row on every carousel
card** builds + posts a narrated reel (Anil's cloned voice) of the same story:
🎬 Make reel (create + preview) → 📤 Post reel (the gated tap). `save_reel` finally
has a caller — `publishing/make_reel.py` — shared by the dashboard and `./attend reel`.
**Reels are attended-only for now** (`config.REEL_MODE='attended'`): the script step
never touches the API — the dashboard button hands you `./attend reel <run_id>`, which
renders locally (voice + ffmpeg) and stores it `ready` for preview + post. The **API
route is kept but inactive** (flip `THELIVU_REEL_MODE=api`), owner's call. First one
built this way: reel #3 (Varkala cliff, run 111). Full detail: `docs/reel-button.md`.
**Next visual upgrade under discussion:** replace pure text-slides with AI-generated
images / editorial cartoons per beat (see `docs/video-reels-research.md`).

### Parked (not built — pick up post-20-posts)
- Marketing/reach push: repurpose one verified story to X/WhatsApp; a political-cartoon
  prototype (concept via LLM → image model → gate).
- **Kiln** (`~/kiln`, separate repo) — a generator that turns this framework into
  clone-and-deploy Instagram content engines for any niche. Spec written; for Anil's
  wife + her brother. See `~/kiln/docs/kiln-spec.md`.

---

## Historical: pre-launch snapshot (2026-07, superseded above)

- **Engine: fully built.** Charter, 12 skills, source registry, investigative
  watchlist, two scripts (ingest, publish), all operating docs — in `engine/`.
- **Three article drafts**, all review-stage; **pushed to a private GitHub repo.**
- **Phase then: pre-launch / validation.** (Now live — see above.)

---

## Decisions locked (don't silently reverse — see CONTEXT-AND-HISTORY for why)

Name **Thelivu**. Stance: **transparent perspective** (argue a view, openly; verify
facts, judge framing). **English.** **One** human-reviewed piece a day. **Global in
scope, with a working emphasis on uncovering Kerala** (where much of the audience is)
— **never Kerala-limited**; national and international stories are fully in scope.
Emphasis is a sourcing priority, not a public frame — we do **not** brand as
"Kerala-first." *(Repositioned 2026-07-16 from the original "Kerala-first,
India-second, international as a lens; distance raises the bar" — owner's call:
open to stories from around the world, Kerala emphasised for the audience, not a
limit.)* Sources
are leads; the open web verifies. **The human gate is absolute** (only the final
publish/post is gated; everything else is autonomous per the 2026-07-15 grant).
*(Superseded: the original "run attended on an M1 Mac, no local LLMs, automation
deferred" is history — the engine now runs unattended on Railway with the human gate
as the one control. The dev machine is Anil's Pop!_OS laptop.)*

---

## The spine — the thing that must not drift

This is a **verification engine with a human gate**, not a content mill or a partisan
line. Its value was proven repeatedly in the build session — it caught compelling-but-
false claims again and again:

- a chartered flight falsely attributed to Adani (allegation, not fact);
- a health minister "endorsing privatisation" who had actually said the opposite;
- private-equity firms "funding the Congress campaign" — unsupported;
- loan write-offs "for the Modis/Ambanis/Adanis" — write-off ≠ waiver, identities
  legally shielded, named-tycoon framing unverifiable;
- "Adani & Ambani are the biggest RSS/BJP backers" — corrected: Reliance *was* a top
  disclosed BJP donor (~₹545cr), Adani was not, RSS funding is opaque;
- a privatisation "plan" the evidence supported only as a "direction."

Each was downgraded, attributed, or dropped. **Preserve this reflex above all else.**

---

## Recent build additions (the latest state)

- Trust-score gate (categorical KILL / HOLD / READY) in the verifier.
- Article-writer (transparent perspective); publisher with the human gate enforced
  in code (no bypass flag, on purpose).
- Context-gathering step in the investigator + a tightened pattern-synthesizer
  (evidence the link, name the weakest link, downgrade by default).
- A **self-similarity / anti-monotony check** in the editorial-reviewer — added
  because two early pieces both landed on "fiscal stress → privatisation."
- Geographic emphasis (Kerala prioritised for the audience; national + international
  fully in scope — not just "as a lens"). Repositioned 2026-07-16; see Decisions.
- The **dig**: `story-scout` + `watchlist.yaml` — proactive, hypothesis-driven
  investigation from primary records, to *unearth* stories rather than wait.
- Public-tips discipline in `topic-intake` (tips are leads; protect sources; guard
  against weaponisation) — for when a public tip line opens (Phase 2).
- **Bio page** (the "link in bio" the slides promise): self-hosted at the slide
  server's `/` and `/bio`, auto-updated on every publish, managed via
  `/links`, `/addlink`, `/dellink`, `/pinlink` in the bot. See `docs/bio-page.md`.
- **Self-hosted article pages** at `/a/<run_id>-<headline-slug>` on the same
  domain — Telegraph is out of the article publish path (Telegram-owned domains
  are blocked/flaky on Indian ISPs; t.me doesn't even resolve on Anil's
  connection). Rendered per request from `pipeline_runs.draft_text`; only
  `status='published'` is served, so the human gate holds in the web path too.
  See `docs/article-hosting.md`.

---

## Open threads / next steps

**Editorial:**
- Run the **validation week** (`engine/DRY-RUN-PLAYBOOK.md`): review only, fill
  `engine/dry-run-log.md`, encode each miss as a rule.
- Ripe next **dig** (on the watchlist): Aravalli degradation; El Niño/monsoon (verify
  the forecast first).

**Your to-dos (not the engine's):**
- Check `@thelivu` handle availability (Telegram bot + channel).
- Verify the YouTube `channel_id`s in `engine/sources.yaml` (only FYI's is confirmed).
- Get a media lawyer's read before going public (defamation, IT Rules 2021, AI labelling).
- Decide the Instagram ingestion path (no RSS; Graph API or manual).
- ~~Push to GitHub~~ ✅ done.

**Deferred to post-validation (Phase 2+):** automation + API keys + hosting; the
public tip line. See `engine/DEPLOYMENT.md`.

---

## Quick reference — how to run things

- **Daily cycle:** "Run today's Thelivu cycle on FYI."
- **A dig:** "Run a dig on <watchlist theme>" (story-scout method), or `/dig` with no
  argument to let the scout pick the ripest theme itself.
- **A submitted topic:** just give it — topic-intake triages scope + worth first.
- Everything ends at the **human gate**. During validation, stop before publishing.
