---
name: publisher
description: Post a human-approved article to the Thelivu Telegram channel, attaching the confidence label and standing footer and logging the publication. Use only after a human has reviewed and approved a draft and explicitly asks to publish or post it. This is the final stage and it runs ONLY on explicit human action — nothing upstream may trigger it. It formats and posts; it never alters the article's substance and never publishes on its own.
---

# Publisher

The **final stage**. It takes an article the human has approved and posts it to the Thelivu channel, where it reaches subscribers. It is deliberately the dumbest stage in the system: it does no judgement, adds no facts, changes no meaning. It formats, posts, and logs.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## The one rule

**It runs only on explicit human approval, by human action.** This is the gate the whole engine exists to protect. No upstream stage, schedule, or routine may invoke publishing. The human reviews the draft, decides, and triggers the post themselves. The publish credential (the bot token) is the human's, kept apart from the rest of the pipeline so that automation literally cannot reach it.

The reference script (`scripts/publish.py`) enforces this with an interactive confirmation that cannot be flagged away — by design. If you ever feel tempted to remove that prompt to "save a step," that is the moment to stop: the step is the point.

## What it does

1. **Verify the draft is approved** — it must be marked approved by the human and carry its sources.
2. **Attach the standing furniture** if not already present:
   - the **confidence label** (Confirmed / Developing / Contested),
   - the **footer, verbatim**: *"Sources above. Drafted with AI assistance, reviewed by a human editor before publishing. Spotted an error? We correct openly — [contact]."*
3. **Post to the channel** — splitting long articles to fit Telegram's limit, or (better) publishing to Telegraph for clean long-form rendering and posting the link.
4. **Log the publication** — id, title, message ids, timestamp, confidence — to the published log, so corrections can find it later.

## What it must never do

- Publish without an explicit human trigger.
- Alter the article's wording or meaning — it formats and appends only.
- Post a draft that lacks sources or the footer.
- Hold the bot token anywhere an automated process can reach it.

## Corrections

A correction is issued the same way — by human action. Edit the channel post (or append a clearly-marked correction), and write a record to the corrections log with what was wrong and what was fixed. Corrections are fast and open; never a silent deletion. This is also your regulatory takedown/grievance path — keep it operable within a few hours.

## Setup (one time)

- Create the bot with **BotFather**; save the token as `TELEGRAM_BOT_TOKEN` (kept separate from model API keys).
- Create the Thelivu channel; add the bot as an **admin with post permission**.
- Set `TELEGRAM_CHANNEL` to the channel (e.g. `@thelivu`).

## Reference

`scripts/publish.py` — takes an approved draft, appends the furniture, asks for interactive human confirmation, posts to the channel, and writes the published-log record.
