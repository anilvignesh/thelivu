# Thelivu — Deploy to Railway (one-time setup)

Four things to do before the system can run: BotFather, API keys, Railway project, and the cron service. Takes about an hour.

---

## Step 1 — Create the Telegram bot (BotFather)

1. Open Telegram → search `@BotFather` → start a chat.
2. Send `/newbot`. Follow prompts. Name: `Thelivu`, username: `@thelivu_bot` (or a fallback).
3. BotFather gives you a **token** — save it (`TELEGRAM_BOT_TOKEN`).
4. Add your new bot to your **@thelivu channel** as an admin with "Post messages" permission.
5. Start a **private chat** with your bot (just send `/start`).
6. Get your private chat ID:
   ```
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
   ```
   Look for `"chat": {"id": <number>}` — that's `TELEGRAM_DRAFT_CHAT_ID`.

---

## Step 2 — Get API keys

| Key | Where |
|-----|-------|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| `GEMINI_API_KEY` | aistudio.google.com/app/apikey (optional) |
| `BRAVE_API_KEY` | api.search.brave.com (optional; free tier = 2000 req/month) |

---

## Step 3 — Deploy to Railway

1. Push this repo to GitHub (already done: it's private).
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
3. Select this repo. Railway auto-detects `railway.toml` and starts the **bot service**.
4. Add a **volume**: Railway dashboard → your service → **Volumes** → add volume, mount at `/data`.
5. Add **environment variables** in Railway → Variables (copy from `.env.example`, fill in values):
   - `ANTHROPIC_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_DRAFT_CHAT_ID`
   - `TELEGRAM_CHANNEL_ID`
   - `DB_PATH=/data/thelivu.db`
   - `GEMINI_API_KEY` (if you have it)
   - `BRAVE_API_KEY` (if you have it)
6. Railway deploys. Check **Logs** tab — you should see `Thelivu bot starting... Polling for updates.`

---

## Step 4 — Add the cron agent service

This is the daily pipeline runner. It triggers at 8am IST (02:30 UTC).

1. In Railway dashboard → your project → **New Service** → **GitHub repo** → same repo.
2. In the new service settings:
   - **Start command:** `python -m engine.agents.orchestrator`
   - **Cron schedule:** `30 2 * * *`
3. Add the same environment variables as the bot service (or link them).
4. Add the same volume (mount at `/data`) so both services share the SQLite DB.

---

## Step 5 — Verify it works

```bash
# Install Railway CLI
npm install -g @railway/cli
railway login

# Trigger the agent manually (don't wait for 8am)
railway run --service thelivu-agent python -m engine.agents.orchestrator
```

Check your Telegram private chat — a draft message with [✓ Approve] [✗ Kill] [⏸ Hold] should arrive.

Tap **⏸ Hold** to test the flow (don't publish yet — validation week first).

---

## Validation week

You're not in production mode yet. During this week:
- Let the agent run daily.
- Read each draft + verification report in Telegram.
- Tap **⏸ Hold** or **✗ Kill** — never Approve.
- Log each run in `engine/dry-run-log.md`.
- Gate: after 5-7 cycles where no false claim reaches a finished draft and your corrections are minor polish, start approving.

---

## Cost estimate (1 article/day)

| Item | Cost/month |
|------|------------|
| Railway bot service | ~$5 (~420 INR) |
| Anthropic API (30 articles × ~$0.50) | ~$15 (~1250 INR) |
| Gemini API | Free tier covers 1 video/day |
| Brave Search | Free tier (2000 req/month) |
| **Total** | **~₹1670/month** |

Well within the ₹5000 budget. At ₹10,000 you can run 3–4 sources daily.
