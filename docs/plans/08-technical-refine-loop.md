# Plan 08 — Technical refine loop (research, investigation, production)

**Scope, Anil's own words (2026-09-14): "editorial will always stay with me,
the technical side, the research, investigation and production is where we
need the improvement."** This plan is the technical/research/production half
of self-improvement only. It never touches story selection, verification,
or what gets published — those stay exactly as human-judged as they are today
(see `engine/agents/learning.py`'s own hard rule, repeated in three modules:
advisory-only, never touches judgment).

Depends on nothing structurally, but reuses plan 05's pattern directly — read
`docs/plans/05-technical-steward.md` and `engine/agents/orchestrator.py`'s
`run_tech_steward()` before writing anything. This plan generalizes that
pattern rather than inventing a new one.

## Before touching anything

Same invariants as every other plan (`docs/plans/README.md`), plus one this
plan must not weaken: **the editorial autopublish decision (2026-08-29,
`PROJECT-STATUS.md` "Autonomy narrowed further") is a different axis from
this plan and is not being revisited.** That decision is about whether a
*story* needs a human tap before it posts (no). This plan is about whether
the *system's own code/config/skills* need a human tap before they change —
and the existing precedent for that (`tech-steward`, built and live) says
yes, propose-and-surface, not auto-apply. This plan keeps that asymmetry on
purpose: content moves fast, the system that produces it changes on a human
tap.

## Step 0 — close a live gap, independent of everything else below

`engine/agents/tools.py`'s `CREATE_SKILL_TOOL` is wired into the always-on
orchestrator loop (`execute_tool` → `create_skill()`), writes straight to
`engine/skills/<name>/SKILL.md` with **no git commit, no review, no
rollback**, and its own description scopes it to *"a clear, reusable
**editorial** pattern"* — directly contradicting the boundary above; it is
also live in an unattended loop, not a human-driven Claude Code session.

Fix, before anything else in this plan:
1. Narrow `CREATE_SKILL_TOOL`'s description to non-editorial (technical/
   production) skills only, matching the allow-list in "Scope" below — or
   remove it from the always-on orchestrator's tool list entirely and make
   skill creation something only a human-driven session does (git commits
   already show this is how every real skill edit has happened so far).
2. Whichever way it's kept, it must write through the same propose-and-surface
   path as everything else in this plan, not straight to disk.

## The mechanism — generalize `tech-steward`, don't reinvent

`tech-steward` already does exactly the shape this plan needs, just scoped to
cost/model routing: gather evidence → one skill call → `RECOMMENDATIONS [...]`
JSON (`action`, `why`, `risk`, est. impact) → `kv_set` → surfaced in
`command_center/api/system.py` (`steward.recs`) both as JSON for the dashboard
and as `_steward_paste()` plain text — "copy this into a working session."
Nothing auto-applies. A human starts the fix session by pasting the brief.

Generalize this into a second, parallel proposer — same shape, different
inputs and scope:

### 1. Evidence sources (already exist, currently only alert)

- `api_health.py` / `model_health.py` / `illustration_health.py` — repeated
  failures already logged to `model_health_checks` (shared.db). Currently:
  alert only. Add: when the same check fails N times inside a window (mirror
  `learning.py`'s `MIN_EFFECTIVE_N` idea — don't act on a single blip),
  that's evidence.
- Digger pipeline (`engine/digger/prefilter.py`, `review.py`) — noise
  patterns, `differ`-flag bugs, extraction failures. `prefilter.py`'s own
  docstring is literally "written against real output rather than a guess
  about it" — this plan turns that manual review habit into a standing
  input instead of something that only happens when Anil notices.
- Production/render failures — reel_worker retries, kinetic-render fallback
  triggers, any place a fallback silently absorbs a failure the way the
  Cloudflare `seed`-param bug did for 3+ days before `illustration_health.py`
  existed to catch it.

### 2. The proposer (new skill: `engine/skills/tech-refiner/SKILL.md`)

Mirror `tech-steward/SKILL.md`'s shape. Input: the evidence above, plus (for a
skill-file recommendation) the current `SKILL.md` content via `read_skill`.
Output: same `RECOMMENDATIONS` block shape, `area` extended with
`digger|production|health|skill-edit`, plus for `skill-edit` a **unified
diff**, not a rewrite — matches how every real skill edit so far has actually
looked in git history (small, targeted: *"long-form: give it search, because
it was told to cite what it could not find"*).

### 3. Fence — allow-list vs deny-list

Same enforcement point as `create_skill`'s fix in Step 0.

**In scope (technical/research/production):** `tech-steward`, `source-
ingestor`, `source-scout` (the *mechanics* of vetting, not which sources to
trust editorially), digger modules (`prefilter`, `review`, `routing`,
`extract`, `fetch`), production/rendering (`reel_worker`, `illustrate`,
`longform_render`, `reel_kinetic`), health-check modules, `reel-fact-check`
(mechanical figure-matching, not judgment).

**Out of scope, hard deny:** `article-writer`, `editorial-reviewer`,
`newsworthiness-gate`, `source-verifier`, `pattern-synthesizer`,
`meta-synthesizer`, `story-scout`, `news-monitor`, `chief-of-staff`,
`premise-check` and anything in the belief-desk verification path. These
decide *what's true* or *what's worth covering* — editorial, stays manual,
no exceptions.

### 4. Surfacing and approval

Reuse `command_center/api/system.py`'s pattern exactly: `kv_set
latest_tech_refine_recs`, a new dashboard section next to `steward`, same
paste-to-start-a-session convention. Telegram heads-up on a new proposal,
same as `_notify_card`. **Approval = you start the session and apply the
diff yourself** (or say "apply #2" to whichever session is live) — same
motion as today's tech-steward recs, no new UI to build.

### 5. Landing new capability — Tier-0 discipline

`docs/plans/07-tier0-digger.md` set the right precedent for adding new
automated capability: land in an isolated table (`digger_candidates`) first,
promotion into the live pipeline happens later, under review, on its own
step. Apply the same discipline here — a new fetch primitive or health check
proves itself against its own log/table for a while before anything reads it
automatically into a refine proposal.

## Digger additions — the research/investigation half

From the Agent-Reach review (2026-09-14): most of it is cookie-based account
scraping of X/Reddit/IG/FB, which `engine/social_desk.py`'s own docstring
already rules out by name ("never account-scrapes X/Reddit/IG, never stores
credentials") — **not adopting that part**, it's a policy line already drawn
on purpose, not a technical gap.

The zero-config, non-account subset is genuinely additive to
`engine/digger/fetch.py` and `source-ingestor`, and fits this plan's scope
(research/investigation mechanics, not what to investigate):

| Addition | What it gives the digger | Landing point |
|---|---|---|
| Jina Reader (`r.jina.ai`) | Any URL → clean markdown, zero config | Alternate/fallback path in `fetch.py` alongside the existing fetcher |
| `yt-dlp` search | YouTube search, not just subtitle pull | New capability for `source-ingestor` (currently ingest-only) |
| `gh` CLI | GitHub repo/code search, zero config | New digger target class — govt/corporate data increasingly ships as repos, not just PDFs; pairs with `datagov.py`/`dataset_watch.py` |
| Jina Reader on LinkedIn public pages | Background on named individuals/companies, no login | Input to `news-investigator`/`source-verifier` (fetch only — the judgment stays theirs) |
| Podcast transcription (Groq Whisper, free) | A lead-source type not currently covered | New lead source, same tier as `source-ingestor`'s video/post ingestion |

None of these need the `agent-reach` package itself installed — they're
thin, individually — but if adopting the package is preferred over
hand-wiring each one, install scoped to *only* these five capabilities, not
the full platform list, and never provide it the account cookies the other
platforms need.

## Open decisions — Anil's call before any code

1. Step 0's two options (narrow `create_skill`'s description + fence, vs.
   pull it from the autonomous loop entirely) — which one.
2. Whether `tech-refiner` is a new skill or a mode of `tech-steward` extended
   with a wider input set — separate skills is cleaner (steward stays cost-
   focused) but doubles the surfacing UI section; one skill with two
   recommendation `area` families is less code. No strong reason either way
   from the codebase alone.
3. Evidence thresholds (the N-in-a-window numbers) — `learning.py` uses
   `MIN_EFFECTIVE_N = 1.5` over a 45-day half-life for editorial priors; this
   is a different kind of signal (binary pass/fail health checks, not
   outcome scores) and probably wants a plain count-in-window rather than a
   decayed score. Needs real failure-rate data to pick sensible numbers —
   suggest instrumenting Step 0 + evidence logging first, picking thresholds
   after a couple weeks of real signal, same way `prefilter.py` was
   calibrated against real output rather than guessed upfront.
4. Agent-Reach: hand-wire the five safe capabilities directly, or install the
   package scoped down — package gives free maintenance (their backend-
   swap-on-block behavior), hand-wiring gives full control over what's
   actually reachable. Leaning hand-wire given how thin the actual need is,
   but flagging rather than deciding.
