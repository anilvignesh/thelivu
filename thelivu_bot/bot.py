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
from shared.db import get_run, get_pending_runs, get_cost_report_data, get_queue_state, kv_get, kv_set, init_db, save_publication, update_run, queue_topic, approve_proposal, skip_proposal, reset_run_for_review, get_recheckable_runs, clear_agents_for_run, clear_stale_agents, clear_stale_topics, deactivate_approved_source, get_approved_sources, queue_carousel_run, get_carousel_run, update_carousel_run, get_carousel_slides

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
    from datetime import datetime, timezone
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"

        def count(status):
            cur.execute(f"SELECT COUNT(*) FROM pipeline_runs WHERE status = {ph}", (status,))
            return cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM publications")
        published = cur.fetchone()[0]
        pending  = count("pending_human")
        held     = count("held")
        killed   = count("killed")
        writing  = count("writing")
        investig = count("investigating")

        # Active agents (non-ghost)
        if _is_postgres():
            cur.execute("SELECT skill, run_id, started_at FROM active_agents WHERE started_at > NOW() - INTERVAL '30 minutes' ORDER BY started_at")
        else:
            cur.execute("SELECT skill, run_id, started_at FROM active_agents WHERE started_at > datetime('now', '-30 minutes') ORDER BY started_at")
        live_agents = cur.fetchall()

        # Ghost agents (>30 min)
        if _is_postgres():
            cur.execute("SELECT COUNT(*) FROM active_agents WHERE started_at < NOW() - INTERVAL '30 minutes'")
        else:
            cur.execute("SELECT COUNT(*) FROM active_agents WHERE started_at < datetime('now', '-30 minutes')")
        ghost_count = cur.fetchone()[0]

        # Stuck topics
        cur.execute("SELECT COUNT(*) FROM pending_topics WHERE status='running'")
        stuck_topics = cur.fetchone()[0]

        # Latest run
        cur.execute("SELECT id, status, LEFT(throughline, 60) FROM pipeline_runs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        latest = f"#{row[0]} [{row[1]}] {row[2]}" if row else "none"

    finally:
        conn.close()

    lines = [
        "Thelivu pipeline status:",
        f"  Pending review: {pending}",
        f"  Writing: {writing}  |  Investigating: {investig}",
        f"  Held: {held}  |  Killed: {killed}  |  Published: {published}",
        "",
        f"Latest run: {latest}",
        "",
    ]

    if live_agents:
        lines.append(f"Active agents ({len(live_agents)}):")
        now = datetime.now(timezone.utc)
        for ag in live_agents:
            skill, run_id, started = ag
            elapsed = int((now - started.replace(tzinfo=timezone.utc)).total_seconds() / 60) if started else "?"
            lines.append(f"  {skill} (run #{run_id}) — {elapsed}m ago")
    else:
        lines.append("Active agents: none")

    if ghost_count:
        lines.append(f"  ⚠️ Ghost agents (>30m): {ghost_count} — run /clearghosts")
    if stuck_topics:
        lines.append(f"  ⚠️ Stuck topics (running state): {stuck_topics} — run /clearghosts")

    await update.message.reply_text("\n".join(lines))


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
            stale = t.get("stale") or t.get("stale", False)
            if t["status"] == "running" and stale:
                status = "⚠️ stuck (run /clearghosts)"
            elif t["status"] == "running":
                status = "🔄 running now"
            else:
                status = "⏳ queued"
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
    kv_set("force_scout_run", "1")
    await update.message.reply_text(
        "Signalled the agent to run a source scout now.\n"
        "Proposals will arrive in a few minutes — watch this chat."
    )
    log.info("Source scout signalled via /scoutnow")


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
    _FLASH_IN   = 0.30;  _FLASH_OUT  = 1.00
    _PRO_IN     = 1.25;  _PRO_OUT    = 5.00
    _INR        = 84

    def calc(model, i, o):
        m = (model or "").lower()
        if "gemini" in m:
            if "pro" in m:
                return (i/1e6*_PRO_IN) + (o/1e6*_PRO_OUT)
            return (i/1e6*_FLASH_IN) + (o/1e6*_FLASH_OUT)
        return (i/1e6*_CLAUDE_IN) + (o/1e6*_CLAUDE_OUT)

    data = get_cost_report_data()
    rows = data["by_model"]
    runs_today = data["runs_today"]

    today_usd = month_usd = total_usd = 0.0
    lines = []
    for row in rows:
        m = row["model"] or "unknown"
        c = calc(m, row["today_in"] or 0, row["today_out"] or 0)
        today_usd += c
        month_usd += calc(m, row["month_in"] or 0, row["month_out"] or 0)
        total_usd += calc(m, row["total_in"] or 0, row["total_out"] or 0)
        if c > 0 or (row["today_in"] or 0) > 0:
            lines.append(f"  {m}: ${c:.4f}")

    await update.message.reply_text(
        f"Thelivu costs:\n\n"
        f"Today:      ₹{today_usd*_INR:.2f} (${today_usd:.4f})\n"
        f"This month: ₹{month_usd*_INR:.2f} (${month_usd:.4f})\n"
        f"All time:   ₹{total_usd*_INR:.2f} (${total_usd:.4f})\n\n"
        + "\n".join(lines or ["No usage today."]) + f"\n\nRuns today: {runs_today}"
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
        gate = run.get("trust_gate", "") or "?"
        legal = " ⚠️ LEGAL" if run.get("legal_flag") else ""

        text = f"#{run_id} — {throughline}\n{gate}{legal} | {date}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Approve", callback_data=f"approve_{run_id}"),
            InlineKeyboardButton("✗ Kill",    callback_data=f"kill_{run_id}"),
            InlineKeyboardButton("⏸ Hold",   callback_data=f"hold_{run_id}"),
        ]])
        await update.message.reply_text(text, reply_markup=keyboard)


async def cmd_held(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List held stories the owner can ask to re-develop."""
    runs = get_recheckable_runs()
    if not runs:
        await update.message.reply_text("No held stories right now.")
        return
    await update.message.reply_text(
        f"{len(runs)} held stor(y/ies). Tap to re-investigate fresh, or use /recheck <id>:"
    )
    for run in runs:
        run_id = run["id"]
        throughline = (run.get("throughline") or "Untitled")[:120]
        date = str(run.get("created_at", ""))[:10]
        gate = run.get("trust_gate") or "held"
        # Show why it was held: trust gate decision + reason if available
        gate_label = {
            "HOLD": "⏸ verifier: needs more sources",
            "FRAMING-FIX": "🔧 verifier: framing issue",
            "held": "⏸ held by you",
            "hold": "⏸ held by verifier",
            "PAUSED": "⏸ provider was down",
            "NEEDS-ATTENTION": "⚠️ halted (bad output)",
        }.get(gate, f"⏸ {gate}")
        text = f"#{run_id} [{date}] {throughline}\n{gate_label}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Re-check now", callback_data=f"recheck_{run_id}"),
            InlineKeyboardButton("✗ Kill",         callback_data=f"kill_{run_id}"),
        ]])
        await update.message.reply_text(text, reply_markup=keyboard)


async def cmd_recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flag a held story for a fresh re-investigation (the agent does it next tick)."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /recheck <run_id>\n\n"
            "Re-investigates a held story from scratch against today's live sources "
            "and brings back a fuller draft if it has developed enough to publish. "
            "Use /held to see held stories."
        )
        return
    try:
        run_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /recheck <run_id> — run_id must be a number.")
        return
    await _request_recheck(update.message, run_id)


async def _request_recheck(message, run_id):
    run = get_run(run_id)
    if run is None:
        await message.reply_text(f"Run #{run_id} not found.")
        return
    if run.get("status") not in ("held", "hold"):
        await message.reply_text(
            f"Run #{run_id} isn't held (status: {run.get('status')}). Only held stories can be re-checked."
        )
        return
    update_run(run_id, status="recheck_requested")
    await message.reply_text(
        f"Re-check queued for #{run_id}. The agent will re-investigate it from scratch "
        f"on its next tick and send back a fuller draft if it's developed enough to publish."
    )
    log.info("Recheck requested for run #%d", run_id)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: reset a stuck run back to 'held' so it can be /recheck'd or killed.

    Useful when a run is frozen at 'investigating' or 'writing' due to a provider
    crash — resets it to held and clears any ghost active_agent entries."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /reset <run_id>\n\n"
            "Resets a run stuck at 'investigating' or 'writing' back to 'held', "
            "clears ghost agents, and makes it available for /recheck or /kill.\n\n"
            "Use /track <id> first to check the current status."
        )
        return
    try:
        run_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /reset <run_id> — run_id must be a number.")
        return

    run = get_run(run_id)
    if run is None:
        await update.message.reply_text(f"Run #{run_id} not found.")
        return

    status = run.get("status", "")
    if status in ("published",):
        await update.message.reply_text(
            f"Run #{run_id} is already published — use /republish if you need to review it again."
        )
        return
    if status in ("killed",):
        await update.message.reply_text(
            f"Run #{run_id} is killed. Reset it anyway? Tap to confirm:",
        )

    old_status = status
    clear_agents_for_run(run_id)
    update_run(run_id, status="held")

    throughline = (run.get("throughline") or "N/A")[:120]
    await update.message.reply_text(
        f"✅ Run #{run_id} reset.\n\n"
        f"Story: {throughline}\n"
        f"Was: {old_status} → now: held\n\n"
        f"Ghost agents cleared. Use /held to recheck it, or tap Kill if it's not worth retrying."
    )
    log.info("Run #%d reset to held (was: %s) via /reset", run_id, old_status)


async def cmd_clearghosts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: clear all stale active_agents (>30min old) and reset stuck 'running' topics."""
    cleared_agents = 0
    cleared_topics = 0
    try:
        clear_stale_agents()
        cleared_agents = 1  # clear_stale_agents doesn't return count; just run it
    except Exception as e:
        await update.message.reply_text(f"Error clearing agents: {e}")
        return
    try:
        cleared_topics = clear_stale_topics()
    except Exception as e:
        await update.message.reply_text(f"Error resetting stuck topics: {e}")
        return

    await update.message.reply_text(
        f"🧹 Ghost cleanup done.\n\n"
        f"Stale active_agents cleared (all >30min old)\n"
        f"Stuck pending_topics reset to queued: {cleared_topics}\n\n"
        f"Use /status to check the pipeline state."
    )
    log.info("Ghost cleanup done via /clearghosts; %d stuck topics reset", cleared_topics)


async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kill a run by ID from text — no need to go through /republish first."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /kill <run_id>\n\nKills a held, stuck, or pending run. "
            "Use /held or /track <id> first to confirm you have the right one."
        )
        return
    try:
        run_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /kill <run_id> — run_id must be a number.")
        return
    run = get_run(run_id)
    if run is None:
        await update.message.reply_text(f"Run #{run_id} not found.")
        return
    old_status = run.get("status", "")
    if old_status == "published":
        await update.message.reply_text(
            f"Run #{run_id} is already published — can't kill a published story. "
            "Use /republish if you need to review it."
        )
        return
    if old_status == "killed":
        await update.message.reply_text(f"Run #{run_id} is already killed.")
        return
    update_run(run_id, status="killed")
    throughline = (run.get("throughline") or "N/A")[:120]
    await update.message.reply_text(
        f"✗ Run #{run_id} killed.\n\n{throughline}\n\nWas: {old_status}"
    )
    log.info("Run #%d killed (was: %s) via /kill", run_id, old_status)


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active sources (yaml + DB approved) with tier/lean and a deactivate button for DB ones."""
    import yaml
    from shared.config import SOURCES_YAML

    try:
        yaml_sources = yaml.safe_load(SOURCES_YAML.read_text()).get("sources", [])
    except Exception:
        yaml_sources = []
    db_sources = get_approved_sources()

    active_yaml = [s for s in yaml_sources if s.get("status") == "active"]
    active_db   = [s for s in db_sources if s.get("status", "active") == "active"]

    if not active_yaml and not active_db:
        await update.message.reply_text("No active sources found.")
        return

    tier_icon = lambda t: {1: "🟢", 2: "🟡", 3: "🟠"}.get(int(t or 3), "⚪")

    # YAML sources — static, can't deactivate via bot
    if active_yaml:
        lines = [f"Static sources ({len(active_yaml)}) — edit sources.yaml to change:\n"]
        for s in active_yaml:
            t = s.get("tier", 3)
            lines.append(
                f"{tier_icon(t)} T{t} {s.get('name', '?')} "
                f"({s.get('platform','?')}) | {s.get('lean','?')} | {s.get('role','?')}"
            )
        await update.message.reply_text("\n".join(lines))

    # DB sources — can deactivate inline
    if active_db:
        await update.message.reply_text(f"Bot-approved sources ({len(active_db)}):")
        for s in active_db:
            src_id = s["id"]
            t = s.get("tier", 3)
            text = (
                f"{tier_icon(t)} T{t} {s.get('name','?')} ({s.get('platform','?')})\n"
                f"Handle: {s.get('handle','—')} | {s.get('lean','?')} | {s.get('role','?')}"
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✗ Deactivate", callback_data=f"deactivatesrc_{src_id}")
            ]])
            await update.message.reply_text(text, reply_markup=keyboard)


async def cmd_setcost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the daily cost report time (UTC). Usage: /setcost HH:MM"""
    if not context.args:
        current = kv_get("cost_report_utc") or "14:30"
        await update.message.reply_text(
            f"Current cost report time: {current} UTC\n\n"
            "Usage: /setcost HH:MM (UTC, 24h)\n"
            "Example: /setcost 13:00 sends the report at 6:30pm IST"
        )
        return
    raw = context.args[0].strip()
    try:
        h, m = (int(x) for x in raw.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await update.message.reply_text("Invalid time. Use HH:MM (24h UTC), e.g. /setcost 14:30")
        return
    kv_set("cost_report_utc", f"{h:02d}:{m:02d}")
    ist_h = (h + 5) % 24
    ist_m = m + 30
    if ist_m >= 60:
        ist_m -= 60; ist_h = (ist_h + 1) % 24
    await update.message.reply_text(
        f"Cost report time set to {h:02d}:{m:02d} UTC ({ist_h:02d}:{ist_m:02d} IST)."
    )
    log.info("Cost report time set to %02d:%02d UTC", h, m)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show lifetime pipeline statistics."""
    from shared.db import get_pipeline_stats
    s = get_pipeline_stats()
    by_status = s["by_status"]
    total = s["total"]
    published = by_status.get("published", 0)
    killed    = by_status.get("killed", 0)
    held      = by_status.get("held", 0) + by_status.get("hold", 0)
    kill_rate = f"{killed/total*100:.0f}%" if total else "n/a"
    pub_rate  = f"{published/total*100:.0f}%" if total else "n/a"

    lines = [
        f"Thelivu lifetime stats ({total} runs):\n",
        f"  Published:  {published}  ({pub_rate})",
        f"  Killed:     {killed}  ({kill_rate})",
        f"  Held:       {held}",
        f"  Avg tokens: {s['avg_tokens']:,} / story",
        "",
        "Top sources by publications:",
    ]
    for src in s["top_sources"]:
        t = src["total"]; p = src["published"]; k = src["killed"]
        pct = f"{p/t*100:.0f}%" if t else "?"
        lines.append(f"  {src['source']}: {p} pub / {t} total ({pct}), {k} killed")

    await update.message.reply_text("\n".join(lines))


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search past runs by throughline keyword."""
    from shared.db import search_runs
    if not context.args:
        await update.message.reply_text("Usage: /search <keywords>\n\nSearches past runs by throughline.")
        return
    q = " ".join(context.args)
    results = search_runs(q)
    if not results:
        await update.message.reply_text(f"No runs found matching '{q}'.")
        return
    lines = [f"Search: '{q}' ({len(results)} found)\n"]
    for r in results:
        date = str(r.get("created_at", ""))[:10]
        gate = r.get("trust_gate") or "?"
        lines.append(f"#{r['id']} [{r['status']}] {date}\n  {(r['throughline'] or '')[:100]}\n  gate: {gate}")
    await update.message.reply_text("\n\n".join(lines))


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View or add to the investigative watchlist."""
    import yaml
    from shared.config import WATCHLIST_YAML

    if context.args and context.args[0] == "add":
        theme = " ".join(context.args[1:]).strip()
        if not theme:
            await update.message.reply_text("Usage: /watchlist add <question>")
            return
        try:
            data = yaml.safe_load(WATCHLIST_YAML.read_text()) or {}
            themes = data.get("themes") or []
            import re as _re
            slug = _re.sub(r"[^a-z0-9]+", "-", theme.lower())[:40].strip("-")
            themes.append({"id": slug, "question": theme, "status": "scoping"})
            data["themes"] = themes
            WATCHLIST_YAML.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
            await update.message.reply_text(f"Added to watchlist: {theme}")
        except Exception as e:
            await update.message.reply_text(f"Failed to save: {e}")
        return

    try:
        data = yaml.safe_load(WATCHLIST_YAML.read_text()) or {}
    except Exception:
        await update.message.reply_text("Watchlist not found or unreadable.")
        return

    themes = data.get("themes") or []
    if not themes:
        await update.message.reply_text("Watchlist is empty. Add with /watchlist add <question>")
        return

    status_icon = {"scoping": "🔍", "records-pending": "📋", "verifying": "🔎",
                   "ready-to-write": "✅", "parked": "⏸", "killed": "✗"}
    lines = [f"Watchlist ({len(themes)} themes):\n"]
    for t in themes:
        icon = status_icon.get(t.get("status", "scoping"), "•")
        q = t.get("question", t.get("id", "?"))[:120]
        lines.append(f"{icon} {q}")
    lines.append("\nAdd: /watchlist add <question>")
    await update.message.reply_text("\n".join(lines))


async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the RSS cycle interval in hours."""
    if not context.args:
        current = kv_get("check_interval_hours") or "6"
        await update.message.reply_text(
            f"Current RSS cycle interval: {current}h\n\n"
            "Usage: /setinterval <hours> (1–24)\nExample: /setinterval 4"
        )
        return
    try:
        hours = int(context.args[0])
        assert 1 <= hours <= 24
    except Exception:
        await update.message.reply_text("Usage: /setinterval <hours> (1–24)")
        return
    kv_set("check_interval_hours", str(hours))
    await update.message.reply_text(f"RSS cycle interval set to {hours}h. Takes effect next tick.")
    log.info("Check interval set to %dh via /setinterval", hours)


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

    data = query.data  # e.g. "approve_42" or "investigate_scout"
    parts = data.split("_", 1)
    if len(parts) != 2:
        await query.message.reply_text("Unrecognised action.")
        return

    action, payload = parts

    # Non-run-id actions handled first
    if action == "investigate" and payload == "scout":
        await _handle_investigate_scout(query)
        return
    if action == "addsrc":
        try:
            proposal_id = int(payload)
        except ValueError:
            await query.message.reply_text("Bad proposal ID.")
            return
        await _handle_addsrc(query, proposal_id)
        return
    if action == "skipsrc":
        try:
            proposal_id = int(payload)
        except ValueError:
            await query.message.reply_text("Bad proposal ID.")
            return
        await _handle_skipsrc(query, proposal_id)
        return
    if action == "deactivatesrc":
        try:
            src_id = int(payload)
        except ValueError:
            await query.message.reply_text("Bad source ID.")
            return
        await _handle_deactivatesrc(query, src_id)
        return
    if action in ("carouselapprove", "carouselkill"):
        try:
            carousel_id = int(payload)
        except ValueError:
            await query.message.reply_text("Bad carousel ID.")
            return
        carousel = get_carousel_run(carousel_id)
        if carousel is None:
            await query.message.reply_text(f"Carousel #{carousel_id} not found in database.")
            return
        if action == "carouselapprove":
            await _handle_carousel_approve(query, carousel_id, carousel)
        else:
            await _handle_carousel_kill(query, carousel_id)
        return

    # All remaining actions operate on a pipeline run
    try:
        run_id = int(payload)
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
    elif action == "recheck":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _request_recheck(query.message, run_id)
    else:
        await query.message.reply_text(f"Unknown action: {action}")


async def _handle_investigate_scout(query):
    """Queue the latest story-scout brief as a topic for immediate investigation."""
    brief = kv_get("latest_scout_brief")
    if not brief:
        await query.message.reply_text(
            "No scout brief found in store — the brief may have been overwritten or expired. "
            "Run /scoutnow to get a fresh one."
        )
        return
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    queue_topic(f"[SCOUT DIG] {brief[:800]}", source="story-scout-manual")
    await query.message.reply_text(
        "Scout dig queued for investigation. The agent will pick it up within 2 minutes "
        "and send you the full draft when ready."
    )
    log.info("Scout brief queued for investigation via button")


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


async def _handle_deactivatesrc(query, src_id):
    ok = deactivate_approved_source(src_id)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    if ok:
        await query.message.reply_text(
            f"Source #{src_id} deactivated. It will be skipped from the next RSS cycle."
        )
        log.info("Source #%d deactivated via /sources", src_id)
    else:
        await query.message.reply_text(f"Source #{src_id} not found.")


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
    article_url = ""
    try:
        import publishing.telegram as tg_render
        teaser, article_url = tg_render.render(prepared, CONTACT_HANDLE)
        msg_ids = _post_html_to_channel(teaser)
        log.info("Published run #%d via Telegraph: %s", run_id, article_url)
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

    # Build a direct link to the published post
    channel_link = ""
    if msg_ids and TELEGRAM_CHANNEL_ID:
        ch = TELEGRAM_CHANNEL_ID.lstrip("@")
        try:
            ch_int = abs(int(ch.lstrip("-100")))
            channel_link = f"\nt.me/c/{ch_int}/{msg_ids[0]}"
        except ValueError:
            channel_link = f"\nt.me/{ch}/{msg_ids[0]}"

    await query.message.reply_text(
        f"Published run #{run_id} ✓ ({how})\n"
        f"{len(msg_ids)} message(s) posted to {TELEGRAM_CHANNEL_ID}.{channel_link}"
    )
    log.info("Published run #%d (%s, %d msgs)", run_id, how, len(msg_ids))

    # Queue the Instagram carousel for this article. The orchestrator (not
    # this bot process) does the actual composing/rendering on its next tick
    # and sends the carousel back here for a separate approve/kill. article_url
    # (the Telegraph page, if that path succeeded) rides along so the final IG
    # caption can point back to the full story.
    try:
        carousel_id = queue_carousel_run(run_id, article_url=article_url)
        log.info("Queued carousel #%d for run #%d", carousel_id, run_id)
    except Exception as e:
        log.error("Failed to queue carousel for run #%d: %s", run_id, e)


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
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Re-check now", callback_data=f"recheck_{run_id}"),
        InlineKeyboardButton("✗ Kill it",       callback_data=f"kill_{run_id}"),
    ]])
    await query.message.reply_text(
        f"Story #{run_id} held.\n\nRe-check it when there's more to find, or kill it if it's a dead end.",
        reply_markup=keyboard,
    )
    log.info("Held run #%d", run_id)


async def _handle_carousel_approve(query, carousel_id, carousel):
    if carousel["status"] == "posted":
        await query.message.reply_text(f"Carousel #{carousel_id} was already posted.")
        return

    # image_url per slide is hosted by the orchestrator right after rendering
    # (self-hosted file server) — this bot runs as a separate Railway service
    # with its own filesystem, so it can't read local image_paths written by
    # that process. See process_queued_carousels() in engine/agents/orchestrator.py.
    slides = get_carousel_slides(carousel_id)
    image_urls = [s["image_url"] for s in slides if s.get("image_url")]
    if len(image_urls) != len(slides) or not image_urls:
        await query.message.reply_text(
            f"Carousel #{carousel_id} has {len(slides)} slides but only {len(image_urls)} hosted "
            f"images. Try again shortly, or check SLIDE_SERVER_BASE_URL is set."
        )
        return

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    from shared.config import IG_USER_ID, IG_ACCESS_TOKEN
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        update_carousel_run(carousel_id, status="approved_manual")
        await query.message.reply_text(
            f"Carousel #{carousel_id} approved — but Instagram isn't configured yet "
            f"(set IG_USER_ID / IG_ACCESS_TOKEN once the Meta app is ready). "
            f"The slides are above in this chat — post them manually for now."
        )
        return

    from publishing.instagram import publish_carousel
    try:
        caption = carousel.get("caption") or ""
        media_id, permalink = publish_carousel(image_urls, caption)
        update_carousel_run(carousel_id, status="posted", ig_media_id=media_id, ig_permalink=permalink)
        link_line = f"\n{permalink}" if permalink else ""
        await query.message.reply_text(f"Posted {len(image_urls)}-slide carousel #{carousel_id} to Instagram ✓{link_line}")
        log.info("Posted carousel #%d to Instagram (media %s)", carousel_id, media_id)
    except Exception as e:
        log.error("Instagram publish failed for carousel #%d: %s", carousel_id, e)
        await query.message.reply_text(f"Instagram publish failed for carousel #{carousel_id}: {e}")


async def _handle_carousel_kill(query, carousel_id):
    update_carousel_run(carousel_id, status="killed")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text(f"Carousel #{carousel_id} killed.")
    log.info("Killed carousel #%d", carousel_id)


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
            BotCommand("held",     "List held stories you can re-develop"),
            BotCommand("recheck",  "Re-investigate a held story fresh by id"),
            BotCommand("reset",    "Reset a stuck run back to held (admin)"),
            BotCommand("republish","Reset a published run back to review by id"),
            BotCommand("queue",    "What's running, queued, and when next cycle fires"),
            BotCommand("runnow",   "Trigger an RSS cycle immediately"),
            BotCommand("feeds",    "List active RSS sources"),
            BotCommand("addfeed",  "Add a YouTube channel for evaluation"),
            BotCommand("scoutnow", "Signal source scout to run now"),
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
    app.add_handler(CommandHandler("held", cmd_held))
    app.add_handler(CommandHandler("recheck", cmd_recheck))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("clearghosts", cmd_clearghosts))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(CommandHandler("sources", cmd_sources))
    app.add_handler(CommandHandler("setcost", cmd_setcost))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("setinterval", cmd_setinterval))
    app.add_handler(CallbackQueryHandler(button_callback))

    log.info("Polling for updates. Human gate active.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
