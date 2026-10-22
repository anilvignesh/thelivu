# 2. How it runs

## The four places code runs

| Place | What runs there | How code gets there | State (verified 2026-10-22) |
|---|---|---|---|
| **Railway** project `brave-determination` | `thelivu-agent`: `run.py`, the brain (a tick every ~2 min) plus the public website on :8080. `thelivu`: the Telegram bot (`python -m thelivu_bot.bot`). `Postgres`: the one database | GitHub `main` auto-deploys | running. **Deploys are paused by a Railway upstream incident**: last deploy 18 Oct, so every commit since is waiting (incl. synthesis fix `6a022a4` and the website redesign) |
| **Oracle reel VM** `ubuntu@129.225.103.20` (aarch64, 12 GB, ssh key `~/.ssh/thelivu_oracle`) | `reel-worker` (old reel loop plus long-form), `animate-worker` (timer, every 30 min: builds reels from story files), `chatterbox` voice server (started on demand, stopped when idle), the **animate toolchain** `~/animate` | `thelivu-auto-update.timer` does `git pull` hourly and restarts services | healthy, 48% disk |
| **Oracle digger VM** `opc@129.225.67.115` (945 MB, key `~/.ssh/thelivu_digger`) | `digger.service`: the Tier-0 loop that reads CAG reports into the corpus, one target per ~20 min | **manual rsync**, no git on the box | running but on a **stale code snapshot** (see audit) |
| **Anil's laptop** (Pop!_OS) | the command center (`command_center/`, :8600, reachable over Tailscale), attended mode (`./attend`) when the APIs are dry, development | local checkout `~/thelivu` | on demand |

Secrets live in Railway variables. The reel VM gets its own copy through `ops/oracle-vm/deploy-secrets.sh`, run from the laptop. The VM holds no
Railway credential.

## What the brain does each tick (`run.py`, service `thelivu-agent`)

Order matters; cheap checks that use no paid model come first so they keep working when budgets or providers are down.

1. Kill switch (`engine_paused`), cost report, carousel cleanup.
2. **No-model checks**: Instagram and YouTube insight sync, Instagram token refresh, API/model/illustration health checks, daily health digest, the publish sweep.
3. **Quota breaker** (`shared/quota.py`): a hard provider failure (out of credit) skips every model stage until it expires.
4. **Budget governor** (`shared/budget.py`): stops model stages at the daily cap (`daily_budget_usd` = 20) until UTC midnight.
5. Model stages: topic queue (one topic per tick through the spine), RSS news cycle (interval `CHECK_INTERVAL_HOURS`, default 6), beat monitor, story scout and tracker, chief of staff, tech steward, dig advance, auto re-check of held stories, long-form scripting (last, one per tick).
6. Idle alert if no news cycle completed in 8 hours.

A restart mid-run parks the interrupted run as `needs_attention` rather than resuming it. There is no resume.

## The scheduled jobs outside the tick

| Job | Where | Cadence |
|---|---|---|
| Digger cycle | digger VM | one target per ~20 min (`sleeping 1198s`) |
| Source scout | Railway tick | daily |
| animate-worker (articles, auto, worker) | reel VM timer | every 30 min |
| reel-worker | reel VM loop | continuous; releases the 4.5 GB voice server when idle |
| auto-update | reel VM timer | hourly |
| Reel posting | sweep, learned time slots (`engine/distribution/timing.py`) | two daily slots |

## How a change reaches production

| Change in | Goes live by |
|---|---|
| `engine/`, `shared/`, `publishing/` web pages, bot | push to `main`, Railway redeploys (paused right now) |
| reel scenes (`publishing/animate/lib/scenes.js`), `publishing/` render code | reel VM `git pull` within the hour; **already-built piece folders keep their old copy of scenes.js** |
| `~/animate/tools` (renderer) | edit on the VM, then copy into `ops/animate-toolchain/` and commit |
| digger code | `ops/oracle-vm/deploy-digger.sh` from the laptop (manual) |
