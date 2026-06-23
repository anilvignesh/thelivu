"""
Thelivu bot — always-on Telegram bot.

Handles the human approval gate:
  Anil taps [✓ Approve] → draft posts to @thelivu channel
  Anil taps [✗ Kill]    → story discarded
  Anil taps [⏸ Hold]   → story held; orchestrator retries in 3 days

Entry point: python -m thelivu_bot.bot
"""

import json
import logging
import sys
import time

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from shared.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_DRAFT_CHAT_ID,
)
from shared.db import get_run, get_pending_runs, get_cost_report_data, get_queue_state, kv_get, init_db, save_publication, update_run, queue_topic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("thelivu_bot")

_TG_LIMIT = 4096
_FOOTER = (
    "\n\n—\n"
    "Sources above. Drafted with AI assistance, reviewed by a human editor "
    "before publishing. Spotted an error? We correct openly — [contact]."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_chunks(text):
    chunks, current = [], ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= _TG_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(para) > _TG_LIMIT:
                chunks.append(para[:_TG_LIMIT])
                para = para[_TG_LIMIT:]
            current = para
    if current:
        chunks.append(current)
    return chunks


def _post_to_channel(text):
    """Post chunked text to the public channel. Returns list of message IDs."""
    if _FOOTER not in text:
        text += _FOOTER
    chunks = _split_chunks(text)
    msg_ids = []
    for chunk in chunks:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHANNEL_ID, "text": chunk},
            timeout=30,
        )
        r.raise_for_status()
        msg_ids.append(r.json()["result"]["message_id"])
        time.sleep(0.5)
    return msg_ids


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Thelivu bot active.\n"
        "Drafts will appear here with [Approve / Kill / Hold] buttons.\n"
        "Nothing reaches the channel without your tap."
    )


async def cmd_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import subprocess
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "Usage: /topic [your story idea or question]\n\n"
            "Example: /topic What happened to the Vizhinjam port deal with Adani?"
        )
        return
    queue_topic(topic, source="owner-telegram")
    await update.message.reply_text(
        f"On it. Investigating now — I'll send the draft when it's ready.\n\nTopic: {topic}"
    )
    subprocess.Popen(["python", "-m", "engine.agents.orchestrator", "--once"])
    log.info("Topic queued and pipeline triggered: %s", topic[:80])


async def cmd_runnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger the orchestrator immediately for any queued topic or RSS cycle."""
    await update.message.reply_text("Triggering pipeline now... I'll send the draft when it's ready.")
    import subprocess
    subprocess.Popen(["python", "-m", "engine.agents.orchestrator", "--once"])
    log.info("Manual pipeline trigger via /runnow")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from shared.db import _conn, _is_postgres
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        def count(status):
            cur.execute(f"SELECT COUNT(*) FROM pipeline_runs WHERE status = {ph}", (status,))
            return cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM publications")
        published = cur.fetchone()[0]
        pending = count("pending_human")
        held = count("held")
        killed = count("killed")
    finally:
        conn.close()
    await update.message.reply_text(
        f"Thelivu status:\n"
        f"  Pending your review: {pending}\n"
        f"  Published: {published}\n"
        f"  Held: {held}\n"
        f"  Killed: {killed}"
    )


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from shared.config import CHECK_INTERVAL_HOURS
    from datetime import datetime, timezone, timedelta

    state = get_queue_state()
    last_cycle = kv_get("last_cycle_at")
    lines = []

    # Owner topics
    topics = state["topics"]
    if topics:
        lines.append(f"Owner topics ({len(topics)}):")
        for t in topics:
            status = "🔄 running now" if t["status"] == "running" else "⏳ queued"
            lines.append(f"  #{t['id']} — {t['topic'][:80]} [{status}]")
    else:
        lines.append("Owner topics: none queued")

    lines.append("")

    # Recent pipeline runs
    runs = state["recent_runs"]
    if runs:
        lines.append("Recent runs:")
        for r in runs:
            date = str(r.get("created_at", ""))[:10]
            gate = r.get("trust_gate") or ""
            status = r.get("status", "")
            lines.append(f"  #{r['id']} [{date}] {r['throughline'][:70]}")
            lines.append(f"    → {gate} | {status} | src: {r['source']}")
    else:
        lines.append("No pipeline runs yet.")

    lines.append("")

    # Cycle timing
    if last_cycle:
        try:
            last_dt = datetime.fromisoformat(last_cycle)
            next_dt = last_dt + timedelta(hours=CHECK_INTERVAL_HOURS)
            now = datetime.now(timezone.utc)
            diff = next_dt - now
            mins = int(diff.total_seconds() / 60)
            if mins > 0:
                lines.append(f"Last cycle: {last_cycle[:16]} UTC")
                lines.append(f"Next cycle: in ~{mins // 60}h {mins % 60}m")
            else:
                lines.append("Next cycle: starting soon")
        except Exception:
            lines.append(f"Last cycle: {last_cycle[:16]} UTC")
    else:
        lines.append("No cycle has run yet. Use /runnow to trigger one.")

    await update.message.reply_text("\n".join(lines))


async def cmd_feeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import yaml
    from shared.config import SOURCES_YAML
    try:
        data = yaml.safe_load(SOURCES_YAML.read_text())
        sources = data.get("sources", [])
    except Exception as e:
        await update.message.reply_text(f"Could not read sources.yaml: {e}")
        return

    active = [s for s in sources if s.get("status") == "active"]
    candidates = [s for s in sources if s.get("status") == "candidate"]

    lines = [f"RSS feeds ({len(active)} active):\n"]
    for s in active:
        platform = s.get("platform", "")
        lean = s.get("lean", "")[:50]
        lines.append(f"  ✓ {s['name']} ({platform})")
        lines.append(f"    {lean}")

    if candidates:
        lines.append(f"\nCandidates (not yet active):")
        for s in candidates:
            lines.append(f"  ? {s['name']} — {s.get('notes','')[:60]}")

    lines.append("\nTo add a new source, use /addfeed [YouTube channel URL]")
    await update.message.reply_text("\n".join(lines))


async def cmd_addfeed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue a new YouTube channel for the source-scout to evaluate."""
    url = " ".join(context.args).strip() if context.args else ""
    if not url:
        await update.message.reply_text(
            "Usage: /addfeed [YouTube channel URL]\n\n"
            "Example: /addfeed https://www.youtube.com/@FactCheckIndia"
        )
        return
    queue_topic(f"EVALUATE SOURCE: {url}", source="owner-addfeed")
    await update.message.reply_text(
        f"Queued for source evaluation: {url}\n\n"
        f"The source-scout will check its reliability, lean, and beat coverage. "
        f"I'll report back when done."
    )
    log.info("Source evaluation queued: %s", url)


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _CLAUDE_IN  = 3.00;  _CLAUDE_OUT = 15.00
    _GEMINI_IN  = 0.30;  _GEMINI_OUT = 1.00
    _INR        = 84

    def calc(model, i, o):
        if "gemini" in model.lower():
            return (i/1e6*_GEMINI_IN) + (o/1e6*_GEMINI_OUT)
        return (i/1e6*_CLAUDE_IN) + (o/1e6*_CLAUDE_OUT)

    data = get_cost_report_data()
    rows = data["by_model"]
    runs_today = data["runs_today"]

    today_usd = month_usd = total_usd = 0.0
    lines = []
    for row in rows:
        m = row["model"]
        c = calc(m, row["today_in"] or 0, row["today_out"] or 0)
        today_usd += c
        month_usd += calc(m, row["month_in"] or 0, row["month_out"] or 0)
        total_usd += calc(m, row["total_in"] or 0, row["total_out"] or 0)
        lines.append(f"  {m}: ${c:.4f}")

    await update.message.reply_text(
        f"Thelivu costs:\n\n"
        f"Today: ₹{today_usd*_INR:.2f} (${today_usd:.4f})\n"
        f"This month: ₹{month_usd*_INR:.2f} (${month_usd:.4f})\n"
        f"All time: ₹{total_usd*_INR:.2f} (${total_usd:.4f})\n\n"
        + "\n".join(lines or ["No usage yet."]) + f"\n\nRuns today: {runs_today}"
    )


async def cmd_drafts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runs = get_pending_runs()
    if not runs:
        await update.message.reply_text("No drafts pending review right now.")
        return

    await update.message.reply_text(f"{len(runs)} draft(s) pending your review:")

    for run in runs:
        run_id = run["id"]
        throughline = (run.get("throughline") or "Untitled")[:120]
        date = str(run.get("created_at", ""))[:10]
        gate = run.get("trust_gate", "")

        text = f"#{run_id} — {throughline}\n{gate} | {date}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Approve", callback_data=f"approve_{run_id}"),
            InlineKeyboardButton("✗ Kill",    callback_data=f"kill_{run_id}"),
            InlineKeyboardButton("⏸ Hold",   callback_data=f"hold_{run_id}"),
        ]])
        await update.message.reply_text(text, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# Inline button callbacks (the human gate)
# ---------------------------------------------------------------------------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "approve_42"
    parts = data.split("_", 1)
    if len(parts) != 2:
        await query.message.reply_text("Unrecognised action.")
        return

    action, run_id_str = parts
    try:
        run_id = int(run_id_str)
    except ValueError:
        await query.message.reply_text("Bad run ID.")
        return

    run = get_run(run_id)
    if run is None:
        await query.message.reply_text(f"Run #{run_id} not found in database.")
        return

    if action == "approve":
        await _handle_approve(query, run_id, run)
    elif action == "kill":
        await _handle_kill(query, run_id)
    elif action == "hold":
        await _handle_hold(query, run_id)
    else:
        await query.message.reply_text(f"Unknown action: {action}")


async def _handle_approve(query, run_id, run):
    if run["status"] == "published":
        await query.message.reply_text(f"Run #{run_id} was already published.")
        return

    draft = run.get("draft_text") or ""
    if not draft:
        await query.message.reply_text(f"Run #{run_id} has no draft text. Cannot publish.")
        return

    try:
        msg_ids = _post_to_channel(draft)
    except Exception as e:
        await query.message.reply_text(f"Failed to publish: {e}")
        log.error("Publish failed for run #%d: %s", run_id, e)
        return

    save_publication(run_id, msg_ids, "Confirmed")
    update_run(run_id, status="published")

    # Remove the inline keyboard from the original summary message
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        f"Published run #{run_id} ✓\n"
        f"{len(msg_ids)} message(s) posted to {TELEGRAM_CHANNEL_ID}."
    )
    log.info("Published run #%d (%d chunks)", run_id, len(msg_ids))


async def _handle_kill(query, run_id):
    update_run(run_id, status="killed")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text(f"Story #{run_id} killed.")
    log.info("Killed run #%d", run_id)


async def _handle_hold(query, run_id):
    update_run(run_id, status="held")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text(
        f"Story #{run_id} held. The orchestrator will retry it in 3 days."
    )
    log.info("Held run #%d", run_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set.")
        sys.exit(1)

    init_db()
    log.info("Thelivu bot starting...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("feeds", cmd_feeds))
    app.add_handler(CommandHandler("addfeed", cmd_addfeed))
    app.add_handler(CommandHandler("drafts", cmd_drafts))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("topic", cmd_topic))
    app.add_handler(CommandHandler("runnow", cmd_runnow))
    app.add_handler(CallbackQueryHandler(button_callback))

    log.info("Polling for updates. Human gate active.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
