# Thelivu — AI-Powered Public Interest Journalism Engine

A fully autonomous investigative journalism pipeline. It monitors primary government sources, investigates leads, verifies claims, writes drafts, publishes articles, and cuts them into narrated Instagram/YouTube reels in Anil's own cloned voice.

**Publishing is automatic; the gates are editorial, not manual.** Until 2026-08-29 nothing published without a human tap. That gate was removed deliberately — all volume now autopublishes, and the human sees it afterwards. What replaced it is a set of *hard* gates in code that refuse to ship rather than asking permission: a claim that fails verification, a reel whose captions leak model reasoning, a figure that isn't in the article, a cut that breaks the 90-second reach ceiling, or a story whose reel already went out. The human decision moved from "approve each piece" to "set the rules and read what shipped."

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
11. **Publishes** the article to its own page + a formatted @thelivu teaser, and notifies Telegram
12. **Cuts a reel** — script (Claude Haiku) → narration in Anil's cloned voice (Chatterbox) → conceptual illustrations (FLUX) → ffmpeg
13. **Posts** the reel to Instagram and cross-posts to YouTube Shorts, in two daily slots (10:00 and 18:00 IST)

Steps 12-13 run on a separate always-on VM, not on Railway — reels need a voice server and ffmpeg.

**Two foundational rules:** (1) **facts come only from live sources, never from a model's training memory** — every skill is told today's date and instructed that sources always win; (2) **each skill is a validated function, not a chatbot** — it returns a structured block or the run halts loudly (`needs_attention`), so a stray conversational reply can never cascade or get published.

---

## Architecture

```
Railway: thelivu-agent (always-on)        Railway: thelivu (always-on)
┌────────────────────────────────┐        ┌──────────────────────────────┐
│ run.py — 2-min polling loop    │        │ bot.py — Telegram bot        │
│                                │        │ fileserver — serves reel MP4s│
│ every 2 min: owner topics      │        │ article pages — /a/<slug>    │
│ every 6h:    RSS + beat-monitor│        │                              │
│ daily:       chief-of-staff    │        │ /topic /runnow /queue /costs │
│ weekly:      scouts, tracker   │        │ /remake /pause /resume       │
│ 2x daily:    autopost sweep    │        └──────────────────────────────┘
│              10:00 · 18:00 IST │
└────────────────────────────────┘
        │                                  Oracle VM (always-on, ARM)
        │                                 ┌──────────────────────────────┐
        │                                 │ reel-worker — builds reels   │
        │                                 │ chatterbox  — cloned voice   │
        │                                 │ auto-pulls git hourly        │
        │                                 └──────────────────────────────┘
        ▼ shared
PostgreSQL on Railway                      Laptop: localhost:8600
pipeline_runs · reels · digs · publications └─ command centre (review + tap Post)
lead_queue · pending_topics · token_usage
engine_events · ig_media · kv_store
```

**Four hosts, one database.** Railway runs the engine and the public surface;
the Oracle VM builds reels (it needs a voice server and ffmpeg, which Railway
has neither of); the laptop is where you look and where you tap Post. Nothing
depends on the laptop being awake.

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

### Judgment / writing tier — Claude Sonnet 5
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
- **publishing/publish.py** — posts the article as its own page + a formatted channel teaser; pure Python, never an LLM (it must not alter substance). (The old `publisher` *skill* is dead — last call 2026-06-25.)
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

**No cross-engine fallback — pause, don't degrade.** If a provider is out of credit, the pipeline does **not** silently switch engines (e.g. run research on Claude's web-search, or judgment on a weaker model). Switching engines changes *how* facts are sourced and erodes the consistency of the flow. Instead, both providers behave the same way: the run pauses and the work goes back in the queue, resuming automatically when credit returns. Lead capture is cheap and keeps running throughout, so nothing is lost — a dead provider costs you time, never stories. (A no-search model is *doubly* barred from research: it can't ground facts at all.)

**Symmetric outage behavior.** Gemini down → research/verify pause, leads wait. Claude down → judgment/writing pause, leads wait. Either way the queue keeps filling and drains when the provider is back. Quota alerts hit Telegram immediately — 🟡 temporary, 🔴 billing — one per issue per day; a pause posts a ⏸ card.

---

## Reels — the reach surface

Every published story becomes a <90s vertical reel, narrated in Anil's own cloned
voice, and posted to Instagram + YouTube Shorts in two daily slots (10:00 and
18:00 IST, one reel per slot, oldest eligible first).

```
article ─► video-script (Claude Haiku 4.5) ─► Chatterbox (cloned voice)
                                           ─► FLUX illustrations (1 per beat)
                                           ─► ffmpeg ─► reels table ─► autopost
```

**The script model matters more than it looks.** It was on a free NVIDIA
reasoning model until 2026-09-08, which leaked its own chain-of-thought into
on-screen captions five separate times — reels shipped reading
`Cabinet(1) advice(2) required(3) = 3 words. Good.` Measured on one article:
that model leaked 6 captions out of 6; Haiku leaked 0 of 5, at ~$0.01 a reel.

**Illustrations** come from FLUX.1-dev (NVIDIA, free) with FLUX.1-schnell
(Cloudflare Workers AI, paid $5/mo) as an independently-hosted second provider —
same model family, shared infrastructure with neither. Capped at 40 images/day,
which is Cloudflare's included daily allowance, so the bill is $5 flat. If *both*
providers are down the reel is **not built** rather than shipped pictureless; the
run keeps no reel row, so the next poll rebuilds it once a provider recovers.

### The gates that replaced the human tap

Each of these exists because something bad shipped, and each **refuses** rather
than warns:

| Gate | Blocks | Because |
|------|--------|---------|
| self-talk detection | model reasoning in a caption or spoken line | five incidents, 2026-08-26 → 09-08 |
| number containment | a figure absent from the article | compression invents statistics |
| claim matching | a real figure attached to the wrong thing | `2 storeys` for a ground-plus-one building |
| 90-second ceiling | cuts that lose Reels-tab reach | a 118s reel reached Instagram |
| duplicate guard | a second reel for a story already posted | runs #121 and #154 were queued to post twice |
| daily image cap | more than 40 images/day | keeps the Cloudflare bill at exactly $5 |

The honest limit: these validate the artefact in front of them. The duplicate
guard exists because *none* of the others could see what had already been
published — that class of blindness was found by a human recognising a video,
not by a check.

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

- **Publishing is gated by code, not by a human tap.** The manual gate was removed 2026-08-29 — all volume autopublishes and reels autopost. What is non-negotiable is that a failed gate *refuses* rather than warning and shipping anyway.
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
| `ANTHROPIC_API_KEY` | Yes | Claude Sonnet 5 — judgment / writing; Haiku 4.5 — triage + reel scripts |
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

The **command centre** (`command_center/`, `localhost:8600`, password-gated) —
Starlette + a hand-rolled SPA, no new dependencies. Autostarts on login; reach it
from a phone over Tailscale.

| Tab | What you can do |
|-----|----------------|
| Gate / Stories | Read drafts, publish, kill, hold |
| Reels | Preview every cut, Post to Instagram, Edit caption, Remake, Kill |
| Digs | Persistent investigations and their logs |
| Sources | Active sources, pending proposals |
| Costs | Daily spend by model and skill |
| System | Pause/resume the engine, autopost hold, news-cycle hold |

*(The Streamlit dashboard this replaced was retired 2026-07 — see
`docs/plans/04-streamlit-retirement.md`. `dashboard.py` still exists but is dead.)*

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
