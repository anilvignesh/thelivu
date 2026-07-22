# Attended mode — running the engine when the APIs are dry

*Context doc, written 2026-07-22 before building. The problem it solves: on
2026-07-21 both LLM providers ran out of credit within hours of each other and the
engine sat in a 22-hour crash loop producing nothing. This is the designed response.*

---

## The decision

**No cross-engine fallback.** When a provider runs out of credit, the engine does
**not** quietly reroute the work to a different model. It parks the work, tells Anil,
and waits for him to run the cycle **attended** — at the terminal, with Claude Code,
as a human doing his own work.

This restores an invariant the codebase already held. `_pause_run()` in
`engine/agents/orchestrator.py` has always said:

> *"Drop the half-finished run and let the caller re-queue the work, so it resumes
> when credit returns — never lost, **never run on a substitute engine**."*

Commit `9b3202f` (Claude→Gemini auto-fallback, 2026-07-22) contradicted that. It is
reverted. The reasoning that motivated it was sound — *don't stall* — but the answer
to "the API is broke" is a human at a keyboard, not a weaker model silently taking
over the trust gate.

**Why this matters editorially:** the spine of Thelivu is a verification engine that
downgrades compelling-but-false claims. Swapping the model behind the trust gate
without the owner noticing is exactly the kind of silent quality drift the charter
exists to prevent. Cheaper output on the gates is not a neutral cost saving.

---

## The terms boundary — read this before "improving" attended mode

Attended mode is a **human-operated tool**. Anil opens Claude Code, and Claude —
as the interactive assistant in that session — does the research, verification and
writing, with Anil present and driving.

- ✅ **Legitimate:** a human sits down and uses their Claude Code subscription to do
  work on their own project. That is what the product is for.
- ❌ **Not legitimate:** invoking `claude -p ...` from cron, from Railway, or from any
  unattended script, so the subscription becomes a drop-in replacement for the paid
  API in an automated pipeline.

**Therefore: `engine/attend.py` must never shell out to the `claude` binary, and
must never be run headlessly.** It blocks waiting for a human-driven session to
answer each request. That blocking is not an inconvenience to be optimised away —
**it is the compliance boundary.** If a future change makes attended mode run
unsupervised, that change is wrong regardless of how convenient it is.

---

## How it works

### 1. The circuit breaker (`shared/quota.py`)

Any hard provider failure — `billing_cap`, `exhausted`, `bad_key`, `free_tier` —
trips a breaker stored in `kv_store`:

| key | meaning |
|---|---|
| `llm_blocked_until` | ISO timestamp; while in the future, all LLM stages are skipped |
| `llm_blocked_reason` | human-readable cause, shown in Telegram + the dashboard |

- Default cooldown **60 minutes**, then it auto-expires and the engine tries once
  more. So a top-up or a midnight quota reset recovers on its own — no manual switch,
  same self-healing property the reverted commit had.
- A *transient* error (overloaded, 500, timeout) does **not** trip it. Those already
  pause + requeue via `_route_spine_failure`.

### 2. The tick respects the breaker (`run.py`)

While the breaker is up, the 2-minute tick **skips every LLM stage** (scouts, digs,
chief-of-staff, recheck, carousel compose, topic intake, RSS cycle) and logs once.

Everything that doesn't need a model keeps running:
- the Telegram bot and the human gate,
- the fileserver (`/`, `/bio`, `/a/<slug>`, slide images),
- `publish_run()` / `post_carousel_run()` — **Anil can still approve and post**,
- carousel file cleanup, auto-recheck status flips, the cost report.

**Losing the API must not take the publishing surface down with it.** The backlog is
approvable whether or not a model is reachable.

### 3. The hot-loop fix (`run.py`)

`_last_rss_run` was only stamped on **success** (`run.py:237`), so a failing cycle
stayed "due" and retried every 2 minutes — 22 hours of crash loop on 2026-07-21.
It now stamps on failure too, with a shorter backoff than the full interval.

### 4. The Telegram nudge

When the breaker trips, Anil gets one card (deduped once/day by the existing
`_already_alerted` machinery):

> 🖐 **Attended mode**
> Gemini prepay credits depleted. Claude balance exhausted.
> Parked: 6 leads, 2 topics, 1 dig.
> Automated cycles are paused. Run it attended when you're home:
> `cd ~/thelivu && ./attend`

### 5. The attended runner (`engine/attend.py`)

The elegant part: **it does not reimplement the pipeline.** It runs the real
orchestrator, and swaps only the model call.

With `THELIVU_ATTENDED=1`, `run_skill()` routes to a *manual provider* instead of an
API. For each skill call it:

1. writes the full system prompt + input to `.attend/NNN-<skill>.request.md`
2. prints the path and **blocks**, polling for `.attend/NNN-<skill>.response.md`
3. reads that file back as the skill's output and continues the pipeline

Claude, in the interactive session, reads the request file, does the actual work
(research, verification, drafting — with web search as needed), writes the response
file, and the pipeline moves to the next stage.

Consequences of this design:
- **Zero duplication.** Trust gate, anti-monotony check, draft parsing, the human
  gate, carousel queueing — all unchanged, because only the model call moved.
- Output lands at `pending_human` exactly as it would have via the API, so the
  publish gate is untouched.
- Each stage is visible on disk, so a half-finished attended run can be resumed or
  inspected.

Commands:

| command | does |
|---|---|
| `attend status` | what's parked, what the breaker says, what a cycle would do |
| `attend cycle` | run the full RSS cycle attended |
| `attend topic "<text>"` | run one topic through the spine attended |
| `attend run <id>` | resume/redo a specific parked run |
| `attend clear` | drop the breaker early (after a top-up) |

`.attend/` is gitignored — request/response files can contain draft material.

---

## Build checklist (compare against this when done)

- [x] Revert `9b3202f`; no cross-engine fallback anywhere in `run_skill` — `1e22818`
- [x] `shared/quota.py` — trip / check / clear, kv-backed, 60-min auto-expiry
- [x] `_send_quota_alert` trips the breaker on hard alert types only
- [x] `run.py` skips LLM stages while blocked; publishing path stays live
- [x] `_last_rss_run` stamped on failure (hot-loop fix), 30-min backoff
- [x] `engine/attend.py` + `./attend` wrapper; manual provider in `skill_runner`
- [x] `attend.py` contains no reference to the `claude` binary (grepped: no
      `subprocess` / `os.system` / `popen` / `which` anywhere in the path)
- [x] `.attend/` in `.gitignore`
- [x] `PROJECT-STATUS.md` + `docs/HANDOFF.md` updated

### Tested 2026-07-22

| test | result |
|---|---|
| breaker opens / reports the edge only once / reason readable | ✓ |
| 60-min cooldown; auto-expires with nothing running | ✓ |
| garbage timestamp in kv fails **open** (never wedges the tick) | ✓ |
| real Jul-21 Gemini `RESOURCE_EXHAUSTED` + Claude credit error → trips | ✓ |
| overload / 500 / timeout → does **not** trip (pause+requeue keeps them) | ✓ |
| re-arms on a second hard failure the same day (alert dedup ≠ breaker) | ✓ |
| attended handoff writes the prompt, blocks, returns the answer verbatim | ✓ |
| empty `.response.md` raises rather than feeding the trust gate garbage | ✓ |
| `./attend status` against the prod DB | ✓ |

**Deferred:** a full `./attend cycle` end-to-end (it needs a real attended session
to answer every stage — that's the next sit-down, not a unit test).

### Deviations from the plan above

- `attend run <id>` was specced but **not built.** `status`, `cycle`, `topic` and
  `clear` cover the actual need; resuming one specific parked run is speculative
  until a real attended session shows it's wanted.
- `attend status` counts leads in SQL and splits fresh (<7d) from expiring, because
  `get_queued_leads()` caps at a limit — the first version reported the backlog as
  exactly "200" when it was really **1,504**.
