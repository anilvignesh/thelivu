# 6. Audit, 2026-10-22

Scope: all 164 Python files (about 42,000 lines of code, 9,600 of tests), the 2,600-line command-center front end, the three machines,
the production database. Method: lint and dead-code analysis (ruff, vulture), compile and import checks of every entry point, the full test
suite before and after each change, and live checks of the services and tables.

## Verdict

The system is healthy and producing: 47 stories published in 30 days, daily reel output, scouts and health checks running, cost under
control. The weaknesses are not in the editorial logic. They are in **operations hygiene**: code that exists on one machine only, a
worker running old code, unbounded tables, retired subsystems still in the tree, and documentation that has fallen behind.

## Fixed today (all committed, 28 of 29 test suites green before and after; the 29th needs a live API key)

| What | Why it mattered |
|---|---|
| `shared/db.py`: `log` was never defined | when stamping a Telegram delivery failed, the error handler raised `NameError` instead of logging, hiding the original failure |
| `thelivu_bot/bot.py`: `lstrip("-100")` | strips any of the characters `-`, `1`, `0`, not the prefix; a channel id whose digits begin with 1 or 0 produced a wrong post link |
| `orchestrator.py`: exception variable used in a lambda | `e` is unbound after the `except` block; now captured first |
| `reel_worker.py`: duplicate import | dead line removed |
| 41 unused imports and empty f-strings | lint noise |
| 19 dead functions, 348 lines | nothing referenced them (checked across code, tests, docs, scripts) |
| dataset-watch test fixture | the test had silently been failing since the "same subject" guard landed; budget vs expenditure is now deliberately a miss, fixture updated |
| tracked `.raj-backfill.log` | log file committed by accident; `*.log` now ignored |
| animate toolchain, auto-update script and units | existed only on the reel VM; copied into `ops/` |
| recurring-synthesis arithmetic (earlier today) | the Haryana lead summed unrelated findings |

## Open: needs a decision or an action

Ranked by risk.

1. **The digger VM runs a stale, hand-copied code snapshot** (Sep 10 to 14). It lacks `engine/digger/scout.py` and
   `jurisdictions/india.yaml`, and its `corpus.py` still has the 40 MB download cap that silently truncated the Rajasthan reports.
   Its own log says `cag-tamil-nadu` "fetched nothing at all" in 13 runs and `cag-jammu-kashmir` "is reading the wrong page"; Tamil Nadu has
   43 findings, the thinnest of 29 offices. There is no git on that box, so fixes never arrive. **Fix:** install git, clone the repo, and run the same hourly
   auto-update pattern the reel VM uses; then re-run the weak targets.
2. **Railway deploys are paused** (upstream incident). Last deploy 18 Oct; the website redesign, the synthesis fix and today's fixes are waiting.
   Nothing to do but wait; then confirm the live commit equals `HEAD`.
3. **Single copy of the renderer.** `~/animate` (renderer, 3 GB with pieces) is on one VM with no git. Tools are now backed up in `ops/animate-toolchain/`; the VM is
   still the only place the pieces run. Needs: the VM's `~/fwenv` and `/opt/pw` recipes in `provision.sh` so a rebuild is one command.
4. **Dead sources (fixed 2026-10-23).** Deccan Herald (silent since 19 Aug) and Newsclick (since 7 Aug) are now `inactive` in `sources.yaml`. Still open: the "silent for 3 cycles"
   alert fires daily for slow sources (The Ken, Alt News, TNM) and drowns the real ones. Fix: per-source expected cadence in `sources.yaml`, alert only on a
   breach. FYI Creator House (213 silent cycles) needs a human look.
5. **Lead backlog: not a problem (corrected 2026-10-23).** `expire_old_leads(7)` runs every daily cycle. Of 26,258 rows, the 1,716 `queued` ones are all from the last 7 days; the rest are `dropped` (24,218) or `processed` (324). My earlier reading was wrong.
6. **23 reels stuck `ready` for over a week** (old "illustrated" pipeline, Sep to Oct) will never post. Mark them `superseded`; decide whether the old reel pipeline
   (`reel.py`, `make_reel.py`, `reel_worker.py`, `reel_illustrated.py`, `reel_kinetic.py`, `belief_reel.py`) is retired now that animate covers it.
7. **Retired subsystems still in the tree**: at least 3,500 lines in the obvious files, plus their branches inside the orchestrator, bot and database layer: carousels (`engine/desks/ek/carousel.py`, `publishing/slides.py`, tables), the belief/"Everyone Knows"
   desks (retired 2026-09-08, "gated, not deleted", 79 call sites), the Streamlit `dashboard.py` (1,368 lines, retired 2026-07-30; plan 04 asks for Anil's confirmation before deleting),
   Telegraph helpers. They are inert but cost every reader and every future change.
8. **No CI, custom test runners.** 29 `run_*_cases.py` scripts, no pytest, no GitHub Actions. `command_center`, `thelivu_bot`, `ingestion` have zero tests. One suite
   (`run_gate_cases`) needs a live Anthropic key and "fails" offline.
9. **God modules.** `shared/db.py` 4,678 lines, `orchestrator.py` 2,863, `run.py` a 900-line tick. They work; they are the main source of change risk.
10. **Docs drift.** `PROJECT-STATUS.md` says its lower half is stale by about 90 commits; `engine/START-HERE.md` and `README.md` disagree with each other on the human gate.
    This wiki is the replacement; the older files need a "superseded by docs/wiki" header.
11. **Railway config-as-code is deprecated** (`railway.toml`), works until 2026-12-01. `ops/railway/railway.ts.proposed` exists.
12. **Content-quality items carried over**: ~64 unread corpus documents; Aizawl, Nagaland and Tripura re-reads; SEBI and Lok Sabha HTML decision; `IG_API_VERSION` bump.
13. **Small**: stray untracked files on the reel VM (`reel-worker.env.bak.*` holds secrets, `media/`); 3 GB of animate pieces and growing (disk 48%).

## Not a problem

Cost: no billing-cap alerts since 11 Oct. Health checks green except the primary illustration model (FLUX-dev on NVIDIA fails; the fallback works, and the daily image
cap was reached 3 times this week). Pipeline conversion is sensible. A pattern scan of tracked files found no API keys or tokens (only the `sk-ant-...` placeholder in `.env.example`).
