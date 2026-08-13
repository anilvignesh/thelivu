# Thelivu — build plans for the next sessions (written by Fable, 2026-07-26)

Implementation-ready plans for an Opus 4.8 session to execute. Each plan is a
step-2 context file in Anil's 5-step workflow (understand → context md → build
→ compare → test). The planning context (audits, measurements, gotchas) is
baked in so you don't have to re-derive it.

## Before touching anything

1. Read `docs/HANDOFF.md` (operational layer + gotchas — §5 saves you real
   debugging time) and `PROJECT-STATUS.md` (current state).
2. Invariants that are never up for debate: **publishing/posting is the only
   human-gated action** (no bypass flag, do not add one); **never run an LLM
   over an approved draft**; **journalism runs on Claude/Gemini only** (free
   NVIDIA Gemma is presentation-only); **`engine/attend.py` is never
   automated**; `git push` deploys to Railway (~2-3 min; verify commit hash on
   the deployment, not just SUCCESS).
3. Test discipline: scratch SQLite via `DB_PATH=<file>` env (shared/db.py is
   dual-dialect), `venv/bin/python -m py_compile` before committing, exercise
   the real flow before claiming done. The command center's regression pattern
   is in git history (curl loops against a scratch server on :8611).

## The plans, in order

| # | Plan | Why this order |
|---|---|---|
| 1 | [01-budget-governor-haiku-routing.md](01-budget-governor-haiku-routing.md) | Makes the ~$10 of API credit last ~2+ weeks of autonomous operation. Do this BEFORE loading credit. |
| 2 | [02-illustrated-reel-pipeline.md](02-illustrated-reel-pipeline.md) | The reach surface. Prototype + style assets rescued into `docs/plans/reel-prototype/` — they only existed in a /tmp scratchpad before. |
| 5 | [05-technical-steward.md](05-technical-steward.md) | A periodic agent that keeps model routing apt, watches Claude/Gemini/NVIDIA for new offerings + price changes, and keeps cost managed. Depends on plan 01 (shared cost model + budget governor). Build after 01 lands. |
| 3 | [03-brand-consolidation.md](03-brand-consolidation.md) | Small; folds the 2026-07-26 brand locks into BRAND.md. |
| 4 | [04-streamlit-retirement.md](04-streamlit-retirement.md) | Only after the command center has proven itself for ~a week. |
| 6 | [06-reel-autonomy.md](06-reel-autonomy.md) | Added 2026-08-12. Auto-triggers reel builds on publish and moves the render off Anil's laptop onto an always-on Oracle VM. Independent of 01-05; written after the command center + illustrated reels already existed. |

Suggested execution order: **01 → 05 → 02 → 03 → 04**. Plan 05 is the "technical
manager" Anil asked for — it rests on the cost model and env-overridable model
knobs that plan 01 introduces, so 01 first.

Editorial work that is NOT a code plan: the ~14 RECHECK backlog
(`docs/gate-triage-2026-07-26.md` has per-item reframe notes) and the 19
`needs_attention` runs from the Jul-21 outage era (several superseded by the
staged refreshes — triage, don't mass-kill).

## Money facts these plans rest on (measured 2026-07-26, 30-day window)

- Engine spend ≈ **$34/mo**, of which ≈ **$20/mo is triage** (news-monitor
  $10.65, topic-intake $5.29, chief-of-staff $4.27, newsworthiness-gate $0.20)
  and only ≈ $5.4 is the writing core (article-writer, editorial-reviewer,
  pattern-synthesizer). Gemini research+verification ≈ $2.
- Prices per MTok (verified against current API docs): Haiku 4.5 $1/$5 ·
  Sonnet 4.6 $3/$15 · **Sonnet 5 intro $2/$10 through 2026-08-31** (then $3/$15
  with a tokenizer that uses ~30% more tokens — net ≈13% cheaper than 4.6 until
  Sept, ~30% dearer after; revisit then) · Opus 4.8 $5/$25.
- Presentation (carousel compose, reel scripts) is free NVIDIA Gemma; reel
  voice/render is local; publishing is non-model. Credit buys stories, nothing
  else.
