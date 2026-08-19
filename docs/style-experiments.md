# Style experiments — the presentation-style bandit

*Context file, written before/alongside building (2026-08-19). Anil's
framing: reach isn't opposed to editorial seriousness, it's a precondition
for staying independent, so an "animation = unserious" heuristic was retired.
He delegated the experiment cadence to the engine: "I will let you decide
the cycle."*

## What it is (and deliberately is not)

Every reel already gets real post-performance data (`ig_media_metrics`,
append-only reach/likes/comments/saved/shares snapshots, synced ~every 6h).
This loop turns that into a small **bandit** that picks which renderer draws
the *next* reel, biased toward whichever presentation style is actually
earning engagement — and keeps sampling the others so the picture doesn't
freeze on an early lead.

It is deliberately **not**:
- A/B split by fixed schedule. Reach is noisy per-post (topic, time of day,
  algorithm mood) — a bandit that reacts to real signal beats a rigid
  50/50 split at this data volume (a few dozen posts).
- A full RL setup. The action space is a handful of hand-built renderers,
  not a continuous one — epsilon-greedy over decayed weighted means is the
  honest model size, same reasoning as `engine/agents/learning.py`.
- A lever on anything editorial. It only chooses which renderer draws the
  frame. Verification, sourcing, legal gate, story selection are untouched.

## The model

`engine/agents/style_learning.py`:
- **Outcome metric**: engagement rate = (likes+comments+saved+shares)/reach,
  from each reel's *latest* metrics snapshot. Rate, not raw reach — raw reach
  is dominated by timing/algorithm variance that has nothing to do with the
  visual style; rate isolates "did the presentation make people engage."
  (Anil's account-level reach target is a separate, system-wide thing this
  doesn't touch — see `docs/reach-analytics.md`.)
- **Maturity gate**: posts younger than `MATURITY_DAYS` (5) are excluded
  entirely, not scored low — a 2-day-old post's numbers are still climbing.
- **Recency decay**: half-life 21 days (faster than editorial learning's 45 —
  a format effect should show up within a couple of weeks of posts, not a
  season of them).
- **Cold-start rule**: any style with fewer than `MIN_EFFECTIVE_N` (3.0)
  decayed samples is always picked over trusting a thin score — new styles
  get exercised before they're judged, not starved by an early leader.
- **Explore rate**: once every style has enough data, 30% of picks still go
  random rather than always to the current best — keeps it adaptive if a
  style's performance drifts (new format novelty wearing off, audience
  composition shifting).

## Where it plugs in

`publishing/make_reel.py::make_narrated_reel()` calls `choose_style()` right
before `save_reel()`, tagging the reel's `presentation_style` column. The
renderer branch on that tag doesn't exist yet beyond the default — see
"Current styles" below.

| Point | What it gets |
|---|---|
| `reels.presentation_style` | which renderer drew this reel — set at build time |
| `/priors` bot command | `format_style_report()` — decayed engagement rate per style, for the owner to inspect |

## Current styles (2026-08-19)

- `static` — the only one that exists: FLUX-illustrated stills, Ken Burns
  pan, progressive caption reveal. Everything posted so far backfills as this
  style (`DEFAULT 'static'` on the column), so existing data is a valid
  baseline, not thrown away.
- `kinetic` (in progress) — motion-graphics layer on top of the same FLUX
  stills (animated emphasis, stat count-ups, more expressive motion than a
  static pan). Building on **Manim Community** (MIT, actively maintained,
  CPU-only — no GPU/API spend, fits the budget cap) rather than hand-rolled
  ffmpeg, including its `manim-voiceover` plugin for syncing motion to the
  Chatterbox narration track that already exists. The moment this ships and
  its name is added to `AVAILABLE_STYLES`, the bandit above starts routing
  reels to it automatically — no other wiring needed.
- Character/stick-figure animation is a real future direction, not a fantasy
  build: `facebookresearch/AnimatedDrawings` (MIT, auto-rigs a single drawn
  figure — but archived, so it'd be vendored and maintained by us) and
  `lukerbs/pytoon` + `DanielSWolf/rhubarb-lip-sync` (audio-driven mouth/body
  animation off audio we already generate) are the concrete leads, evaluated
  2026-08-19. Scoped as its own prototype once `kinetic` has real data.

## Guardrail carried in the module docstring

This never touches verification, sourcing, or the legal gate — it only
decides which renderer draws the frame. Same spirit as the learning loop's
"the spine is not a tunable."
