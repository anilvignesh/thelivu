# Learning loop — outcome-weighted priors for lead selection

*Context file, written before building (2026-07-14). Anil asked for "a
self-learning weighted model to tune the system for improvement".*

## What it is (and deliberately is not)

Every pipeline run already ends in a labelled outcome: **published** (the human
approved it), **killed** (trust gate or human), **held**. That's a growing
training set. The loop turns it into **decayed, smoothed publish-tendency
scores per feature** (source and theme), recomputed from the DB on demand, and
feeds the strongest signals into the two *selection* stages as an advisory
block.

It is deliberately **not** a neural network or an opaque optimiser:

- ~60 runs of data — a transparent weighted average is the honest model size.
- Every score is explainable ("theme:communal 0.2, n≈3" — killed 3 of 3).
- **It biases selection priority only. It must never touch verification, and
  it must never suppress a high-impact story because its theme historically
  died.** The spine (verify everything) is not a tunable.

## The model

- For each terminal run: outcome value published=1.0, killed/dropped=0.0,
  held=0.4 (a hold is "not ready", not "wrong").
- Recency decay: weight = 0.5^(age_days / 45) — the system "forgets" old
  behavior with a 45-day half-life, so it adapts as sources and seasons change
  (this is the self-learning part: every new outcome shifts the weights, and
  stale evidence fades on its own).
- Features per run: `source:<source>` and `theme:<bucket>` (keyword buckets
  over the throughline — see `_THEMES` in `engine/agents/learning.py`).
- Score per feature: Laplace-smoothed weighted mean
  `(Σ w·v + 2·0.5) / (Σ w + 2)` with effective n = Σ w. Features with
  n_eff < 1.5 are ignored (not enough evidence).

## Where it plugs in

| Point | What it gets |
|---|---|
| news-monitor prompt (lead selection) | "LEARNED PRIORS" block: top/bottom signals + the advisory rules |
| newsworthiness-gate prompt | same block (it decides pursue/drop at the floor) |
| `/priors` bot command | the same block, for the owner to inspect what the system currently believes |

The block always carries the guardrail text: advisory, tie-breaking only,
never verification, never suppress high-impact leads.

## The dig trigger (built in the same change)

`run_story_scout(theme_hint)` now accepts a target theme; the bot's
`/dig [theme]` sets kv `dig_request`, the orchestrator loop picks it up on the
next 2-minute tick and produces a targeted dig brief (card with the existing
"Investigate this now" button). No hint = the scout picks from the watchlist
as before.
