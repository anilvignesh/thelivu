# Plan 01 — Budget governor + Haiku triage routing

**Goal:** the engine runs autonomously on a hard daily spend cap, and triage
skills run on Haiku 4.5 so a dollar buys ~2× the stories. Target outcome:
~$34/mo burn → ~$20/mo, and the engine can never again die ungracefully
mid-spine on an exhausted balance — it parks at the cap and resumes tomorrow.

**Owner decisions already made (don't re-ask):** triage on Haiku is approved in
principle by the cost discussion of 2026-07-26; the trust-critical chain
(source-verifier on Gemini Pro, two-source backstop, article-writer,
editorial-reviewer, news-investigator fallback) STAYS on the full Claude model.
Haiku is still Claude — the owner's model split (journalism never on Gemma)
holds. Default cap: **$0.75/day**, kv-configurable.

---

## Part A — one shared cost model (prerequisite cleanup)

The USD-per-MTok table is currently triplicated and diverging:
- `engine/agents/orchestrator.py` ~line 2040 (`_CLAUDE_OUT_PER_M` etc. + `_calc_cost`)
- `dashboard.py` ~line 40 (`_MODEL_COSTS` + `cost()`)
- `command_center/api/util.py` (`_MODEL_COSTS` + `cost_usd()`)

Create **`shared/costs.py`**:

```python
RATES = {  # USD per MTok: (input, output). Keys are substring-matched, most specific first.
    "haiku":      (1.00, 5.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini":     (0.30, 1.00),
    "gemma":      (0.0, 0.0),      # NVIDIA free
    "attended":   (0.0, 0.0),
    "claude":     (3.00, 15.00),   # sonnet-class default
}
USD_TO_INR = 84

def cost_usd(model, in_tok, out_tok): ...   # substring match, order matters
def daily_spend_usd(day=None): ...          # sums token_usage for the (UTC) day via shared.db
```

`daily_spend_usd` queries `token_usage` grouped by model for `recorded_at::date
= CURRENT_DATE` (dual-dialect — copy the pattern from
`shared.db.get_cost_report_data`, which already has the sqlite branch) and runs
the rows through `cost_usd`. Refactor all three call sites to import from
`shared.costs`. Note the CC's `cost_usd` also has a "nvidia" tier and INR — keep
behavior identical (CC gate: its existing tests in git history hit /api/costs).

## Part B — Haiku routing in the skill runner

File: `engine/agents/skill_runner.py`.

1. `shared/config.py` (~line 83): add
   `HAIKU_MODEL = os.environ.get("THELIVU_HAIKU_MODEL", "claude-haiku-4-5")`
   next to `CLAUDE_MODEL = "claude-sonnet-4-6"`.
2. Add near `_GEMINI_SKILLS` (~line 203):
   ```python
   # Triage/selection/gating — strict output contracts, no writing, no trust
   # gate. Haiku 4.5 at 1/3 the price. Journalism (writing, editorial, the
   # investigator fallback) stays on CLAUDE_MODEL.
   _HAIKU_SKILLS = {"news-monitor", "topic-intake", "chief-of-staff", "newsworthiness-gate"}
   ```
3. `_run_claude(...)` (line ~392): add a `model=CLAUDE_MODEL` keyword param;
   use it at the `client.messages.create(model=...)` call (~line 414) and in
   `record_usage(skill=..., model=...)` (~line 460) — record the ACTUAL model
   string so cost accounting stays truthful.
4. In `run_skill` (~line 615 area, the Claude branch): pick
   `model = HAIKU_MODEL if skill_name in _HAIKU_SKILLS else CLAUDE_MODEL`, pass
   it through, and use it for `model_label` / `agent_start`.
5. **Check `_run_claude`'s web-search tool config against Haiku** —
   `_CLAUDE_SKILL_TOOLS` gives chief-of-staff (and others?) web search. Haiku
   4.5 supports the basic `web_search_20250305` tool type; if the code uses a
   newer `web_search_20260209` variant, keep that ONLY for sonnet-class and use
   the basic type for Haiku (the `_20260209` variant needs Opus 4.6+/Sonnet
   4.6+ — it will 400 on Haiku).
6. Prompt-cache note: `_cache_growing_context` stays as is — caches are
   per-model, so Haiku skills build their own cache. No change needed.

**Quality guardrail:** news-monitor has a selection contract
(`SELECTED_LEAD` input-numbering + `SELECTED_THROUGHLINE` echo — see
`_resolve_selected_lead` in the orchestrator, which fuzzy-matches and distrusts
the index). That resolver already defends against a weaker model's numbering
mistakes. After deploying, watch 2-3 cycles' logs for "throughline unmatched"
warnings; if Haiku's selections start failing the match, revert just
news-monitor to sonnet-class and keep the other three on Haiku.

## Part C — the budget governor

Mechanism mirrors the quota breaker but is spend-driven and self-expiring at
midnight UTC.

1. **`shared/budget.py`**:
   ```python
   DEFAULT_CAP_USD = 0.75
   def cap_usd():        # kv 'daily_budget_usd'; ''/'0'/unset → disabled (None)
   def is_over_budget(): # (cap is not None) and shared.costs.daily_spend_usd() >= cap
                         # returns (spent, cap) or None — give the caller numbers to log
   ```
2. **`run.py`** — insert AFTER the quota-breaker block (breaker has precedence;
   its `continue` already covers the dry-API case) and BEFORE the weekly jobs:
   ```python
   # ── Budget governor ── spend cap reached → park model stages until the
   # UTC day rolls over. Non-model work (publish/post/cleanup/approvals)
   # already ran above, mirroring the breaker's design. Throttle the log
   # like _breaker_logged_at does.
   ```
   Same `time.sleep(TOPIC_POLL_SECONDS); continue` pattern. Add a
   `_budget_logged_at` throttle (copy `_breaker_logged_at`). One Telegram
   notify per day when the cap first trips (kv `last_budget_alert_at`,
   compare dates): "Budget cap $X reached for today (~$Y spent) — engine
   resumes at midnight UTC. `/setbudget` or the command center changes it."
3. **Note:** this adds ~1 DB query per 2-min tick from inside Railway
   (internal network — cheap). Do NOT cache it in-process for more than a few
   ticks; a stale read past the cap is real money.
4. **Command center surfacing** (`command_center/`):
   - `/api/system` response: add `budget: {cap_usd, spent_today_usd, over}`.
   - New endpoint `POST /api/system/budget {usd}` → `kv_set('daily_budget_usd', ...)`
     (validate 0 ≤ usd ≤ 20; 0 disables). Add to `api/system.py` routes.
   - System view: show cap + today's spend + an input to change it.
   - Overview: banner when `over` (mirror the breaker banner, gold not red —
     it's healthy behavior, not an outage).
   - CC perf pattern: fold the budget numbers into the existing
     `db.parallel(...)` fan-outs — do not add serial round trips
     (see `command_center/db.py` docstring for why).
5. **Bot command (optional, small):** `/setbudget 0.75` in
   `thelivu_bot/bot.py` mirroring `/setcost`. Skip if time-boxed.

## Part D — optional, flag to Anil before doing

Switch `CLAUDE_MODEL` to `"claude-sonnet-5"` for the writing core: intro
pricing $2/$10 through 2026-08-31 makes it ~13% cheaper than Sonnet 4.6 *and*
a better model (its tokenizer uses ~30% more tokens, which eats most of the
discount; after Aug 31 it's ~30% dearer than 4.6). If adopted, put a dated
comment in config to revisit 2026-09-01. **Ask Anil first — model choice on
journalism output is his call.**

## Test plan

1. `py_compile` everything touched.
2. Scratch sqlite: `DB_PATH=... python -c` — `record_usage` a few rows with
   haiku/sonnet/gemini models, assert `shared.costs.daily_spend_usd()` matches
   hand-computed; set kv cap below/above and assert `is_over_budget()`.
3. CC scratch server (:8611 pattern from git history): `/api/system` carries
   budget; POST budget endpoint sets kv; bogus values rejected.
4. Routing: unit-call `run_skill` is NOT safely testable without credit — the
   breaker is open. Instead verify statically (grep the chosen model per skill
   branch) and, after credit is loaded, watch the first cycle's
   `token_usage` rows: triage skills must record `claude-haiku-4-5`.
5. Deploy: push → verify Railway deployment commit hash == HEAD → set
   `daily_budget_usd` via the CC → confirm the governor line appears in
   `railway logs` once spend crosses it (or set cap to 0.01 briefly to watch
   it trip, then restore — the governor blocks model stages only, so this is
   safe to do live).

## Files touched

`shared/costs.py` (new) · `shared/budget.py` (new) · `shared/config.py` ·
`engine/agents/skill_runner.py` · `engine/agents/orchestrator.py` (cost import)
· `run.py` · `dashboard.py` (cost import) · `command_center/api/util.py` ·
`command_center/api/system.py` · `command_center/static/app.js` ·
`thelivu_bot/bot.py` (optional) · `PROJECT-STATUS.md` + `docs/HANDOFF.md`
(document the governor + routing).
