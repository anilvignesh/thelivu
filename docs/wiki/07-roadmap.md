# 7. Roadmap

Order is by what protects the channel first, then what grows it. Effort is Claude's working time with Anil approving.

## Now (next few days)

| # | Item | Effort | Needs |
|---|---|---|---|
| 1 | Deploy the website redesign and today's fixes once Railway is back; confirm live commit equals `HEAD` | 15 min | Railway |
| 2 | Put the digger VM on git with an hourly auto-update; re-run the weak targets (Tamil Nadu, J&K, Rajasthan) with the 150 MB fix | 1 to 2 h | Anil: OK to touch the VM |
| 3 | Per-source silence cadence in `sources.yaml` (dead sources already marked inactive 2026-10-23) | 1 h | nothing |
| 4 | Mark the unreviewed `ready` old-pipeline reels (about 24) `superseded` | 5 min | your yes on retiring the old reel pipeline |
| 5 | Publish the Haryana "SDRF uninvested four years running" story through the article desk | 1 h | nothing |

## Next (2 to 4 weeks)

1. **Delete the retired code** in three PRs, each followed by the full suite: dashboard + Streamlit, carousels, belief desks. At least 3,500 lines gone, more once their call sites go. Needs Anil's yes on each.
2. **Decide the old reel pipeline's fate.** If animate covers every case, retire `reel_worker` and the Manim/illustrated styles; one reel path, one verification story.
3. **Real tests, real CI**: move the runners to pytest, add a GitHub Action that runs them offline, add smoke tests for the bot and command center.
4. **Split `shared/db.py`** by domain (runs, corpus, reels, ops) behind the same import names, no behavior change.
5. **Reel quality loop**: first animate reel with the new look and captions; watch retention in `ig_media_metrics`; tune the first two seconds.
6. **Website**: finish the rollout to `/bio`, `/terms`, `/privacy`; one authored motion; add the "records" view fed from `findings`.

## Later

1. **Corpus depth**: read the remaining documents, then second countries via `jurisdictions/<country>.yaml`.
2. **Long-form pilot** (HyperFrames or the current renderer), after reels are stable.
3. **Domain** at 1,000 followers (now 37). Then footer, sign-off and article links switch from `thelivu.up.railway.app`.
4. **Railway IaC migration** before 2026-12-01.
5. **Alerting**: one daily digest only, per-source cadence, mute rules; Telegram stays the control surface.

## Decisions waiting for Anil

1. Delete retired subsystems (dashboard, carousels, belief desks)? 
2. Retire the old reel pipeline?
3. (Closed: lead expiry already runs at 7 days; `kv_store` is only 630 rows, no job needed.)
4. OK to modify the digger VM?
