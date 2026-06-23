# Thelivu — AI-Powered Public Interest Journalism Engine

A fully autonomous investigative journalism pipeline. It monitors primary government sources, investigates leads, verifies claims, writes drafts, and sends them to a human editor for approval before anything is published. Nothing reaches the @thelivu Telegram channel without a human decision.

---

## What it does

Every 6 hours, the engine:

1. **Ingests** RSS feeds from curated text journalism and YouTube sources
2. **Scans** primary government databases for under-covered developments (ECI, CAG, RBI, courts, company registries)
3. **Filters** out entertainment, celebrity, sports before any model sees the leads
4. **Selects** the highest-impact, most under-covered story using source reliability scores
5. **Investigates** from primary records — affidavits, filings, court orders, spending data
6. **Verifies** every claim against a strict two-source corroboration gate
7. **Writes** a transparent draft with Fact / Allegation / Inference labels
8. **Reviews** for quality, charter compliance, and legal risk
9. **Sends** the draft to the editor on Telegram with Approve / Kill / Hold buttons

The editor approves → it publishes to @thelivu. No approval → nothing goes out.

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
│    → full pipeline               │        │  Kill / Hold → logged        │
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
pipeline_runs · publications · token_usage
active_agents · pending_topics · seen_items
source_proposals · approved_sources · kv_store
```

---

## The 15 skills

Each skill is a `SKILL.md` file — the file IS the system prompt. No code in the skills, just editorial instructions that any model can follow.

### Research tier (Gemini 2.5 Flash + Google Search)
| Skill | What it does |
|-------|-------------|
| `beat-monitor` | Scans ECI, CAG, RBI, courts, company registries every cycle. Runs 6 cross-database "join the dots" patterns to find what nobody else found. |
| `news-investigator` | Deep-dives one lead into a full evidence dossier. Always hits primary records before reading any news coverage. |
| `source-verifier` | Adversarial re-check of every claim. Two independent credible sources required per claim. Issues KILL / HOLD / READY-FOR-HUMAN. Tool failure = HOLD, never KILL. |
| `source-scout` | Finds new RSS and primary sources to add. Proposes candidates via Telegram for human review. |
| `story-scout` | Works the watchlist weekly — picks one investigation theme and produces a dig brief. |
| `story-tracker` | Checks published stories for new developments. Court compliance, government responses, new documents. Queues follow-ups automatically. |

### Editorial tier (Claude Sonnet 4.6)
| Skill | What it does |
|-------|-------------|
| `topic-intake` | Front gate for editor-submitted topics. Triages for scope and worth. Produces a STORY_BRIEF that frames all downstream work. |
| `article-writer` | Writes the transparent-perspective draft. Confidence labels, source footer, three-bucket labelling throughout. |
| `editorial-reviewer` | Final automated gate. Quality check, charter compliance, framing, named-person safety. Outputs LEGAL-FLAG: YES/NO with specific reason. Sends back REVISION_NEEDED or passes APPROVED. |

### Reasoning tier (DeepSeek R1)
| Skill | What it does |
|-------|-------------|
| `pattern-synthesizer` | Finds the structural pattern and systemic context behind the verified facts. |
| `meta-synthesizer` | Monthly: looks across all published/killed stories for recurring actors, thematic patterns, coverage gaps, and meta-leads invisible at the story level. |

### Utility tier (Groq / Llama 3.3 70B — free)
| Skill | What it does |
|-------|-------------|
| `news-monitor` | Ranks ingested leads by impact × under-coverage. Receives source reliability scores from past runs. |
| `source-ingestor` | Extracts structured claims from YouTube transcripts. |
| `publisher` | Formats approved drafts with confidence label and source footer before channel posting. |
| `finance-manager` | Formats the daily cost report (8pm IST). |

---

## Model routing

Each skill is assigned to the cheapest model that can do the job well. The routing lives in `engine/agents/skill_runner.py`.

| Tier | Provider | Model | Skills | Cost/story |
|------|----------|-------|--------|------------|
| 1 — Research | Gemini 2.5 Flash | `gemini-2.5-flash` | beat-monitor, news-investigator, source-verifier, source-scout, story-scout, story-tracker | ~₹72 |
| 2 — Reasoning | DeepSeek R1 | `deepseek-reasoner` | pattern-synthesizer, meta-synthesizer | ~₹4 |
| 3 — Utility | Groq / Llama 3.3 70B | `llama-3.3-70b-versatile` | news-monitor, publisher, source-ingestor, finance-manager | ₹0 (free) |
| 4 — Editorial | Claude Sonnet 4.6 | `claude-sonnet-4-6` | topic-intake, article-writer, editorial-reviewer | ~₹35 |
| **Total** | | | | **~₹111/story** |

**Fallback chain:** Every tier falls back to Claude if the provider is unconfigured, hits a quota, or returns an error. The pipeline never stops mid-story due to a provider failure.

**Why this split:**
- Gemini gets research skills because Google Search grounding is built in — the model can search the web natively, no separate tool call needed
- DeepSeek R1 gets reasoning skills because it's a chain-of-thought model trained for deep analysis, at 1/6th Claude's price
- Groq gets utility skills (formatting, extraction, classification) because Llama 3.3 70B handles structured prompts reliably and the free tier covers Thelivu's current volume
- Claude keeps editorial judgment because nuance, tone, and complex instruction-following is where it still leads

**Quota alerts:** When any provider hits its limit or needs action, you get a Telegram message immediately — 🟡 for temporary limits with active fallback, 🔴 for billing issues that need money. One notification per issue per day, no spam.

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
- **Legal circuit-breaker.** `LEGAL-FLAG: YES` in review output triggers a prominent `⚠️ LEGAL REVIEW REQUIRED` warning in the Telegram approval message. Stored in DB.
- **Two-source gate.** Verifier requires two independent credible sources per load-bearing claim. One source = HOLD.
- **Hard exclusions.** Cinema, celebrity, gossip, sports, lifestyle filtered at keyword level before any model call.
- **Tool failure = HOLD, not KILL.** Broken search is an infrastructure problem, not editorial failure.
- **Revision loop.** Reviewer can send stories back to investigator and writer up to 2 times.
- **Source reliability scoring.** news-monitor receives per-source verified/killed rates from past runs and weights sources accordingly.

---

## Environment variables

Set on **both** Railway services.

| Variable | Required | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | Yes | Claude Sonnet 4.6 |
| `GEMINI_API_KEY` | Yes | Gemini 2.5 Flash — must have billing enabled |
| `DATABASE_URL` | Yes | Railway PostgreSQL URL |
| `TELEGRAM_BOT_TOKEN` | Yes | From BotFather |
| `TELEGRAM_DRAFT_CHAT_ID` | Yes | Editor's private chat with the bot |
| `TELEGRAM_CHANNEL_ID` | Yes | `@thelivu` |
| `APPROVAL_MODE` | Yes | `telegram` in production |
| `GROQ_API_KEY` | Recommended | Free Llama 3.3 70B — console.groq.com |
| `DEEPSEEK_API_KEY` | Recommended | DeepSeek R1 — platform.deepseek.com |
| `MISTRAL_API_KEY` | Optional | Mistral Small — console.mistral.ai |
| `BRAVE_API_KEY` | Optional | Reliable search fallback — api.search.brave.com |
| `CHECK_INTERVAL_HOURS` | Optional | Default 6 |

---

## Dashboard

```bash
streamlit run dashboard.py
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

# Dashboard
streamlit run dashboard.py
```
