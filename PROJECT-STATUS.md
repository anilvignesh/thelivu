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

### Parked (not built — pick up post-20-posts)
- Marketing/reach push: **Reels generator** + repurpose one verified story to
  X/WhatsApp; a political-cartoon prototype (concept via LLM → image model → gate).
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
- Ripe next **dig** (on the watchlist): **Adani infrastructure, anchored on
  Vizhinjam.** Also: Aravalli degradation; El Niño/monsoon (verify the forecast first).

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
- **A dig:** "Run the Vizhinjam/Adani dig" (story-scout method).
- **A submitted topic:** just give it — topic-intake triages scope + worth first.
- Everything ends at the **human gate**. During validation, stop before publishing.
