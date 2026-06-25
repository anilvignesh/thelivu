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
    CONTACT_HANDLE,
)
from shared.db import get_run, get_pending_runs, get_cost_report_data, get_queue_state, kv_get, init_db, save_publication, update_run, queue_topic, approve_proposal, skip_proposal, reset_run_for_review

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


def _strip_draft_scaffolding(text):
    """Drop the writer's review-only header so it never reaches the channel.

    article-writer prepends '# DRAFT — for human review' (sometimes inside a code
    fence). Skip leading blank lines, code fences, and that marker until the first
    line of real content (the standfirst)."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s == "" or s.startswith("```") or ("DRAFT" in s.upper() and "HUMAN REVIEW" in s.upper()):
            i += 1
            continue
        break
    return "\n".join(lines[i:]).strip()


def _prepare_for_publish(text):
    """Turn an approved draft into exactly what goes to the channel: strip the
    review scaffolding, ensure the standing footer is present exactly once, and
    fill the [contact] placeholder. Substance is never touched."""
    text = _strip_draft_scaffolding(text.strip())
    # The writer's sources block already carries the standing footer text; only
    # append the standalone footer when it is genuinely absent (avoid doubling).
    if "Drafted with AI assistance" not in text:
        text += _FOOTER
    text = text.replace("[contact]", CONTACT_HANDLE)
    return text


def _post_html_to_channel(html_text):
    """Post a single HTML-formatted message to the channel (the teaser). Web
    preview stays on so Telegram renders the Telegraph Instant-View card."""
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    r.raise_for_status()
    return [r.json()["result"]["message_id"]]


def _post_to_channel(text):
    """Post chunked text to the public channel. Returns list of message IDs."""
    text = _prepare_for_publish(text)
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
        f"Queued. The agent picks this up within 2 minutes — I'll send the draft when ready.\n\nTopic: {topic}"
    )
    log.info("Topic queued: %s", topic[:80])


async def cmd_runnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Signal the agent to run an RSS cycle on its next 2-minute tick."""
    from shared.db import kv_set
    kv_set("force_rss_run", "1")
    await update.message.reply_text("Signalled the agent to run an RSS cycle now. Check /track in a minute.")
    log.info("Force RSS run signalled via /runnow")


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


async def cmd_scoutnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import subprocess
    await update.message.reply_text("Running source scout now... I'll send proposals when done.")
    subprocess.Popen(["python", "-c",
        "from engine.agents.orchestrator import run_source_scout; run_source_scout()"])
    log.info("Manual source scout triggered")


async def cmd_track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show live status of the most recent pipeline run or a specific run ID."""
    from shared.db import _conn, _is_postgres

    run_id = None
    if context.args:
        try:
            run_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /track or /track [run_id]")
            return

    conn = _conn()
    try:
        cur = conn.cursor()
        if run_id:
            ph = "%s" if _is_postgres() else "?"
            cur.execute(
                f"SELECT id, throughline, source, status, trust_gate, created_at, updated_at "
                f"FROM pipeline_runs WHERE id = {ph}", (run_id,)
            )
        else:
            cur.execute(
                "SELECT id, throughline, source, status, trust_gate, created_at, updated_at "
                "FROM pipeline_runs ORDER BY id DESC LIMIT 1"
            )
        from shared.db import _fetchone
        run = _fetchone(cur)
    finally:
        conn.close()

    if not run:
        await update.message.reply_text("No pipeline runs found yet.")
        return

    STATUS_LABELS = {
        "investigating":  "🔍 Investigating sources...",
        "writing":        "✍️ Writing the draft...",
        "pending_human":  "📬 Ready for your review",
        "published":      "✅ Published",
        "killed":         "❌ Killed",
        "held":           "⏸ On hold",
        "kill":           "❌ Killed",
        "hold":           "⏸ On hold",
    }
    label = STATUS_LABELS.get(run["status"], run["status"])
    updated = str(run.get("updated_at", ""))[:16]

    msg = (
        f"Run #{run['id']}\n\n"
        f"Story: {(run.get('throughline') or 'TBD')[:100]}\n"
        f"Source: {run.get('source', 'N/A')}\n"
        f"Status: {label}\n"
        f"Trust gate: {run.get('trust_gate') or 'pending'}\n"
        f"Last updated: {updated} UTC"
    )

    if run["status"] == "pending_human":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Approve", callback_data=f"approve_{run['id']}"),
            InlineKeyboardButton("✗ Kill",    callback_data=f"kill_{run['id']}"),
            InlineKeyboardButton("⏸ Hold",   callback_data=f"hold_{run['id']}"),
        ]])
        await update.message.reply_text(msg, reply_markup=keyboard)
    else:
        await update.message.reply_text(msg)


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


async def cmd_republish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset a run that was already published (or wrongly marked published) back
    to review, then re-send the draft with Approve/Kill/Hold buttons.

    Recovery path for runs that left the human gate in error. The reset only
    touches the database — a bad post already on the channel must be deleted
    there by hand."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /republish [run_id]\n\n"
            "Resets a run back to review and re-sends the draft with buttons. "
            "Use it when a run was published in error and you want to approve it again."
        )
        return
    try:
        run_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /republish [run_id] — run_id must be a number.")
        return

    run = reset_run_for_review(run_id)
    if run is None:
        await update.message.reply_text(f"Run #{run_id} not found.")
        return

    draft = run.get("draft_text") or ""
    throughline = (run.get("throughline") or "Untitled")[:120]
    gate = run.get("trust_gate") or "pending"

    await update.message.reply_text(
        f"Run #{run_id} reset to review; any prior publication record was cleared.\n"
        f"⚠️ If a bad post reached the channel, delete it there by hand — this only resets the database.\n\n"
        f"Re-read the draft below, then tap to decide."
    )

    if draft:
        for chunk in _split_chunks(draft):
            await update.message.reply_text(chunk)
            time.sleep(0.3)

    summary = f"#{run_id} — {throughline}\n{gate} | ready for your decision"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✓ Approve", callback_data=f"approve_{run_id}"),
        InlineKeyboardButton("✗ Kill",    callback_data=f"kill_{run_id}"),
        InlineKeyboardButton("⏸ Hold",   callback_data=f"hold_{run_id}"),
    ]])
    await update.message.reply_text(summary, reply_markup=keyboard)
    log.info("Run #%d reset for re-review via /republish", run_id)


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
    elif action == "addsrc":
        await _handle_addsrc(query, run_id)
    elif action == "skipsrc":
        await _handle_skipsrc(query, run_id)
    else:
        await query.message.reply_text(f"Unknown action: {action}")


async def _handle_addsrc(query, proposal_id):
    source = approve_proposal(proposal_id)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    if source:
        await query.message.reply_text(
            f"Source added: {source['name']}\n"
            f"It will be picked up on the next RSS cycle."
        )
        log.info("Source approved: %s (#%d)", source["name"], proposal_id)
    else:
        await query.message.reply_text(f"Proposal #{proposal_id} not found.")


async def _handle_skipsrc(query, proposal_id):
    skip_proposal(proposal_id)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text(f"Source proposal #{proposal_id} skipped.")
    log.info("Source skipped: proposal #%d", proposal_id)


async def _handle_approve(query, run_id, run):
    if run["status"] == "published":
        await query.message.reply_text(f"Run #{run_id} was already published.")
        return

    draft = run.get("draft_text") or ""
    if not draft:
        await query.message.reply_text(f"Run #{run_id} has no draft text. Cannot publish.")
        return

    # The publisher is "deliberately the dumbest stage": it formats, posts, and
    # logs — it never alters the article's substance (see publisher/SKILL.md).
    # The draft the human reviewed and approved is exactly what gets posted; we
    # do NOT run a free-form LLM over an approved article (that risks rewriting
    # it, and once posted a conversational meta-message instead of the article).
    #
    # Preferred presentation: a clean Telegraph Instant-View page + a short HTML
    # teaser in the channel. If anything in that path fails, fall back to the
    # chunked plain-text post — approval must never hard-fail.
    prepared = _prepare_for_publish(draft)
    how = "teaser"
    try:
        import publishing.telegram as tg_render
        teaser, url = tg_render.render(prepared, CONTACT_HANDLE)
        msg_ids = _post_html_to_channel(teaser)
        log.info("Published run #%d via Telegraph: %s", run_id, url)
    except Exception as e:
        log.warning("Telegraph path failed for run #%d (%s) — falling back to plain text", run_id, e)
        how = "plain-text"
        try:
            msg_ids = _post_to_channel(draft)
        except Exception as e2:
            await query.message.reply_text(f"Failed to publish: {e2}")
            log.error("Publish failed for run #%d: %s", run_id, e2)
            return

    save_publication(run_id, msg_ids, "Confirmed")
    update_run(run_id, status="published")

    # Remove the inline keyboard from the original summary message
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        f"Published run #{run_id} ✓ ({how})\n"
        f"{len(msg_ids)} message(s) posted to {TELEGRAM_CHANNEL_ID}."
    )
    log.info("Published run #%d (%s, %d msgs)", run_id, how, len(msg_ids))


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

async def _post_init(app):
    from telegram import BotCommand
    try:
        await app.bot.set_my_commands([
            BotCommand("topic",    "Submit a story to investigate now"),
            BotCommand("track",    "Check status of current or recent story"),
            BotCommand("drafts",   "List all drafts pending your review"),
            BotCommand("republish","Reset a published run back to review by id"),
            BotCommand("queue",    "What's running, queued, and when next cycle fires"),
            BotCommand("runnow",   "Trigger an RSS cycle immediately"),
            BotCommand("feeds",    "List active RSS sources"),
            BotCommand("addfeed",  "Add a YouTube channel for evaluation"),
            BotCommand("scoutnow", "Run source scout to find new sources"),
            BotCommand("status",   "Story counts: pending / published / held / killed"),
            BotCommand("cost",     "API spend today / month / all-time in ₹"),
        ])
        log.info("Bot command menu registered.")
    except Exception as e:
        log.warning("Could not set bot commands (rate limit?): %s", e)


def main():
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set.")
        sys.exit(1)

    init_db()
    log.info("Thelivu bot starting...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("track", cmd_track))
    app.add_handler(CommandHandler("feeds", cmd_feeds))
    app.add_handler(CommandHandler("addfeed", cmd_addfeed))
    app.add_handler(CommandHandler("scoutnow", cmd_scoutnow))
    app.add_handler(CommandHandler("drafts", cmd_drafts))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("topic", cmd_topic))
    app.add_handler(CommandHandler("runnow", cmd_runnow))
    app.add_handler(CommandHandler("republish", cmd_republish))
    app.add_handler(CallbackQueryHandler(button_callback))

    log.info("Polling for updates. Human gate active.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
