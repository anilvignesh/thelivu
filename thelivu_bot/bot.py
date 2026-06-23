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
from shared.db import get_run, init_db, save_publication, update_run, queue_topic

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
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "Usage: /topic [your story idea or question]\n\n"
            "Example: /topic What happened to the Vizhinjam port deal with Adani?"
        )
        return
    queue_topic(topic, source="owner-telegram")
    await update.message.reply_text(
        f"Topic queued. It will run at the next cycle (or trigger one now with /runnow).\n\n"
        f"Topic: {topic}"
    )
    log.info("Topic queued via Telegram: %s", topic[:80])


async def cmd_runnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger the orchestrator immediately for any queued topic or RSS cycle."""
    await update.message.reply_text("Triggering pipeline now... I'll send the draft when it's ready.")
    import subprocess
    subprocess.Popen(["python", "-m", "engine.agents.orchestrator"])
    log.info("Manual pipeline trigger via /runnow")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from shared.db import _conn
    with _conn() as c:
        pending = c.execute(
            "SELECT COUNT(*) FROM pipeline_runs WHERE status = 'pending_human'"
        ).fetchone()[0]
        published = c.execute(
            "SELECT COUNT(*) FROM publications"
        ).fetchone()[0]
        killed = c.execute(
            "SELECT COUNT(*) FROM pipeline_runs WHERE status = 'killed'"
        ).fetchone()[0]
        held = c.execute(
            "SELECT COUNT(*) FROM pipeline_runs WHERE status = 'held'"
        ).fetchone()[0]
    await update.message.reply_text(
        f"Thelivu status:\n"
        f"  Pending your review: {pending}\n"
        f"  Published: {published}\n"
        f"  Held: {held}\n"
        f"  Killed: {killed}"
    )


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
    app.add_handler(CommandHandler("topic", cmd_topic))
    app.add_handler(CommandHandler("runnow", cmd_runnow))
    app.add_handler(CallbackQueryHandler(button_callback))

    log.info("Polling for updates. Human gate active.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
