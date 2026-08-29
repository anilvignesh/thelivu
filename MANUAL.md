# Thelivu — Owner's Manual

_Your AI-powered investigative journalism engine. Built by Anil Vignesh + Jarvis._

---

## What is Thelivu?

Thelivu is an autonomous investigative pipeline. It watches YouTube channels and RSS feeds for newsworthy signals, investigates the strongest leads using Gemini + Google Search, verifies claims, and writes drafts.

**This doc's original framing — "sends drafts to you for Approve/Hold/Kill, nothing publishes without your tap" — is no longer how it works.** As of 2026-08-29 (Anil, explicit; narrowed once already on 2026-08-16), every story that clears editorial review publishes and posts on its own. Telegram still sends the draft card below as a **heads-up**, and Approve/Hold/Kill still work as manual overrides if you act before the sweep does — but no tap is required, ever, including for stories naming a real person alongside an allegation. See `engine/distribution/sweep.py`.

---

## Architecture in 60 seconds

```
Sources (YouTube / RSS / beat-monitor)
    ↓ ingest
Lead Queue (7-day rolling, deduplicated)
    ↓ news-monitor (Claude — picks best lead)
    ↓ newsworthiness-gate (Claude — floors on public-interest threshold)
    ↓ news-investigator (Gemini + Google Search — builds evidence dossier)
    ↓ source-verifier (Gemini Pro — trust gate: KILL / HOLD / FRAMING-FIX / READY)
    ↓ [two-source backstop — auto-HOLD if load-bearing claim < 2 sources]
    ↓ pattern-synthesizer (Claude — finds the structural pattern)
    ↓ article-writer (Claude — writes the draft)
    ↓ editorial-reviewer (Claude — up to 2 revision cycles)
    ↓ YOU (Telegram — approve / hold / kill)
    ↓ Telegraph Instant View + Telegram channel post
```

Two AI providers. No cross-engine fallback:
- **Gemini 2.5 Flash** — research and investigation (news-investigator, beat-monitor, story-scout, story-tracker, source-scout)
- **Gemini 2.5 Pro** — verification (source-verifier — highest-stakes stage, needs adversarial reasoning)
- **Claude Sonnet** — judgment, writing, gates (everything else)

If Gemini goes down, research pauses. If Claude goes down, writing pauses. Leads stay queued and resume automatically when the provider is back.

---

## Two Railway services

| Service | What it does |
|---------|-------------|
| `thelivu` | The Telegram bot — handles your approve/kill/hold taps and all commands |
| `thelivu-agent` | The orchestration loop — runs the pipeline every 6h, processes topics, runs weekly scouts |

Both auto-deploy when you push to GitHub `main`.

---

## The Telegram card (heads-up, not a gate)

Every story that clears the trust gate lands in your Telegram draft chat as a card:

```
📰 New story ready — run #42

[Article headline]

▸ Read the draft    [Telegram Instant View link]

[✓ Approve]  [✗ Kill]  [⏸ Hold]
```

- **Approve** → posts to @thelivu channel immediately (Telegraph + teaser) — same as what happens automatically if you don't act
- **Kill** → discards the story permanently — use this to stop the autopublish sweep from posting it
- **Hold** → pauses it; the agent will auto-recheck after 3 days, or you can tap Re-check

If the draft has a legal flag (LEGAL-FLAG: YES in the reviewer's output), the card still shows a red ⚠️ warning — but it no longer blocks anything. It publishes on the same autopublish sweep as everything else; the warning is informational only, so you know to check it after the fact if you want to.

---

## All bot commands

### Story workflow

| Command | What it does |
|---------|-------------|
| `/topic <text>` | Submit a story idea for immediate investigation |
| `/drafts` | List all stories waiting for your review |
| `/held` | List held stories with why they were held (verifier gate, PAUSED, etc.) |
| `/recheck <id>` | Re-investigate a held story from scratch against today's sources |
| `/kill <id>` | Kill a held/stuck/pending run from text |
| `/reset <id>` | Reset a stuck run (frozen at investigating/writing) back to held |
| `/republish <id>` | Re-send approval card for an already-reviewed run |
| `/track <id>` | Show full status of a specific run |
| `/search <keywords>` | Find past runs by throughline keyword |

### Pipeline control

| Command | What it does |
|---------|-------------|
| `/runnow` | Trigger an RSS cycle immediately (don't wait for the 6h schedule) |
| `/scoutnow` | Trigger a source scout now (proposes new sources) |
| `/dig [theme]` | Targeted story-scout dig on a watchlist theme. No theme = the scout picks the ripest one itself. Brief arrives with an Investigate button |
| `/priors` | Show the learning loop's current outcome-weighted signals (see docs/learning-loop.md) |
| `/setinterval <hours>` | Change the RSS cycle interval (1–24h, default 6h) |

### Sources & watchlist

| Command | What it does |
|---------|-------------|
| `/sources` | List all active sources (static + bot-approved) with Deactivate buttons |
| `/feeds` | Raw list of RSS/YouTube feeds from sources.yaml |
| `/addfeed <url>` | Add a new RSS feed directly |
| `/watchlist` | View all watchlist themes |
| `/watchlist add <question>` | Add a new theme to the watchlist |

### Bio page (link in bio)

The public page the Instagram bio points at — served by the agent service at
`SLIDE_SERVER_BASE_URL` (also `/bio`). Published articles are added
automatically on approval; a "Join the Telegram channel" button is part of the
page itself once `CHANNEL_PUBLIC_URL` is set (needs the channel to have a
public @username). These commands manage the rest. See `docs/bio-page.md`
for the design.

| Command | What it does |
|---------|-------------|
| `/links` | List bio-page links with ids + the public page URL |
| `/addlink <url> \| <title>` | Add an evergreen link (channel, about) |
| `/dellink <id>` | Remove a link |
| `/pinlink <id>` | Toggle pin — pinned links stay above the articles |

### Status & monitoring

| Command | What it does |
|---------|-------------|
| `/pending` | Everything waiting on your decision (drafts, carousels, held, proposals) in one card |
| `/help` | Legend: what each card type means + key commands |
| `/status` | Pipeline health: active agents, ghost count, stuck topics, latest run |
| `/queue` | What's queued: owner topics + last 5 pipeline runs + next cycle timing |
| `/leads` | Peek at the current lead queue (up to 10 leads) |
| `/stats` | Lifetime stats: publish rate, kill rate, top sources, avg tokens/story |
| `/cost` | Token spend breakdown by model for today / this month / all time |
| `/setcost HH:MM` | Change the daily cost report time (UTC, default 14:30 = 8pm IST) |

### Admin / recovery

| Command | What it does |
|---------|-------------|
| `/clearghosts` | Clear all stale active_agents (>30min) + reset stuck 'running' topics |
| `/start` | Show the command menu |

---

## Inline buttons (you don't type these — they appear in cards)

| Button | Where it appears | What it does |
|--------|-----------------|-------------|
| ✓ Approve | Draft card | Publishes to channel |
| ✗ Kill | Draft card, Hold confirmation, /held | Kills the story |
| ⏸ Hold | Draft card | Holds; shows Re-check + Kill |
| 🔄 Re-check now | Hold confirmation, /held list | Queues for fresh re-investigation |
| 🔍 Investigate this now | Weekly scout card | Queues the scout brief as a topic |
| ✓ Add to sources | Source proposal card | Approves and activates the source |
| ✗ Skip | Source proposal card | Rejects the proposal |
| ✗ Deactivate | /sources list | Deactivates a bot-approved source |

---

## Weekly automated jobs (run every Sunday)

| Job | What it does |
|-----|-------------|
| **Source scout** | Gemini searches for new Tier 1–2 sources that fill gaps in the pool. Proposals come to Telegram with Add / Skip buttons. |
| **Story scout** | Picks one watchlist theme, produces a dig brief, sends it to Telegram as a Telegraph link with an "Investigate now" button. |
| **Story tracker** | Checks all published stories for new developments — court compliance, government responses, new documents. High/Medium priority follow-ups are automatically queued as topics. |

Monthly:
| Job | What it does |
|-----|-------------|
| **Meta-synthesizer** | Finds patterns across all published and killed stories — recurring actors, structural failures, editorial themes. |

---

## What each AI provider does

### Gemini (research / ground truth)
Uses **Google Search grounding** — all facts come from live web results, not training memory.

- `news-investigator` — builds the Evidence Dossier (all claims, sources, primary documents)
- `source-verifier` (Gemini Pro) — the Trust Gate. Verifies each claim against independent sources. Issues KILL / HOLD / FRAMING-FIX / READY-FOR-HUMAN
- `beat-monitor` — scans govt feeds (Kerala HC, ECI, RBI, CAG) daily for under-covered leads
- `story-scout` — weekly watchlist dig brief
- `story-tracker` — weekly follow-up check on published stories
- `source-scout` — weekly source proposal

### Claude (judgment / writing)
Uses web search only for `topic-intake`. Everything else works from the provided dossier.

- `topic-intake` — evaluates your submitted topics: PROCEED / PARK / DECLINE
- `news-monitor` — picks the best lead from the queue
- `newsworthiness-gate` — absolute floor check before expensive investigation
- `pattern-synthesizer` — finds the structural pattern in the verified dossier
- `article-writer` — writes the draft
- `editorial-reviewer` — up to 2 revision cycles (fact-checking, charter compliance, legal flag)

---

## Trust gate decisions

The `source-verifier` (Gemini Pro) is the most consequential stage. It issues one of four verdicts:

| Verdict | What happens |
|---------|-------------|
| `READY-FOR-HUMAN` | Story clears — goes to writing, then you |
| `FRAMING-FIX` | Facts hold, framing doesn't. Flags specific fix; writer applies it before you see the draft |
| `HOLD` | Not enough independent sourcing yet. Story held; auto-rechecked in 3 days |
| `KILL` | Story doesn't meet the bar — unverifiable claim, not a story, etc. Discarded |

**Two-source backstop:** Even if the model says READY, if any load-bearing claim is verified against fewer than 2 independent sources, it's automatically held. This is a code-level safety check, not an AI judgment.

---

## What the Trust Gate does NOT mean

- **KILL ≠ "the story is false"** — it means we couldn't verify it to our standard. You can still investigate manually.
- **HOLD ≠ "bad story"** — it means it needs more sources or time. Most held stories ripen.
- **READY-FOR-HUMAN ≠ publish immediately** — you're the final gate. The AI can be wrong.

---

## Source tiers

| Tier | Icon | What it means |
|------|------|--------------|
| Tier 1 | 🟢 | Primary records — court orders, government data, RTI responses, regulatory filings |
| Tier 2 | 🟡 | Established investigative outlets — The Ken, Scroll, The Wire, IndiaSpend, OCCRP |
| Tier 3 | 🟠 | Secondary — mainstream news, YouTube journalism channels |

The source-verifier prefers Tier 1 and Tier 2 sources for load-bearing claims. A Tier 3-only verification on a load-bearing claim triggers a HOLD.

---

## Story statuses

| Status | Meaning |
|--------|---------|
| `investigating` | Gemini is building the Evidence Dossier right now |
| `writing` | Claude is writing the draft (trust gate cleared) |
| `pending_human` | Waiting for your approve/kill/hold decision |
| `published` | Sent to @thelivu channel |
| `held` | Held by you (tapped Hold on the draft card) |
| `hold` | Held by the verifier (trust gate said HOLD) |
| `killed` | Killed (by you or trust gate) |
| `recheck_requested` | You (or the auto-scheduler) queued it for fresh re-investigation |
| `dropped` | Provider went down mid-spine; lead re-queued for next cycle |
| `needs_attention` | Halted — a stage returned no valid structured output |

---

## Recovery playbook

### "A run is stuck at investigating or writing"
```
/reset <run_id>
```
This clears ghost active_agent rows and resets the run to held. Then use `/recheck <run_id>` to re-run it.

### "I see ⚠️ Ghost agents in /status"
```
/clearghosts
```
Clears all stale agents (>30min old) and resets stuck pending_topics.

### "The pipeline hasn't run in a long time"
Check `/queue` for next cycle timing. If it shows "starting soon" but nothing happens:
1. Check Railway logs for the `thelivu-agent` service
2. Use `/runnow` to force an immediate cycle
3. If Gemini is down, use `/status` — it'll show "Gemini unavailable" in active agents

### "A topic I submitted isn't moving"
```
/queue
```
Check if it's showing as ⚠️ stuck. If so, `/clearghosts` then re-submit with `/topic`.

### "Cost is higher than expected"
```
/cost
```
Shows per-model breakdown. Look for unusually high Gemini Pro (verifier) usage — Pro is 4× more expensive than Flash. Also check `/stats` for avg tokens/story; if it's >100k, investigation prompts may be too verbose.

---

## Watchlist

The watchlist (`engine/watchlist.yaml`) is the investigative agenda — themes worth digging into. The story-scout picks one theme per week and produces a dig brief.

Themes have a status lifecycle:
`scoping` → `records-pending` → `verifying` → `ready-to-write` → `parked` / `killed`

Add new themes:
```
/watchlist add Who controls Kerala's sand mining contracts and who gets the revenue?
```

Edit via git for richer entries (why_under_told, primary_records, RTIs, etc.).

---

## Cost reference (July 2026 pricing)

| Model | Use | Input | Output |
|-------|-----|-------|--------|
| Gemini 2.5 Flash | Investigation, scouts | $0.30/MTok | $1.00/MTok |
| Gemini 2.5 Pro | Verification (trust gate) | $1.25/MTok | $5.00/MTok |
| Claude Sonnet 4.6 | Everything else | $3.00/MTok | $15.00/MTok |

Typical story cost: ₹15–40 depending on investigation depth and revision cycles.
Daily cost report arrives at 8pm IST (change with `/setcost`).

---

## Database tables (quick reference)

| Table | What's in it |
|-------|-------------|
| `pipeline_runs` | Every story — status, throughline, draft, verification, trust gate |
| `token_usage` | Token spend per skill call, per model |
| `lead_queue` | Incoming leads from RSS/YouTube/beat-monitor (7-day rolling) |
| `pending_topics` | Your `/topic` submissions |
| `approved_sources` | Sources approved via Telegram bot (Add button on proposals) |
| `source_proposals` | Source scout proposals, pending your review |
| `publications` | Published stories — channel message IDs |
| `active_agents` | In-flight skill calls (cleared on crash by startup cleanup) |
| `kv_store` | Key-value signals (force_rss_run, last_cycle_at, cost_report_utc, etc.) |
| `seen_items` | Deduplication — video IDs / URLs already ingested |

---

## Key kv_store signals

| Key | Set by | Read by | Purpose |
|-----|--------|---------|---------|
| `force_rss_run` | `/runnow` | run.py | Trigger immediate RSS cycle |
| `force_scout_run` | `/scoutnow` | run.py | Trigger immediate source scout |
| `last_cycle_at` | orchestrator | run.py, /queue | Track cycle timing |
| `last_scout_at` | orchestrator | run.py | Weekly scout scheduling |
| `latest_scout_brief` | story-scout | bot.py | "Investigate now" button payload |
| `cost_report_utc` | `/setcost` | run.py | Daily report time (HH:MM) |
| `check_interval_hours` | `/setinterval` | run.py | RSS cycle interval |
| `last_auto_recheck_at` | run.py | run.py | Daily auto-recheck of held stories |

---

## Files you might want to edit directly

| File | What it is |
|------|-----------|
| `engine/sources.yaml` | Primary source list — add/remove/activate YouTube channels and RSS feeds |
| `engine/watchlist.yaml` | Investigative agenda — themes for the weekly story-scout |
| `engine/skills/*/SKILL.md` | AI skill definitions — the instructions each model stage gets |
| `engine/CHARTER.md` | Editorial charter — the rules the pipeline enforces |

---

## What Jarvis built (session log)

**Session 1 (context summary):**
- Fixed Gemini MAX_TOKENS crash (text=None when thinking tokens exhaust output budget)
- Fixed token recording NULL bug
- Added `/reset`, `/held` improvements, `/scoutnow` kv fix
- Wired `force_scout_run` signal in run.py
- Fixed source proposal HTML cards, story scout Telegraph link, story tracker, beat monitor throughlines
- Cleared ghost agents and reset stuck runs #24 and #27

**Session 2 (this session):**
- Cost report now per-model with Gemini Flash vs Pro differentiation
- Added `clear_stale_topics()` — startup cleanup for stuck pending_topics
- Added `/clearghosts` command
- Richer `/status` with live agents, ghost count, stuck topics
- Fixed `duckduckgo_search` → `ddgs` deprecation
- Added `/kill <id>`, `/sources` with Deactivate buttons, `/setcost HH:MM`
- Hold confirmation now shows Re-check + Kill buttons
- `/held` now shows why each story was held
- `/queue` tags stuck 'running' topics
- 7-day spend trend in daily cost report
- story-tracker parser replaced fragile heuristic with JSON block (FOLLOW_UPS)
- Removed dead `__main__` loop from orchestrator.py
- Removed unused streamlit + pandas from requirements.txt
- Auto-retry of held stories (wired `get_held_runs` into run.py daily pass)
- Multi-story fallback: if top lead fails newsworthiness gate, tries next lead
- Source feed silence alert (3+ consecutive zero-item cycles)
- Publication confirmation with channel jump link
- Idle pipeline alert (>8h since last cycle)
- `/stats` command (lifetime publish rate, kill rate, top sources)
- `/search <query>` command (find past runs by throughline keyword)
- `/watchlist` and `/watchlist add` commands
- `/setinterval <hours>` command (RSS cycle interval via bot)
