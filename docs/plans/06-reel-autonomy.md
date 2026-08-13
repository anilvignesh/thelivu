# Plan 06 — Reel autonomy (auto-render, off the laptop)

**Goal:** a reel gets built automatically for every published run — no one has to
open the command center and click "Make reel" — and the render no longer needs
Anil's laptop to be on. The human gate is untouched: **Post reel** stays a manual
tap in the command center, exactly as today.

## Why this and not ElevenLabs

Discussed 2026-08-12. The actual blocker to publishing daily isn't voice quality
or TTS cost — it's two things:
1. **Script generation is already automatic and free** — `THELIVU_REEL_MODE`
   defaults to `nvidia` (`shared/config.py`), which calls free hosted Gemma 4 via
   NVIDIA. This has been true since 2026-07-26 (`docs/reel-button.md`). Nothing to
   build here.
2. **Nobody triggers the build.** `publishing/make_reel.py::make_narrated_reel()`
   only ever runs when a human clicks "🎬 Make reel" in the command center — there
   is no auto-trigger on publish. And that click has to happen on Anil's laptop,
   because Chatterbox (`127.0.0.1:3901`) and the ffmpeg render both run locally
   there (`command_center` itself is a local process — Tailscale-reachable from
   the phone, but the machine still has to be on).

So the fix is: (a) something triggers the build automatically when a run
publishes, and (b) that something isn't the laptop. ElevenLabs would only have
solved a cost/quality question that was never the actual constraint — swapping
Chatterbox for it wouldn't have removed either blocker above.

## Design — one Oracle Free Tier VM, two co-located services

```
Railway (unchanged)              Oracle VM (new, Always Free ARM)
┌─────────────────┐              ┌─────────────────────────────────┐
│ engine tick      │              │ chatterbox_server.py :3901       │
│ Postgres         │◄────DB─────►│   (127.0.0.1 only — never public)│
│ fileserver       │   network    │ reel_worker.py                   │
└─────────────────┘              │   polls Postgres, calls           │
                                  │   make_narrated_reel() in-process,│
                                  │   voice via localhost:3901,       │
        ▲                        │   script+FLUX via NVIDIA API,     │
        │ Tailscale              │   ffmpeg local, save_reel() back  │
        │                        │   to Postgres over the network    │
   Anil's phone/laptop            └─────────────────────────────────┘
   (command center, Post-tap
    only — unchanged)
```

**Why co-locate instead of just moving Chatterbox:** if only the voice server
moves, `make_reel.py`'s orchestration (the actual laptop dependency) still has to
run somewhere — and today that's the laptop. Putting `reel_worker.py` on the same
box removes the laptop from the loop entirely, and keeps Chatterbox bound to
`127.0.0.1` — no public port, no auth surface, no risk of an open endpoint
speaking in Anil's cloned voice. The command center doesn't change: it already
reads reels from the shared `reels` table (`command_center/api/media.py`) with no
idea which process built them, so auto-built reels just show up in the Reels tab,
`status='ready'`, waiting for the Post tap.

## Build

1. **`publishing/reel_worker.py` (new).** Loop (systemd, restart-always):
   - Query Postgres: runs with `status='published'` and no `reels` row that is
     `ready`/`posted`/pending-retry (skip `killed` — that's an explicit no).
   - For each: pull the carousel's `dark` flag + build `article_url` the same way
     `command_center/api/media.py::make_reel()` does (`{SLIDE_SERVER_BASE_URL}/a/{slug}`).
   - Call `make_narrated_reel(rid, dark=dark, article_url=article_url, mode="nvidia")`
     directly — same function the button calls, untouched.
   - Log outcome; on `ok:False` (voice down, FLUX failure beyond the fallback
     threshold, etc.) back off and retry next poll rather than looping tight on a
     broken run.
   - Poll interval: every 10 min is plenty — this isn't latency-sensitive.
2. **`publishing/make_reel.py` — no change needed, verified.** `CHATTERBOX_HEALTH`
   is `127.0.0.1:3901`, still correct once co-located. `_ensure_voice()` health-
   checks first (3s timeout) and only shells out to the laptop launcher
   (`~/.jarvis/reel-voice.sh start`) if that fails — on the VM the launcher won't
   exist, but `os.path.exists()` catches that instantly and returns a clean error,
   it doesn't hang. Since systemd keeps Chatterbox up, this path shouldn't fire in
   practice; if it ever does (a restart mid-request), the worker just logs and
   retries next poll.
3. **Env on the VM:** same pull-from-Railway pattern as `command_center/run.sh`
   (`railway variables --json`) — needs `DATABASE_PUBLIC_URL`, `NVIDIA_API_KEY`,
   `SLIDE_SERVER_BASE_URL`. Nothing else; posting stays out of this box entirely
   (no `IG_ACCESS_TOKEN` on the worker — it only builds, never posts).
4. **Chatterbox on the VM** — same `publishing/chatterbox_server.py`, unmodified,
   `CBX_PORT=3901`, bound to `127.0.0.1` explicitly (not `0.0.0.0`). Reference clip
   (`~/thelivu_voice_ref2.wav`) copied over once.
5. **Fonts + ffmpeg on the VM** — `NotoSerifMalayalam-Bold` / `NotoSansMalayalam-*`
   (illustrated-reel frame builder asserts on these — plan 02) + `ffmpeg` via apt.

## Constraints / invariants carried over unchanged

- **Post reel stays the human gate** — `reel_worker.py` never calls
  `post_reel_run`. It only builds and saves as `status='ready'`.
- **No Claude credit spent** — stays on `mode="nvidia"`, same as the button's
  default today. Do not flip to `THELIVU_REEL_MODE=api` as part of this.
- **`engine/attend.py` is not touched** — irrelevant to this path; nvidia mode
  never routes through attend.
- **All-or-nothing illustrated fallback, hook validation, notes handling** — all
  inside `make_narrated_reel`, untouched by calling it from a new caller.
- Chatterbox never gets a public port. If a future need requires reaching it from
  off-box, that's a new decision (shared-secret header, security-list rule) — not
  assumed here.

## Test

1. Scratch: point `DATABASE_URL` at a scratch Postgres/SQLite, seed one
   `status='published'` run with no reel, run `reel_worker.py` once (not as a
   loop), confirm a `reels` row appears `status='ready'` and the command center
   (pointed at the same scratch DB) shows it in the Reels tab with a working
   preview.
2. Prod, read-mostly: run the worker once by hand against prod Postgres with a
   single already-published run that has no reel yet, confirm it builds and shows
   up in the real Reels tab as `ready`. Anil reviews and posts (or kills) by hand
   — do not let the worker's first run auto-post anything.
3. Confirm Chatterbox is unreachable from outside the VM (`curl` from the laptop
   to the VM's public IP:3901 should fail/timeout, not connect).
4. Let it run unattended for a few days, watch for a run that never gets picked
   up (stuck query) or a run that gets rebuilt repeatedly (poll query not
   excluding in-flight/ready reels correctly).

## Status (2026-08-12)

- `publishing/reel_worker.py` — **built, scratch-tested** (candidate discovery,
  carousel-mood lookup, killed-reel exclusion, retry-after-failure all verified
  against a scratch SQLite DB with `venv/bin/python -m publishing.reel_worker --once`).
  `make_reel.py` needed no changes — verified its failure paths already degrade
  cleanly rather than hang.
- `ops/oracle-vm/` — provisioning script, systemd units, and the secrets-deploy
  script are written and syntax-checked. Runbook: `ops/oracle-vm/README.md`.
- **Blocked on:** the VM itself (`docs/oracle-vm-setup.md` — needs Anil's
  phone/card for OCI signup). Once the IP exists, steps 2-5 in the ops README
  finish this end to end.
