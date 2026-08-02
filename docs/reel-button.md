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

## Where to watch a build (added 2026-08-02)

The **Activity** view in the command center — live progress, the current stage, elapsed
time, and the full stage timeline per job; failures show the error. The build runs
server-side, so closing the modal, reloading, or switching to the phone all keep it
visible. `make_narrated_reel`'s existing `progress` callback is what feeds it, unchanged.
See `docs/command-center-v2.md` § Activity.

## Requirements to actually build one
- The **Chatterbox voice server** up on the laptop: `~/.jarvis/reel-voice.sh start`
  (on-demand, ~2GB resident, not autostart). `make_narrated_reel` fails fast with this
  command if it's down.
- Rendering is CPU-bound and slow — ~15-20 min for a ~6-beat / ~55s reel. Expect it.
- Posting needs `IG_USER_ID` / `IG_ACCESS_TOKEN` (same as carousels).

## Remake suggestions (added 2026-07-30)

A remake used to be a pure re-roll: the modal collected only `run_id` + `dark`, so
nothing carried the owner's reaction to the cut he had just watched. The reel modal now
has a **suggestion box** — "What to change" on Remake — and the notes travel to the one
place that can act on them, the video-script step.

- `make_narrated_reel(..., notes=…)`; `_notes_block()` builds the delimited
  `OWNER REVISION NOTES` block and it is appended to the **script prompt for both
  engines** (`script_input = draft + _notes_block(notes)`) — the notes must not reach
  Gemma but not Claude depending on which mode is live.
- **Notes are direction, not licence.** The block restates that the skill's hard rules
  outrank every note: no procedural upgrades, no claim/number/quote the article doesn't
  carry, no process narration, and if a note asks for something the article doesn't
  support, follow the article. This is stated rather than assumed because the reel is
  **post-gate** — nothing re-verifies it after the Post tap, and "punch up the hook" and
  "say they won the bill" arrive through the same textarea. (Reel #12 overstated a tabled
  Bill as passed on the generator's own; notes must not reopen that door.)
- Notes are **stored on the reel** (`reels.notes`) — shown on the card, and prefilled
  into the next Remake, because a second remake is usually the first note plus one more.
- Ignored for the prompt when an explicit `script=` is supplied (a hand-corrected script
  is already the final word) — still recorded on the reel.
- Attended parity: `./attend reel <run_id> --notes "…"`.
- The legacy Streamlit `dashboard.py` was deliberately left alone — the command center
  supersedes it; `notes` defaults to None so that path is unaffected.

**Also fixed here:** `/assets/*` now sends `Cache-Control: no-cache`. The SPA has no
bundler/hash step, so the browser was heuristically caching `app.js` and serving the
previous build — the new modal shipped to the server and wasn't in the tab. `no-cache`
means revalidate, not never-cache; the ETag still makes an unchanged file cheap.

## Pacing + the hook (2026-07-30)

Three invariants the render path now holds. Full measurements in `PROJECT-STATUS.md`.

- **The zoom spans the beat.** `_zoom_expr(frames)` derives the increment from the beat's
  own length. A fixed increment against a fixed ceiling ran out at 4.44s and froze the
  rest of every 6-12s beat (45-55% of a reel). `ZOOM_MAX` is the single knob; raise it for
  more visible movement, but check the caption margins first — captions sit near the edges
  and travel is what crops them.
- **A long beat gets 2-3 pictures.** `build_reel(shots_per_beat=[...])` subdivides the
  *video* only; the VO is one continuous take per beat, so `_split_duration` must sum to
  exactly the beat duration or the picture drifts against the voice. `TARGET_SHOT_SECS`
  and `MAX_SHOTS_PER_BEAT` live in `publishing/reel.py`; `_plan_shots` estimates each
  beat's length from its word count at 147wpm *before* synthesis (a bad estimate changes
  shot lengths, never sync). Sub-shots reuse the beat's own scene with a different seed —
  a beat is one idea, and the second picture is another view of it, not a new claim.
  **Do not "fix" pacing by shortening the spoken lines**: compression is where reel #12
  overstated a tabled Bill, so that trades verification for retention.
- **No reel renders without a hook.** `_has_hook` (line-anchored, requires actual words)
  is the ONE predicate; it guards the nvidia generator, `run_structured_skill`'s marker
  and a post-parse check on `parse_script`'s new `hook` field. Beware `\s` in the script
  regexes — it matches newlines, and a bare `HOOK:` used to capture BEAT 1's sentence.

## Not to do
- Do **not** automate `./attend reel` (cron / Railway / `claude -p`). It is attended
  because a human is present; the blocking wait is the boundary, not a rough edge.
- Do **not** add a second NVIDIA retry loop. `shared/nvidia.py::call_with_retry` is the
  one, used by the script step, the FLUX illustrations and `skill_runner._run_nvidia`.
  It retries 5xx/timeouts, fails fast on 4xx, and must never trip the paid quota breaker.
- Do **not** re-enable the API route as the default without a deliberate owner call —
  the whole point of `REEL_MODE=attended` is that reels don't spend API credit.
