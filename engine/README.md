# News Engine — Skill Package

A modular, human-in-the-loop pipeline for surfacing **verified, high-impact, under-reported** news (Kerala first, India second). Twelve skills do the work — three ways a topic enters, one verification spine, and two discovery/maintenance workflows — and **you are the final guard** before anything publishes.

Governing document: [`CHARTER.md`](./CHARTER.md). The skills operationalise it; the charter wins any conflict. For the operator's-eye view and how to resume cold, start with [`START-HERE.md`](./START-HERE.md).

## The pipeline

Topics enter from **three lead sources**, then all flow through one verification spine to the human gate:

```
  curated channels                              ┌──────────────────┐  evidence  ┌─────────────────┐
  (source-ingestor + news-monitor) ┐            │ news-investigator │── dossier ─▶│ source-verifier │
  open web / primary feeds         ├─ leads  ──▶│  (+ context map)  │            │ (trust gate)    │
  (beat-monitor)                   │            └──────────────────┘            └────────┬────────┘
  your tips (topic-intake)         ┘                                                     │ KILL / HOLD /
                                                                                         │ FRAMING-FIX /
                                                                                         ▼ READY-FOR-HUMAN
  ┌──────────────────┐  post   ┌────────────────────┐  review  ┌──────────────┐  draft  ┌──────────────────┐
  │    publisher     │◀── ── ──│   ★ HUMAN GATE ★   │◀── ── ──│  editorial-   │◀── ── ──│  article-writer   │
  │ (Telegram, code- │ approve │  you approve/kill  │ verdict  │  reviewer     │         │ (+ pattern-check  │
  │  gated on human) │         └────────────────────┘          └──────────────┘         │  on verified dots)│
  └──────────────────┘                                                                  └──────────────────┘
```

Every lead — whatever its source — is **Tier 3 until the open web verifies it**. Each stage hands the next a **defined artifact**, so the chain is auditable.

## The twelve skills, by function

**Lead sources — three ways a topic enters (leads only, never verified copy):**

| Skill | Role |
|-------|------|
| `source-ingestor` (+ `scripts/ingest.py`) | Ingest a curated video/post → structured **Tier-3 lead** (transcript, claims, throughline) |
| `news-monitor` | Scan the curated channels (the tip line) → ranked **candidate queue** |
| `beat-monitor` | Scan the **open web + primary feeds** (courts, ECI, RBI, CAG, govt portals) → leads |
| `topic-intake` | Accept a topic **you** hand in, triage scope/worth, run it down the pipeline (may decline, and says why) |

**The verification spine — one lead becomes a publishable draft (or doesn't):**

| Stage | Skill | Input → Output |
|-------|-------|----------------|
| Investigate | `news-investigator` | a lead → **evidence dossier** (claims bucketed Fact / Allegation / Inference, + a context map of related threads) |
| Verify | `source-verifier` (+ `references/trust-score.md`) | the dossier → **verification report**, story-level verdict **KILL / HOLD / FRAMING-FIX / READY-FOR-HUMAN** (authority to fail the whole story) |
| Pattern-check | `pattern-synthesizer` | *verified* threads only → a labelled, falsifiable **hypothesis** — often "this pattern does not hold" |
| Write | `article-writer` | a `READY-FOR-HUMAN` story → **draft** in the transparent-perspective voice (adds no facts) |
| Review | `editorial-reviewer` | the draft → **editorial verdict** (framing, symmetry, defamation safety, confidence label) — the last *automated* gate |
| Publish | `publisher` (+ `scripts/publish.py`) | a **human-approved** draft → Telegram post (formats and logs; changes no meaning) |

**Discovery & maintenance:**

| Skill | Role |
|-------|------|
| `story-scout` | The proactive **dig** — works `watchlist.yaml`, one hypothesis at a time, from primary records. Catches what never surfaces on its own |
| `source-scout` | Weekly: nominate **new** candidate sources and audit existing ones into `sources.yaml` as `status: candidate`. Fights echo-chamber drift; a human activates |

## Why it's split this way

Separation is the safeguard. The investigator is allowed to be enthusiastic; the verifier is built to distrust it and may fail the whole story on its own authority; the pattern-synthesizer is held to a *higher* bar than single-story reporting because connected narratives are more persuasive when wrong; the reviewer ignores whether the facts are true and asks only whether the *writing* is fair, clean, and legally safe. No single stage can push a story to readers — and only the publisher can post, and only on an explicit human action. That's the structural reason this stays a newsroom and doesn't drift into a propaganda feed.

## The two hard guarantees

1. **The human gate stops every story that carries real legal exposure.** The `publisher` is the only stage that can post. As of 2026-08-16 (one-week trial, Anil) a story the reviewer explicitly clears of naming a real person alongside an allegation (`LEGAL-FLAG: NO`) publishes without a human tap — see `engine/agents/autopublish.py`. Anything else — a YES, or a missing/unparseable verdict — still requires explicit human action, same as before. The split is enforced in code and fails CLOSED: only an explicit NO clears the autonomous path.
2. **Under-coverage selects, it never confirms.** Obscurity tells the engine what to *look at*, never what to *believe*. Obscure claims clear a *higher* bar, not a lower one.

## Running it

These follow this environment's Agent Skills format (`SKILL.md` per folder), so they load in Claude Code or Cowork. Two ways to drive them:

- **Manual / on-demand:** invoke a skill at a time — e.g. "run today's Thelivu cycle on FYI", then "investigate lead 2", then "verify this dossier", then "review this draft". Good while you're tuning the charter — and the right mode for the current **validation phase**, where everything stops at the gate.
- **Routine / scheduled (Phase 2+):** wire the chain into a recurring task that runs the lead sources → investigate → verify → review and **drops finished candidates into a review queue** for you. It still stops at the gate; you read, approve, and only then run the publisher. Automation comes only after the validation week's gate is met — see [`DEPLOYMENT.md`](./DEPLOYMENT.md) and [`DRY-RUN-PLAYBOOK.md`](./DRY-RUN-PLAYBOOK.md).

## Tuning

Treat `CHARTER.md` as the source of truth and edit it first; the skills point back to it. If you change the corroboration bar (e.g. require a primary record for any claim naming a person), change it in the charter and in `source-verifier` (and its `references/trust-score.md`). Re-read the symmetry test in the charter every so often — it's the rule most likely to quietly erode. The `editorial-reviewer` also runs a **self-similarity / anti-monotony** check, so the engine doesn't keep landing on the same frame.

## Suggested first test

Run one real Kerala story end to end — monitor → investigate → verify → pattern-check → write → review — and read what lands at the gate. The useful question isn't "is the story good"; it's "did the verifier catch the weak claim, and did the reviewer flag the loaded phrase." If both did their job on a live example, the pipeline works. The before/after in [`examples/`](./examples/) is exactly this test, already run on the masala-bonds piece.
