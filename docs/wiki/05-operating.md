# 5. Operating it

## Daily glance (2 minutes)

1. Telegram: `/status` (engine state, queue, spend). The engine sends one daily health digest; silence on a day is itself a signal.
2. Command center `:8600` > Reels: anything `ready` for more than a day is stuck.
3. Command center > Investigation: source health and syntheses.

## Controls

| Want to | Do |
|---|---|
| stop everything | `/pause` (kv `engine_paused`); `/resume` |
| stop posting only | `/pauseposting`, `/resumeposting` (kv `autopost_paused`) |
| change daily model spend cap | `/setbudget` (kv `daily_budget_usd`, now 20) |
| run a news cycle now | `/runnow` |
| work when the APIs are dry | `./attend status`, `./attend cycle` (human-operated only; never cron) |
| post or remake a reel | command center Reels tab, or `/remake` |

Carousels are off (`carousels_paused=1`); reels are the only format going forward.

## Access

| System | How |
|---|---|
| Railway | `railway login` (browser), project `brave-determination`, services `thelivu-agent`, `thelivu`, `Postgres` |
| Production DB | `export DATABASE_URL=$(railway variables --service Postgres --json | python3 -c "import sys,json;print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")` |
| Reel VM | `ssh -i ~/.ssh/thelivu_oracle ubuntu@129.225.103.20` |
| Digger VM | `ssh -i ~/.ssh/thelivu_digger opc@129.225.67.115` |
| Logs | `railway logs --service thelivu-agent`; `journalctl -u reel-worker` / `animate-worker` / `digger` on the VMs |

**Deploy gotchas.** Railway deploys from GitHub `main`; the website is served by `thelivu-agent`, not `thelivu` (that is the bot), so
`railway up --service thelivu` is the wrong target. The reel VM follows `main` hourly. After a deploy, compare the live commit with
`git rev-parse HEAD`; `SUCCESS` alone can be the previous deploy.

## Costs

Models: Claude Haiku 5.5 does most work, Sonnet 5 for judgment, Gemini for grounding and video, free NVIDIA/Cloudflare models for
illustrations and health pings. Example day (21 Oct): about 1.3M Haiku, 0.4M Sonnet, 0.23M Gemini Flash tokens. The Claude billing cap was
hit daily until 11 Oct (alerts in `kv_store`); none since. Check spend with `/cost`.

## When X breaks

| Symptom | First look |
|---|---|
| nothing published for a day | `/status`; kv `engine_paused`, `autopost_paused`; quota breaker and budget governor messages in Railway logs |
| reel stuck `ready` | `journalctl -u animate-worker` on the reel VM; the claim-verifier or `textcheck` may have refused it |
| a source "silent for 3 cycles" | `source_checks` and `seen_items` for that source; many low-volume sources trigger this by design |
| Instagram errors | token refresh (`engine/agents/ig_token.py`), `IG_API_VERSION` |
| YouTube `invalid_grant` | while the OAuth app is in Testing mode the refresh token expires every 7 days: `python -m publishing.youtube_auth` |
| digger reports "fetched nothing" | see audit item on the stale digger VM |
