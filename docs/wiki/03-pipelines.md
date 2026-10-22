# 3. Pipelines

## A. News desk (`engine/skills`, run by `engine/agents/orchestrator.py`)

```
feeds + tips + channels -> lead_queue -> newsworthiness gate -> investigate -> verify (KILL / HOLD / READY)
   -> pattern check -> write -> editorial review -> publish sweep -> article page + Telegram + bio link
   -> reel (animate) -> Instagram + YouTube Shorts
```

- **Leads**: 52 sources in `engine/sources.yaml`: 16 active, 34 candidates nobody has reviewed, 2 inactive (The Hindu National and Kerala, India Today, Business Standard, Medianama, TNM, Alt News, The Ken, OCCRP and others), polled by the news cycle into `lead_queue` / `seen_items`.
- **The spine** is one skill per stage (`engine/skills/<stage>/SKILL.md`), run through `skill_runner.py`. The verifier is the trust gate; a KILL or HOLD stops the story.
- **Outcomes** (last 30 days, verified): 47 published, 11 sent on to reels, 9 held, 2 killed. About 2 to 9 stories published per day.
- **Publish sweep** (`engine/distribution/sweep.py`): autopublishes what clears review, no human tap, including named-person stories (Anil's explicit decision, 2026-08-29). The guard is code.
- **Learning**: decayed, smoothed priors on source and theme (`engine/agents/learning.py`) and on posting time (`timing.py`). Advisory only; they never touch verification.

## B. Public-records desk (the digger)

```
digger (free models, digger VM) -> documents (full text) -> findings (grounded, quoted) -> syntheses (4 detectors)
   -> leads -> a human or Claude reads -> article / reel
```

- `engine/digger/loop.py` fetches CAG reports for 29 offices into `documents`. Targets come from `jurisdictions/india.yaml`.
- `engine/corpus.py` keeps the whole text; `engine/attend_corpus.py` is the attended reader (an assistant reads chunks and writes findings; no API spend). 3,663 findings over 338 documents in production.
- `engine/synthesis.py` detectors: same objection in N years (`recurring`), same failure in N states (`structural`), a finding never named again (`no-follow-through`), a figure growing every year (`wrong-direction`). Arithmetic only, every row cites finding ids. Output is a lead, not a story.
- `engine/digger/scout.py` re-checks every source daily and records `source_checks`. It proposes, never activates or deactivates.
- `engine/digger/dataset_watch.py` watches government tables by arithmetic.

## C. Reels (animate)

```
published article  -> publishing/animate/articles.py -> story.json (script + claims tied to passages, verified)
audit finding set  -> publishing/animate/auto.py     -> story.json
story.json (approved) -> animate worker -> build piece -> voice (Chatterbox clone) -> render (headless Chrome + ffmpeg)
   -> review + textcheck -> reel row `ready` -> auto-posts at the next slot if every gate is clean -> Instagram + YouTube
```

- Scenes are canvas drawings from `publishing/animate/lib/scenes.js` (the "dossier" look): illustration, timeline, excerpt, compare, share, figure, list, source, signoff, with burned-in word-timed captions.
- Every figure, date and excerpt is checked against the cited passages before anything renders; a claim-verifier reads every spoken line.
- The **old reel pipeline** (`publishing/reel*.py`, `make_reel.py`, `reel_worker.py`) still runs on the VM for runs the new one does not cover. Decision pending (see roadmap).
- 169 reels in the table: 96 posted, 32 `ready`, the rest killed or superseded. 9 of the `ready` rows are animate reels waiting for the next slot; 23 are older than a week and will never post (see audit).

## D. Long-form video (`publishing/longform*.py`)

Occasional: a script is written only when a story would be damaged by the 90 second ceiling, rendered on the VM, uploaded to YouTube from Railway (the VM holds no posting credentials). 4 rows ever; dormant.

## E. The website (`publishing/fileserver.py` and friends)

Server-rendered Python pages, no build step, no CDN: `/` feed (`feedpage.py`), `/a/<id>-<slug>` articles (`articlepage.py`), `/bio` link list, `/terms`, `/privacy`, `/reel/<id>.mp4`. New shared look in `publishing/sitestyle.py` (Archivo self-hosted, status blocks). Reads are counted without cookies or IPs (`publishing/reads.py`).

## F. Control surfaces

- **Telegram bot** (`thelivu_bot/bot.py`): about 40 commands, e.g. `/status /queue /held /pause /resume /pauseposting /kill /runnow /remake /longform /cost /setbudget`. Full list: `MANUAL.md`.
- **Command center** (`command_center/`, :8600): runs, reels, ops, reach, investigation view, beliefs. Posting always sits behind an explicit confirm.
