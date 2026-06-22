# Thelivu

**Kerala, explained — with the evidence.**

This repository is the source-of-truth for Thelivu: a human-gated, AI-assisted
explainer and accountability news operation, Kerala-first and India-second.

## What's here

- **`engine/`** — the full news engine: the editorial charter, twelve skills, the
  source registry and the investigative watchlist, the scripts, and the operating
  docs. **Start with [`engine/START-HERE.md`](engine/START-HERE.md)** — it boots
  any fresh assistant into running the whole thing.
- **`articles/`** — the work. `drafts/` holds pieces awaiting the human gate;
  `published/` holds what has actually gone out.

## Status

**Pre-launch.** Validation phase: review only — nothing is published, nothing is
automated. See `engine/DRY-RUN-PLAYBOOK.md`. During this phase, everything in
`articles/drafts/` is exactly that: a draft awaiting a human decision.

## How it works, in one line

Three lead sources — curated channels, an open-web/primary-feed beat-monitor, and
owner-or-public tips — feed one pipeline (investigate → verify → write → review →
**human gate** → publish), alongside a proactive *dig* (`engine/skills/story-scout`)
that unearths under-told stories from primary records.

## A note on version history

Article history in this repo doubles as Thelivu's **corrections trail** — what
changed, and when. The transparency promise, kept by default.
