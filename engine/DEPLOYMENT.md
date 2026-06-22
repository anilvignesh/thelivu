# Deployment Checklist (build AFTER validation)

This is the plan, captured so it's portable — **not** a thing to build now.
Standing up automation before the validation week proves the pipeline means
automating something unproven. Build these only once `DRY-RUN-PLAYBOOK.md`'s
gate is met. Full design rationale is in `SYSTEM-DESIGN.md` §6, §8, §11.

Each phase has a **gate** — don't start it until the gate is met.

---

## Phase 1 — Validation (current)
*Gate to leave: a week where no false/defamatory claim ever reached a finished
draft, and your gate catches were polish, not saves.*
- [ ] Run the daily dry runs; fill `dry-run-log.md`.
- [ ] Encode each recurring miss as a charter/skill rule.

## Phase 1.5 — Pre-launch (one-time, before anything goes public)
- [ ] Secure handles: `@thelivu` Telegram bot + channel (and fallbacks).
- [ ] Verify the YouTube `channel_id`s in `sources.yaml`.
- [ ] **Media lawyer's read** — defamation, IT Rules 2021, the Feb-2026 AI-labelling
      rule, the draft creator-regulation (`SYSTEM-DESIGN.md` §8).
- [ ] Create the bot with BotFather; add it to the channel as admin (post perms).
- [ ] Stand up the **correction/grievance contact** and put it in the footer.
- [ ] Confirm the AI-assistance disclosure is on every piece.

## Phase 2 — Assisted automation
*Gate to start: validation passed. Gate to leave: a week of auto-drafts where your
edits are minor and nothing false slipped through.*
- [ ] Get API keys: Anthropic + Gemini (free tiers first). Note: these are separate
      from the Pro subscription and the consumer Gemini plan.
- [ ] Automate **ingest + verify** only; drafts land in a review queue (a private
      Telegram drafts chat, Slack, or a doc). **Publish stays manual.**
- [ ] Wire `publish.py` for the manual post step (keep the human-confirm prompt).
- [ ] Hosting: your Mac, or a small VPS (~$5/mo) if you want it off your laptop.
- [ ] (Optional) Public tip line — a simple form + dedicated contact, funnelling into
      `topic-intake`. Requires first: a published tips policy (tips are leads, we
      verify, we protect sources), a source-protection plan, and legal sign-off.
      Open only after validation — never during it. Start simple (form + email);
      reserve a SecureDrop-style channel for genuinely high-risk whistleblowers.

## Phase 3 — Scheduled
*Gate to start: Phase 2 stable. Gate to leave: stable cost, low correction rate,
sustainable queue volume.*
- [ ] Orchestrator: n8n (self-host) or cron + scripts — your comfort.
- [ ] RSS-notify: a tiny job that pings you when a watched source posts.
- [ ] Schedule the chain monitor→…→review to drop candidates in the review queue.
- [ ] Still human-gated publish. Always.
- [ ] Set a daily spend cap with alerting; cache transcripts and verifications.

## Phase 4 — Scale
*Gate to start: Phase 3 stable without gate erosion.*
- [ ] Activate more sources from `sources.yaml`; let the scout nominate weekly.
- [ ] Solve the Instagram ingestion path (Graph API or manual) before relying on IG.
- [ ] Extend the beat toward India.
- [ ] Recruit a second human reviewer before volume outpaces one gatekeeper.

---

## The rule that outranks the checklist

Every phase keeps the human gate and the verification bar intact. If a deployment
step would weaken either to gain speed or reach, it doesn't ship. Scaling a leaky
pipeline only scales the leak.
