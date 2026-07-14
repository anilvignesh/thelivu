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

## Where things stand

- **Engine: fully built.** Charter, 12 skills, source registry, investigative
  watchlist, two scripts (ingest, publish), all operating docs — in `engine/`.
- **Three article drafts**, all review-stage (nothing published):
  - `articles/drafts/thelivu-masala-bond-ENGINE.md` — user-sourced topic (KIIFB
    masala bonds / white paper), full pipeline.
  - `articles/drafts/thelivu-kerala-health-audit-ENGINE.md` — engine-discovered
    (CAG health audit + India's highest out-of-pocket costs).
  - `articles/drafts/thelivu-varkala-cliff-ENGINE.md` — engine-discovered (Varkala
    cliff / stayed Swadesh Darshan project), deliberately off the house frame.
- **Pushed to a private GitHub repo.**
- **Phase: pre-launch / validation.** Nothing automated. Nothing published.

---

## Decisions locked (don't silently reverse — see CONTEXT-AND-HISTORY for why)

Name **Thelivu**. Stance: **transparent perspective** (argue a view, openly; verify
facts, judge framing). **English.** **One** human-reviewed piece a day. **Kerala-first,
India-second, international as a lens** — distance from Kerala raises the bar. Sources
are leads; the open web verifies. Run **attended** on an M1 Mac via Claude Code under
a Pro plan; **no local LLMs**; automation deferred until after validation. **The human
gate is absolute.**

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
- Geographic tiers (Kerala core / national-by-hook / international-as-lens).
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
