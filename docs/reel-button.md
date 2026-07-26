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

## How the script is produced — `config.REEL_MODE`
The video-script is a **post-gate** model step (it transforms an already verified +
human-approved article, so it never touches the trust gate — which is why a cheap/free
model here is a deliberate engine choice, not the silent fallback the charter forbids).
Three modes:

- **`nvidia`** (default, ACTIVE since 2026-07-26) — free hosted **Gemma 4 31B** via
  NVIDIA (`NVIDIA_API_KEY`; model overridable with `NVIDIA_SCRIPT_MODEL`). Own key, so
  it's independent of the Anthropic/Gemini quota breaker and needs no attended process:
  the **dashboard button just works** (script free, then voice + video render locally —
  needs the voice server up, takes a few minutes). ~3-min cold-start on the free tier.
  This is what took reels off "attended-only" — no Claude credit needed.

- **`attended`** — the script is handed to the human-driven terminal session (`./attend
  reel <run_id>`); **no API.** Use when you want a human writing the script. The
  dashboard (non-attended) returns `needs_terminal` with that command instead of running
  the model step. `./attend reel` reuses the carousel's dark/light mood.

- **`api`** (KEPT but INACTIVE) — `mode="api"` calls Claude via `run_structured_skill`,
  guarded by the quota breaker. Deliberately **not deleted**; flip back with
  `THELIVU_REEL_MODE=api` when Claude credit is a non-issue.

None of the three touches the trust gate or the human publish gate.

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
