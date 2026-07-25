# The carousel → reel button (command center)

A **Reels row on every carousel card** in the dashboard (Carousels tab) that builds
and posts a narrated reel — Anil's cloned voice — of the same story as the carousel.
This is the orchestration that closed the "reels built but not wired in" gap: before
it, `save_reel` had zero callers and every reel was a hand-built CLI one-off.

## The two stages (the human gate is unchanged)
1. **🎬 Make reel** — generate the video-script → voice it (Chatterbox) → render
   (ffmpeg) → store the MP4 in the DB (`reels`, status `ready`). **Not public.**
2. **📤 Post reel** — `post_reel_run` → Instagram. This is the gated tap: you preview
   the reel, then post it. Nothing reaches Instagram until you click Post.

Same shape as the carousel flow (compose → preview → post).

## Attended-only for now (the model step never hits the API)
`config.REEL_MODE` switches how the video-script (a model step) is produced:

- **`attended`** (default, ACTIVE) — the script is handed to the human-driven terminal
  session; **no API is used.** Because that handoff can only happen inside an attended
  process (where the blocking wait is the compliance boundary — see
  `docs/attended-mode.md`), the dashboard button (a *non-attended* process) does **not**
  run the model step. It returns the exact terminal command instead:

      ./attend reel <run_id>

  That command renders the reel locally (voice + ffmpeg), stores it `ready`, and you
  preview + post from the dashboard. `./attend reel` reuses the carousel's dark/light
  mood so the reel matches its carousel.

- **`api`** (KEPT but INACTIVE) — `make_narrated_reel(..., mode="api")` calls Claude
  directly via `run_structured_skill`, guarded by the quota breaker. The route was
  deliberately **not deleted**, only switched off (owner's call, 2026-07-25). Flip it
  back with `THELIVU_REEL_MODE=api` or `mode="api"` when API credit is a non-issue.

## Pieces
- `publishing/make_reel.py` — `make_narrated_reel(run_id, *, dark, article_url,
  progress, mode)`. The one shared orchestration (get_run → route model step →
  voice-check → script → `build_reel(backend="chatterbox")` → `save_reel`). Never
  raises for expected failures; returns a result dict the UI renders.
- `publishing/reel.py` — `build_reel(..., backend=)` / `_synth(..., backend=)` override
  the module `TTS_BACKEND` (env binds at import, so callers force `chatterbox` here).
- `shared/db.py` — `get_reel_for_run(run_id)` (latest reel per run, for the card state).
- `engine/attend.py` — `./attend reel <run_id>` (the attended build path).
- `dashboard.py` — the Reels row (batch-queried like the slide thumbnails).

## Requirements to actually build one
- The **Chatterbox voice server** up on the laptop: `~/.jarvis/reel-voice.sh start`
  (on-demand, ~2GB resident, not autostart). `make_narrated_reel` fails fast with this
  command if it's down.
- Rendering is CPU-bound and slow — ~15-20 min for a ~6-beat / ~55s reel. Expect it.
- Posting needs `IG_USER_ID` / `IG_ACCESS_TOKEN` (same as carousels).

## Not to do
- Do **not** automate `./attend reel` (cron / Railway / `claude -p`). It is attended
  because a human is present; the blocking wait is the boundary, not a rough edge.
- Do **not** re-enable the API route as the default without a deliberate owner call —
  the whole point of `REEL_MODE=attended` is that reels don't spend API credit.
