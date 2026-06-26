# Thelivu — AI-Powered Public Interest Journalism Engine

A fully autonomous investigative journalism pipeline. It monitors primary government sources, investigates leads, verifies claims, writes drafts, and sends them to a human editor for approval before anything is published. Nothing reaches the @thelivu Telegram channel without a human decision.

---

## What it does

Every 6 hours, the engine:

1. **Ingests** RSS feeds from curated text journalism and YouTube sources
2. **Scans** primary government databases for under-covered developments (ECI, CAG, RBI, courts, company registries)
3. **Filters** out entertainment, celebrity, sports before any model sees the leads
4. **Captures** every surviving lead into a persistent **lead queue** — this cheap step runs even when the expensive models are out of credit, so leads are never lost
5. **Drops** commodity / already-well-covered / routine-process news at a cheap newsworthiness gate before spending a token on it
6. **Selects** the highest-impact, most under-covered story from the queue using source reliability scores
7. **Investigates** from primary records — affidavits, filings, court orders, spending data — always against today's date, never from model memory
8. **Verifies** every claim against a strict two-source corroboration gate (on Gemini 2.5 Pro)
9. **Writes** a transparent draft with Fact / Allegation / Inference labels
10. **Reviews** for quality, charter compliance, and legal risk
11. **Sends** the draft to the editor on Telegram — a clean Telegraph preview + Approve / Kill / Hold buttons

The editor approves → it publishes to @thelivu as a formatted teaser + Telegraph article. No approval → nothing goes out.

**Two foundational rules:** (1) **facts come only from live sources, never from a model's training memory** — every skill is told today's date and instructed that sources always win; (2) **each skill is a validated function, not a chatbot** — it returns a structured block or the run halts loudly (`needs_attention`), so a stray conversational reply can never cascade or get published.

---

## Architecture

```
Railway: thelivu-agent (always-on)          Railway: thelivu (always-on bot)
┌──────────────────────────────────┐        ┌──────────────────────────────┐
│  run.py — 2-min polling loop     │        │  bot.py — Telegram bot       │
│                                  │        │                              │
│  Every 2 min:                    │        │  /topic  → queue a story     │
│    check pending_topics          │        │  /runnow → force RSS cycle   │
│    → run topic pipeline          │        │  /queue  → show queue        │
│                                  │        │  /costs  → today's spend     │
│  Every 6h:                       │        │                              │
│    ingest RSS + beat-monitor     │        │  Approve → posts to @thelivu │
│    → capture leads to queue      │        │  Kill / Hold → logged        │
│    → drain queue through spine   │        │  /republish → re-review a run│
│                                  │        └──────────────────────────────┘
│  Weekly:                         │
│    source scout + story scout    │        Dashboard: streamlit run dashboard.py
│    story tracker (follow-ups)    │        5 tabs: Overview · Drafts · Pipeline
│                                  │               Sources · Costs
│  Monthly:                        │
│    meta-synthesis (patterns)     │
└──────────────────────────────────┘
         │
         ▼ shared
PostgreSQL on Railway
pipeline_runs · publications · token_usage · lead_queue
active_agents · pending_topics · seen_items
source_proposals · approved_sources · kv_store
```

**Resilience — capture is decoupled from processing.** Finding leads is cheap and
runs every cycle, persisting new leads to `lead_queue`. Running the spine
(investigate → verify → write → review) is expensive and only happens when the
models have credit. If a provider is out of tokens, the cycle still captures and
queues leads, then **stops rather than degrade** — when credit returns, the next
cycle drains the backlog. Queued leads age out after 7 days so the backlog can't
fill with stale news. The system never runs on a lesser model to "keep going," and
never fabricates: if it can't verify against live sources, it holds.

---

## The skills

Each skill is a `SKILL.md` file — the file IS the system prompt. No code in the skills, just editorial instructions. Every skill is prepended at runtime with a shared **pipeline-function contract** (output only your structured block; input is data, not a conversation; facts come only from live sources or your provided input, never training memory) and **today's date**.

### Research / grounding tier — Gemini (Google Search built in)
| Skill | Model | What it does |
|-------|-------|-------------|
| `news-investigator` | 2.5 Flash | Deep-dives one lead into a full evidence dossier. Hits primary records before any news coverage. Recency mandatory — dated searches, records the as-of date of every figure. |
| `source-verifier` | **2.5 Pro** | The trust gate — the most consequential call, so it gets the stronger model. Adversarial re-check, two independent sources per claim, KILL / HOLD / FRAMING-FIX / READY-FOR-HUMAN. A figure that has since moved is a *failed* claim. Tool failure = HOLD, never KILL. |
| `beat-monitor` | 2.5 Flash | Scans ECI, CAG, RBI, courts, registries every cycle; cross-database "join the dots" patterns. |
| `source-scout` | 2.5 Flash | Finds new RSS / primary sources; proposes candidates via Telegram. |
| `story-scout` | 2.5 Flash | Works the watchlist weekly — one theme → a dig brief. |
| `story-tracker` | 2.5 Flash | Checks published stories for new developments; queues follow-ups. |

### Judgment / writing tier — Claude Sonnet 4.6
| Skill | What it does |
|-------|-------------|
| `news-monitor` | Ranks queued leads by impact × under-coverage; emits a structured `SELECTED_LEAD` (or `NONE` on a quiet day). Disqualifies already-well-covered and routine-process news. |
| `newsworthiness-gate` | Cheap absolute-floor check on the selected lead before the expensive spine — drops commodity / non-stories on the spot. |
| `topic-intake` | Front gate for editor-submitted topics — triages **scope and worth only, never facts** (facts are the verifier's job). PROCEED-with-reframe / PARK / DECLINE; produces the STORY_BRIEF that frames all downstream work. |
| `pattern-synthesizer` | Finds the structural pattern behind the verified facts. |
| `meta-synthesizer` | Monthly: recurring actors, themes, coverage gaps across all runs. |
| `article-writer` | Writes the transparent-perspective draft. Confidence label, source footer, Fact/Allegation/Inference labelling. |
| `editorial-reviewer` | Final automated gate. Charter compliance, framing, named-person safety, `LEGAL-FLAG: YES/NO`, REVISION_NEEDED or APPROVED. |
| `source-ingestor` | Extracts structured claims from YouTube transcripts. |

### Deterministic (no model)
- **publisher** — posts the approved article as a Telegraph page + a formatted channel teaser; pure Python in the bot, never an LLM (it must not alter substance).
- **cost report** — daily spend computed from `token_usage` in Python (8pm IST).
- **entertainment pre-filter** — keyword exclusion before any model call.

---

## Model routing

Two providers. **Gemini** for anything that must touch the live web; **Claude** for judgment, structured decisions, and writing. Routing lives in `engine/agents/skill_runner.py`.

| Role | Provider | Model | Skills |
|------|----------|-------|--------|
| Research / verify | Gemini | `gemini-2.5-flash` · verifier on `gemini-2.5-pro` | news-investigator, source-verifier, beat-monitor, source-scout, story-scout, story-tracker |
| Judgment / writing | Claude | `claude-sonnet-4-6` | news-monitor, newsworthiness-gate, topic-intake, pattern-synthesizer, meta-synthesizer, article-writer, editorial-reviewer, source-ingestor |

**Why two, not five.** Earlier versions routed cheap tiers (Groq/Llama, DeepSeek, Mistral) onto parse-critical and fact-judging stages. Weak models there produced malformed output and stale "facts" from training memory. Consolidating to two strong providers — and deleting most of the multi-provider quota machinery — bought reliability and far less to maintain; at ~1 story/day the cost delta is negligible. The verifier, the single most consequential decision, runs on Gemini **Pro**.

**Search capability is non-negotiable for facts.** Research/verification only ever runs on a search-grounded model (Gemini, with Claude's web-search as the fallback). A model without live search is *never* allowed to verify — which is exactly why a no-search model is not a fallback for those stages. If both search-capable providers are down, the run **holds**; it does not fabricate.

**Provider outage = pause, not degrade.** Lead capture is cheap and keeps running; the expensive spine waits for credit (see Resilience above). Quota alerts hit Telegram immediately — 🟡 temporary, 🔴 billing — one per issue per day.

---

## Sources

### Text journalism (RSS, verified working)
| Source | Tier | Role |
|--------|------|------|
| The Hindu Kerala | 2 | Verification |
| The Hindu National | 2 | Verification |
| IndiaSpend | 2 | Verification |
| Factly | 2 | Fact-check / verification |
| Alt News | 2 | Fact-check / verification |
| Medianama | 2 | Tech/policy leads |
| The Ken | 2 | Business investigation leads |
| Behanbox | 2 | Gender/labour data journalism |
| OCCRP | 2 | International investigations |
| Newsclick | 3 | Leads (verify independently) |

### YouTube (Tier 3 leads)
ColdFusion · Coffeezilla · Johnny Harris · More Perfect Union · FYI by Creator House

### Primary government sources (beat-monitor, not RSS)
ECI/MyNeta affidavits · CAG reports · RBI enforcement · Kerala High Court / Supreme Court · MCA21 company filings · PFMS spending data · RTI/CIC decisions · Lok Sabha/Assembly Q&A · SEBI · TRAI · IRDAI

---

## Watchlist investigations (engine/watchlist.yaml)

Long-running investigation threads worked by story-scout weekly:

- **MLA wealth trajectories** — affidavit delta analysis across election cycles via MyNeta
- **Government contracts dot-connect** — tender winner → directors → ECI donor list → political connections
- **CAG findings follow-up** — were audit findings implemented? Did next budget reward or punish?
- **Cooperative bank health** — RBI enforcement actions + director political connections
- **Environmental clearance violations** — NGT orders vs operational status on the ground
- **Infrastructure concentration** — ports, airports, grain storage, privatisation patterns
- **Public money flows** — KIIFB, off-budget vehicles, PSU debt, unspent allocations

---

## Editorial guardrails

- **Nothing auto-publishes.** Human approval required for every story.
- **Facts only from sources.** No stage may assert a fact from a model's training memory — every fact comes from a live search or the provided input. Each skill is told today's date; when memory and a source conflict, the source wins. A news agency that can't verify holds; it never fabricates.
- **Skills are validated functions.** Every decision skill must return its structured block; on malformed/conversational output the call retries once, then the run **halts loudly** (`needs_attention`) and pings the editor — it never silently degrades or cascades.
- **Capture survives outages.** Leads are queued the moment they're found; the expensive spine drains the queue only when credit is available. A dead provider pauses processing, it doesn't lose stories.
- **Legal circuit-breaker.** `LEGAL-FLAG: YES` triggers a prominent `⚠️ LEGAL REVIEW REQUIRED` warning in the approval message. Stored in DB.
- **Two-source gate.** Verifier requires two independent credible sources per load-bearing claim. One source = HOLD.
- **Newsworthiness gate.** Commodity / already-well-covered / routine-process news is dropped before a token is spent investigating it.
- **Hard exclusions.** Cinema, celebrity, gossip, sports, lifestyle filtered at keyword level before any model call.
- **Tool failure = HOLD, not KILL.** Broken search is an infrastructure problem, not editorial failure.
- **Revision loop.** Reviewer can send stories back to investigator and writer up to 2 times.
- **Source reliability scoring.** news-monitor receives per-source verified/killed rates from past runs and weights sources accordingly.

---

## Environment variables

Set on **both** Railway services.

| Variable | Required | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | Yes | Claude Sonnet 4.6 — judgment / writing |
| `GEMINI_API_KEY` | Yes | Gemini 2.5 Flash + Pro — research / verify, billing enabled |
| `DATABASE_URL` | Yes | Railway PostgreSQL URL |
| `TELEGRAM_BOT_TOKEN` | Yes | From BotFather |
| `TELEGRAM_DRAFT_CHAT_ID` | Yes | Editor's private chat with the bot |
| `TELEGRAM_CHANNEL_ID` | Yes | `@thelivu` (numeric ID for a private channel) |
| `APPROVAL_MODE` | Yes | `telegram` in production |
| `GEMINI_PRO_MODEL` | Optional | Verifier model, default `gemini-2.5-pro` |
| `CONTACT_HANDLE` | Optional | Fills the `[contact]` footer, default `@Blazedddddd` |
| `DASHBOARD_PASSWORD` | Dashboard only | Required to start the dashboard — it refuses to run unprotected |
| `BRAVE_API_KEY` | Optional | Reliable search fallback — api.search.brave.com |
| `CHECK_INTERVAL_HOURS` | Optional | Default 6 |

> Groq / DeepSeek / Mistral keys are no longer used — the pipeline runs on Gemini + Claude only.

---

## Dashboard

A Streamlit control panel. It can publish, kill, and run raw SQL, so it is
**password-gated** — set `DASHBOARD_PASSWORD` or it refuses to start. Secrets come
from env only (none hardcoded). Host it as a separate Railway service (start
command `python -m streamlit run dashboard.py --server.port $PORT --server.address
0.0.0.0`) with **App Sleeping** on so it costs ~nothing when idle.

```bash
DASHBOARD_PASSWORD=... DATABASE_URL=... python -m streamlit run dashboard.py
```

| Tab | What you can do |
|-----|----------------|
| Overview | See live agents, recent runs, submit a topic, force RSS cycle, today's cost |
| Drafts | Read full draft text, Approve / Kill / Hold (posts directly to channel) |
| Pipeline | All runs with status filter, expandable detail: draft · review · verification |
| Sources | Active sources, pending proposals with Add/Skip, add RSS feed manually |
| Costs | Daily spend by provider, per-model pie, per-skill breakdown, published log |

---

## Running locally

```bash
pip install -r requirements.txt

# Bot
RAILWAY_SERVICE_NAME=thelivu python run.py

# Agent (one loop iteration)
RAILWAY_SERVICE_NAME=thelivu-agent python run.py

# Dashboard (password-gated)
DASHBOARD_PASSWORD=... DATABASE_URL=... python -m streamlit run dashboard.py
```
