# Plan 05 — Technical steward (the stack's chief-of-staff)

**Goal:** a periodic agent that owns the *technical* health of Thelivu the way
chief-of-staff owns the editorial backlog: keeps model routing apt per task,
watches Anthropic / Google / NVIDIA for new models, price changes, intro-pricing
expiries and deprecations, and keeps cost managed — surfacing a ranked brief
with one-tap-appliable recommendations. **v1 is advisory: it never changes
models or spends money on its own.** Model/price changes on journalism output
are Anil's call; the steward makes them one tap instead of a research session.

Depends on plan 01 (shared/costs.py, the budget governor, Haiku routing).

## Design

Mirror the chief-of-staff pattern exactly (skill + runner + kv signal + tick
block + surfacing). Read `run_chief_of_staff()` + `_build_cos_snapshot()` in
`engine/agents/orchestrator.py` and `engine/skills/chief-of-staff/SKILL.md`
before writing anything — same block-array parsing (`_extract_block_array`,
generous max_tokens, mandatory-complete blocks; HANDOFF §5.12).

### 1. Skill: `engine/skills/tech-steward/SKILL.md`

Input (assembled by the runner):
- **Internal telemetry:** 30-day cost by skill×model (shared/costs over
  token_usage), current routing table (CLAUDE_MODEL / HAIKU_MODEL /
  GEMINI_MODEL / GEMINI_PRO_MODEL / NVIDIA_MODEL and the _HAIKU_SKILLS /
  _GEMINI_SKILLS sets — pass as text), budget cap + trips this week, breaker
  history, avg tokens/story.
- **Date anchor** (the runner already prepends one) — so it catches dated
  events like *Sonnet 5 intro pricing ends 2026-08-31*.

Instructions: search the live web for (a) current Anthropic model catalog +
pricing, (b) current Gemini API models + pricing + deprecation notices for the
models we use, (c) NVIDIA's free hosted catalog (build.nvidia.com) — is our
Gemma/FLUX still served, is something strictly better free. Compare against
the telemetry. Emit:
- a short prose brief (what changed since last sweep, cost posture)
- `RECOMMENDATIONS [...] END_RECOMMENDATIONS` — JSON array of
  `{"area": "routing|pricing|new-model|deprecation|budget",
    "action": <one concrete change, e.g. 'set CLAUDE_MODEL=claude-sonnet-5'>,
    "why": ..., "risk": "low|medium|high", "saves_usd_mo": <est or null>}`

Hard rules in the skill: never recommend moving journalism (writing/editorial/
verification) onto a non-Claude/Gemini model; presentation-only models may be
anything free; recommendations must be actionable as a single env-var or kv
change wherever possible; no more than ~6, ranked.

### 2. Routing & engine

- Route tech-steward to **Gemini flash + Google Search** (add to
  `_GEMINI_SKILLS`) — it's a search-heavy scan, the cheap grounded searcher is
  apt, and the existing Gemini-block→Claude fallback covers content blocks.
  It is ops, not journalism — no charter concern.
- Runner `run_tech_steward()` in the orchestrator: build input → `run_skill`
  → parse blocks → `kv_set('latest_tech_brief', ...)`,
  `kv_set('latest_tech_recs', json)` → Telegram card (`_notify_card`, report
  link for the full brief).
- Tick wiring in `run.py`: weekly, stamp `last_tech_steward_at` BEFORE running
  (the retry-storm rule, HANDOFF §5.16); manual signal `force_tech_steward`.

### 3. Actuation path (what makes recommendations one-tap)

Make the model knobs **env-overridable** so applying a recommendation is a
Railway variable change, not a code push:
- `shared/config.py`: `CLAUDE_MODEL = os.environ.get("THELIVU_CLAUDE_MODEL", "claude-sonnet-4-6")`
  (currently hardcoded, line ~83); same for GEMINI_MODEL / GEMINI_PRO_MODEL
  (already env: NVIDIA_MODEL, HAIKU_MODEL per plan 01).
- Document in the brief card: apply via
  `railway variable set THELIVU_CLAUDE_MODEL=... --service thelivu-agent`
  (and the bot service where relevant) — or from the CC if you build the
  optional applier below.
- **Optional v1.5 (ask Anil first):** CC endpoint that applies a rec by
  writing kv overrides read at skill-call time instead of env (no redeploy).
  Adds indirection; only do it if the env-var flow proves annoying.

### 4. Command center surfacing

- System view: "Tech steward" section — last sweep time, Run now button
  (`force_tech_steward` → add to `ALLOWED_SIGNALS` in
  `command_center/api/system.py`), latest brief (collapsible), and the
  recommendations as cards showing area/risk/est. savings + the exact apply
  command as copyable code. Schedules table: add the row to `SCHEDULES`.
- Keep CC reads inside the existing `db.parallel` fan-outs.

### 5. What the steward does NOT do (encode in SKILL.md + docs)

No autonomous model switches, no spending, no dependency upgrades, no touching
the trust gate, sources, or editorial anything. It is eyes + a ranked memo.
If a recommendation is applied and regresses, reverting is the same one env
var — note the previous value in every recommendation ("from X → to Y").

## Test

1. Scratch: run `run_tech_steward()` attended or with credit once; verify kv
   keys, Telegram card, CC section render, tolerant parsing on a truncated
   RECOMMENDATIONS block (feed it a cut string).
2. Signal path: CC Run-now → kv → next tick picks it up (watch logs).
3. First real sweep should independently rediscover known facts as a sanity
   check: Sonnet 5 intro pricing ending 2026-08-31, Haiku 4.5 at $1/$5 —
   if it can't find those, the search prompt needs work.
