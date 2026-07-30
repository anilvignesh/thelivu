# START HERE — Thelivu Operator Guide & Context Bootstrap

**Read this first.** This single file hands any fresh assistant — a new Claude
chat, Claude Code, Gemini, any capable model — the full context needed to run
Thelivu, without depending on the conversation that built it. Hand over this
folder (or paste this file + `CHARTER.md`), then trigger a cycle.

> For Claude Code: copy this file to `CLAUDE.md` at the project root so it loads
> automatically.

---

## 1. What Thelivu is

An explainer-and-accountability news operation that surfaces **important but
under-reported** stories — **Kerala first, India second** — verifies them against
the open web, and publishes short, sourced, perspective-driven pieces to a
Telegram channel. It is **human-gated**: a person reviews and approves every
piece before it goes out.

## 2. Current status (updated 2026-07-30)

**Live and automated, still human-gated.** This section described Phase-1 dry runs
("nothing is published, nothing is automated") long after both stopped being true —
if it looks stale again, trust `PROJECT-STATUS.md`, which is the living state.

- **~25 stories published**, self-hosted + on the bio page; carousels and reels posted
  to Instagram (`@thelivu.reports`).
- **The engine runs unattended on Railway** (`run.py` ticks ~2 min: RSS cycle,
  chief-of-staff, dig auto-advance, scouts). Postgres on Railway is the live DB.
- **Operations happen in the command centre**, not in a chat: `command_center/` on
  `:8600` (laptop, LAN, phone over Tailscale). The old Streamlit `dashboard.py` is
  **retired** as of 2026-07-30. See `docs/command-center-v2.md`.
- **Reels + carousels are built locally** on the owner's laptop (cloned voice + ffmpeg;
  Railway has no GPU) and stored in the DB for the fileserver to serve.
- **The human gate is unchanged and non-negotiable** — publishing and posting are the
  only gated actions, and nothing auto-publishes.

Phase-1 artifacts (`DRY-RUN-PLAYBOOK.md`, `dry-run-log.md`) are kept as history.

## 3. Locked decisions (Phase 0 — do not silently change)

- **Name:** Thelivu (see `BRAND.md`).
- **Stance:** *transparent perspective* — argues a view from the side of ordinary
  people and public goods, and says so. Not neutral; not disguised.
- **Language:** English.
- **Cadence:** one human-reviewed piece per day. Quality over quantity.
- **First source:** FYI by Creator House (Kerala). Full list in `sources.yaml`.
- **Models:** Claude for reasoning (investigate/verify/write/review); Gemini for video
  ingestion and some monitoring. Channels are *tips*; the open web is the substance.
  **Presentation-side skills only** (`carousel-composer`, `video-script`) run on free
  NVIDIA-hosted Gemma — they format an already-verified, already-approved story, so they
  never touch the trust gate. That split is the locked part: *never* move a judgment or
  verification step onto a cheaper model to save credit.
- **Hosting (superseded 2026-07-30):** the engine runs unattended on **Railway**;
  media rendering is local on the owner's **Pop!_OS laptop** (not the M1 Mac this
  originally said). Attended mode (`./attend`) still exists as the fallback for when the
  APIs are dry, and is human-operated only — never cron, Railway or `claude -p`.

## 4. The non-negotiables (compressed charter — full text in `CHARTER.md`)

1. **Nothing auto-publishes.** A human approves every piece. Final and mandatory.
2. **Under-coverage selects, never confirms.** Obscurity says "look," never
   "it's true." Obscure claims face a *higher* bar.
3. **One source proposes, the whole web disposes.** A claim's origin never counts
   toward its own verification. The tip channel never verifies its own tip.
4. **Three buckets, always:** Fact / Allegation / Inference. Inference is never
   laundered into fact.
5. **Build, don't re-voice.** Original synthesis from the verified record; credit
   the channel that surfaced the topic; never a reworded transcript.
6. **Verify facts, judge framing.** Verified facts don't verify an argument.
7. **Corrections are visible and fast.**

## 5. The pipeline

Topics enter from **three lead sources**, then all flow through one pipeline:

```
curated channels (ingest + news-monitor) ┐
open web + primary feeds (beat-monitor)  ├─→ investigate → verify (trust gate)
your own tips (topic-intake)             ┘      → [pattern-check] → write
                                                → review → ★ HUMAN GATE ★ → publish
```

Each stage is a skill in `skills/`, and each hands the next a defined artifact:
candidate queue → evidence dossier → verification report (KILL/HOLD/READY) →
draft → review verdict → (human) → post. Every lead, whatever its source, is
Tier 3 until the open web verifies it.

## 6. File map

- `START-HERE.md` — this file.
- `CONTEXT-AND-HISTORY.md` — the brief story of how this was built and *why* each
  rule exists. Read it before bending any rule.
- `CHARTER.md` — the constitution. Governs everything.
- `SYSTEM-DESIGN.md` — full architecture, trust score, infra, legal, risks, rollout.
- `DEPLOYMENT.md` — the phased checklist to go live (build AFTER validation).
- `README.md` — pipeline orchestration and how the stages chain.
- `BRAND.md` — name, tagline, about, footer, handles.
- `sources.yaml` — the editable source registry (what to ingest).
- `watchlist.yaml` — the investigative agenda: themes/actors to DIG into.
- `DRY-RUN-PLAYBOOK.md` — the validation-week routine and the gate to automate.
- `dry-run-log.md` — fill one row each morning.
- `examples/` — the same story done two ways (`...-original-op-ed-BEFORE.md` vs
  `...-ENGINE-output.md`): the clearest proof of what the engine is for.
- `skills/` — the twelve skills, by function:
  - **Lead sources (three ways a topic enters):** `source-ingestor/` (+ `scripts/ingest.py`)
    and `news-monitor/` for curated channels; `beat-monitor/` for the open web and
    primary feeds; `topic-intake/` for tips you (or, later, the public) bring in.
  - **Pipeline:** `news-investigator/`, `source-verifier/`
    (+ `references/trust-score.md`), `pattern-synthesizer/`, `article-writer/`,
    `editorial-reviewer/`, `publisher/` (+ `scripts/publish.py`).
  - **Discovery & maintenance:** `story-scout/` (the proactive *dig* — works the
    watchlist) and `source-scout/` (weekly new-source discovery).

## 7. How to run one daily cycle

Trigger phrase: **"Run today's Thelivu cycle on FYI"** (or another active source).
The assistant should, reading the skills and obeying the charter:

1. **monitor** — scan the source's recent items; pick ONE topic on impact ×
   under-coverage. The channel is only a tip.
2. **investigate** — rebuild that topic from the OPEN WEB (primary records,
   established news). Ignore the channel's framing. Also **map the related
   threads** (other statements, budget lines, history) as raw material for the
   pattern stage — gathered, not yet connected.
3. **verify** — run the trust gate (`source-verifier` + `references/trust-score.md`).
   Output KILL / HOLD / FRAMING-FIX / READY-FOR-HUMAN. Expect many HOLDs early.
   Each related thread is verified too before it can become a dot.
4. **pattern-check** — only on *verified* threads; evidence the link itself,
   classify it, name the weakest link, downgrade by default. Expect "not
   supported" often.
5. **write** — only if READY; transparent-perspective draft (`article-writer`).
6. **review** — `editorial-reviewer` flags framing, nuance, legal; assigns a
   confidence label.
7. **Hand the draft + verification report to the human.** During the validation
   week, STOP HERE — do not publish.

## 8. How to resume in a new chat or on another platform

1. Upload this whole folder (or, if you can't, paste `START-HERE.md` + `CHARTER.md`,
   then the specific `skills/*/SKILL.md` for the stage you're running).
2. Say: "You are running Thelivu. Read START-HERE and the charter, then run
   today's cycle on FYI."
3. The assistant has everything it needs. It does **not** need the original
   conversation — the operating context lives in these files, not in chat
   history. (Memory across chats, if available, is a bonus, not the mechanism.)

## 9. Open to-dos (parking lot)

- Check `@thelivu` handle availability (Telegram bot + channel).
- Verify the YouTube `channel_id`s in `sources.yaml` (only FYI's is confirmed).
- Get a media lawyer's read before going public (see `SYSTEM-DESIGN.md` §8).
- Decide the Instagram ingestion path (no RSS; Graph API or manual).
- Run the validation week; meet the gate in `DRY-RUN-PLAYBOOK.md` before automating.
- Then build: bot setup, RSS-notify, optional VPS/API for unattended runs.

---

*If you change a decision in §3 or a rule in §4, write it down here and in
`CHARTER.md`. The day a rule gets bent for a story too good to check is the day
Thelivu becomes the thing it was built to replace.*
