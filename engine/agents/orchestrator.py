"""
Thelivu agent orchestrator — always-on pipeline loop.

Entry point: python -m engine.agents.orchestrator

Runs a pipeline cycle every CHECK_INTERVAL_HOURS (default 6), sleeping between:
  ingest → monitor → investigate → verify → pattern → write → review → Telegram

Agents can use web_search to verify claims and create_skill to add new skills
when they identify recurring editorial patterns.
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import yaml

import time

from shared.config import (
    SOURCES_YAML,
    WATCHLIST_YAML,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_DRAFT_CHAT_ID,
    GEMINI_API_KEY,
    ANTHROPIC_API_KEY,
    APPROVAL_MODE,
    ARTICLES_DIR,
    DRY_RUN_LOG,
    CHECK_INTERVAL_HOURS,
)
from shared.db import (
    init_db,
    is_seen,
    mark_seen,
    save_run,
    update_run,
    get_held_runs,
    get_cost_report_data,
    get_approved_sources,
    save_proposal,
    set_proposal_msg_id,
    pop_next_topic,
    finish_topic,
    kv_set,
    kv_get,
)
from engine.agents.skill_runner import run_skill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("orchestrator")


# ---------------------------------------------------------------------------
# Ingestion helpers (transcript-first; Gemini video fallback)
# ---------------------------------------------------------------------------

def _video_id(url):
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else url


def _get_transcript(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        chunks = YouTubeTranscriptApi.get_transcript(video_id)
        return "\n".join(
            f"[{int(c['start'])//60:02d}:{int(c['start'])%60:02d}] {c['text']}"
            for c in chunks
        )
    except Exception:
        return None


def _extract_claims_via_claude(transcript):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        "Extract from this transcript (faithfully, without endorsing):\n"
        "1. throughline: the video's central argument in 1-2 sentences, phrased as "
        "the SOURCE's claim ('The source argues that...')\n"
        "2. claims: each discrete factual assertion with [MM:SS] timestamp, a "
        "provisional bucket (fact|allegation|inference), and any source the video "
        "itself cites (or null).\n\n"
        "Return ONLY valid JSON: "
        '{\"throughline\": \"...\", \"claims\": [{\"text\", \"timestamp\", '
        '\"provisional_bucket\", \"video_cited_source\"}]}\n\n'
        "TRANSCRIPT:\n" + transcript
    )
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",  # cheap extraction step
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def _ingest_via_gemini(video_url):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        "Extract from this video (faithfully, without endorsing):\n"
        "1. throughline: the video's central argument in 1-2 sentences.\n"
        "2. claims: each discrete factual assertion with timestamp, provisional "
        "bucket (fact|allegation|inference), and any source the video cites.\n"
        "3. notable_visuals: any on-screen documents or figures that carry meaning "
        "the audio alone does not.\n\n"
        'Return ONLY valid JSON: {"throughline":"...","claims":[...],"notable_visuals":[...]}'
    )
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=video_url)),
            types.Part(text=prompt),
        ]),
    )
    text = re.sub(r"^```(?:json)?|```$", "", resp.text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def ingest_source(source):
    """Fetch RSS, return list of new lead dicts (deduped against seen_items)."""
    feed_url = source.get("feed")
    if not feed_url:
        return []

    feed = feedparser.parse(feed_url)
    items = []
    for entry in feed.entries:
        vid = _video_id(entry.link)
        if is_seen(vid):
            continue

        transcript = _get_transcript(vid)
        if transcript:
            try:
                extracted = _extract_claims_via_claude(transcript)
            except Exception as e:
                log.warning("Claim extraction failed for %s: %s", vid, e)
                extracted = {"throughline": entry.title, "claims": []}
            method = "transcript"
        elif GEMINI_API_KEY:
            try:
                extracted = _ingest_via_gemini(entry.link)
            except Exception as e:
                log.warning("Gemini fallback failed for %s: %s", vid, e)
                extracted = {"throughline": entry.title, "claims": []}
            method = "gemini_video"
        else:
            extracted = {"throughline": entry.title, "claims": []}
            method = "title_only"

        mark_seen(vid, source["id"])
        items.append({
            "video_id": vid,
            "video_url": entry.link,
            "title": entry.title,
            "source": source["name"],
            "source_id": source["id"],
            "throughline": extracted.get("throughline", entry.title),
            "claims": extracted.get("claims", []),
            "ingest_method": method,
        })
        log.info("  ingested: %s [%s]", entry.title[:60], method)

    return items


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

_TG_LIMIT = 4096


def _split_chunks(text):
    """Split text into ≤4096-char chunks at paragraph boundaries."""
    chunks, current = [], ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= _TG_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Para itself may exceed limit — split by line
            while len(para) > _TG_LIMIT:
                chunks.append(para[:_TG_LIMIT])
                para = para[_TG_LIMIT:]
            current = para
    if current:
        chunks.append(current)
    return chunks or ["(empty)"]


def _tg_post(chat_id, text, reply_markup=None):
    """Send a single message — caller must ensure len(text) ≤ 4096."""
    payload = {"chat_id": str(chat_id), "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return None


def _tg_send_long(chat_id, text):
    """Send arbitrarily long text as multiple messages. Returns first msg_id."""
    first_id = None
    for chunk in _split_chunks(text):
        msg_id = _tg_post(chat_id, chunk)
        if first_id is None:
            first_id = msg_id
        time.sleep(0.3)
    return first_id


def _notify(text):
    """Send a short status notification to Anil's draft chat."""
    _tg_send_long(TELEGRAM_DRAFT_CHAT_ID, text)


def send_for_approval(run_id, draft_text, verification_report, review_text):
    """Route the finished draft based on APPROVAL_MODE."""
    if APPROVAL_MODE == "telegram":
        _send_via_telegram(run_id, draft_text, verification_report, review_text)
    else:
        _save_to_file(run_id, draft_text, verification_report, review_text)


def _send_via_telegram(run_id, draft_text, verification_report, review_text):
    title = draft_text.lstrip("# ").splitlines()[0][:80]
    summary = (
        f"Draft ready — run #{run_id}\n\n"
        f"{title}\n\n"
        f"Trust gate: READY-FOR-HUMAN\n\n"
        f"Review notes:\n{review_text[:600]}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✓ Approve", "callback_data": f"approve_{run_id}"},
            {"text": "✗ Kill",    "callback_data": f"kill_{run_id}"},
            {"text": "⏸ Hold",   "callback_data": f"hold_{run_id}"},
        ]]
    }
    # Summary + buttons first (always short enough for one message)
    msg_id = _tg_post(TELEGRAM_DRAFT_CHAT_ID, summary[:_TG_LIMIT], reply_markup=keyboard)
    update_run(run_id, tg_msg_id=msg_id)

    # Full draft in follow-up messages (properly chunked, no truncation)
    _tg_send_long(TELEGRAM_DRAFT_CHAT_ID, draft_text)


def _save_to_file(run_id, draft_text, verification_report, review_text):
    """Save draft + report to articles/drafts/ and log to dry-run-log.md."""
    from datetime import date
    today = date.today().isoformat()

    drafts_dir = ARTICLES_DIR / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)

    draft_file = drafts_dir / f"{today}-draft.md"
    draft_file.write_text(draft_text, encoding="utf-8")

    report_file = drafts_dir / f"{today}-report.md"
    report_file.write_text(
        f"# Verification & Review Report — {today}\n\n"
        f"## Trust Gate Output\n\n{verification_report}\n\n"
        f"## Editorial Review\n\n{review_text}",
        encoding="utf-8",
    )

    # Append one row to the dry-run log
    log_entry = (
        f"| {today} | run #{run_id} | READY-FOR-HUMAN | "
        f"See {today}-report.md | See {today}-report.md | | | |\n"
    )
    with open(DRY_RUN_LOG, "a", encoding="utf-8") as f:
        f.write(log_entry)

    log.info("Draft saved: %s", draft_file)
    log.info("Report saved: %s", report_file)
    log.info("Dry-run log updated.")
    print("\n" + "=" * 60)
    print(f"  DRAFT READY FOR REVIEW — run #{run_id}")
    print(f"  File: articles/drafts/{today}-draft.md")
    print(f"  Report: articles/drafts/{today}-report.md")
    print("=" * 60 + "\n")
    print(draft_text)


# ---------------------------------------------------------------------------
# Trust gate parser
# ---------------------------------------------------------------------------

def _parse_gate(text):
    for gate in ("KILL", "FRAMING-FIX", "HOLD", "READY-FOR-HUMAN"):
        if gate in text:
            return gate
    return "HOLD"  # conservative default


# ---------------------------------------------------------------------------
# Main daily cycle
# ---------------------------------------------------------------------------

def _run_topic_intake(pending):
    """Run the full pipeline on an owner-submitted topic via topic-intake."""
    topic_id = pending["id"]
    topic_text = pending["topic"]

    log.info("Running topic-intake on: %s", topic_text[:80])
    intake_output = run_skill(
        "topic-intake",
        f"SUBMITTED TOPIC:\n\n{topic_text}\n\nSource: {pending.get('source', 'owner')}",
    )

    # topic-intake may DECLINE — respect that
    if any(word in intake_output.upper() for word in ("DECLINE", "PARK", "OUT OF SCOPE")):
        finish_topic(topic_id)
        _notify(f"Topic-intake declined this topic:\n\n{intake_output[:600]}")
        log.info("Topic declined by topic-intake.")
        return

    # Otherwise topic-intake passes a scoped lead — run the full spine
    log.info("Topic accepted. Running investigation...")
    # Save early so /track can show live status
    live_run_id = save_run(
        video_id=f"topic-{topic_id}",
        source=pending.get("source", "owner"),
        throughline=topic_text[:200],
        trust_gate="investigating",
        status="investigating",
    )
    dossier = run_skill("news-investigator", intake_output)

    log.info("Running source-verifier...")
    verification = run_skill("source-verifier", f"EVIDENCE DOSSIER:\n\n{dossier}")
    gate = _parse_gate(verification)
    log.info("Trust gate: %s", gate)

    if gate in ("KILL", "HOLD"):
        update_run(live_run_id, trust_gate=gate, verification_report=verification, status=gate.lower())
        finish_topic(topic_id)
        _notify(f"Your topic was {gate}ed (run #{live_run_id}).\n\n{verification[:600]}")
        return

    update_run(live_run_id, trust_gate=gate, status="writing")
    pattern = run_skill("pattern-synthesizer",
        f"VERIFIED DOSSIER:\n\n{dossier}\n\nVERIFICATION:\n\n{verification}")
    draft = run_skill("article-writer",
        f"DOSSIER:\n\n{dossier}\n\nVERIFICATION:\n\n{verification}\n\nPATTERN:\n\n{pattern}")
    review = run_skill("editorial-reviewer", draft)

    update_run(live_run_id,
        throughline=topic_text[:200],
        trust_gate=gate,
        draft_text=draft,
        review_text=review,
        verification_report=verification,
        status="pending_human",
    )
    finish_topic(topic_id)
    send_for_approval(live_run_id, draft, verification, review)
    log.info("Topic pipeline complete. Run #%d pending review.", run_id)


def run_daily_cycle():
    log.info("=== Thelivu daily cycle starting ===")
    init_db()
    kv_set("last_cycle_at", datetime.now(timezone.utc).isoformat())

    # 1. Check for owner-submitted topics first (these jump the RSS queue)
    pending = pop_next_topic()
    if pending:
        log.info("Owner topic queued: %s", pending["topic"][:80])
        _run_topic_intake(pending)
        return

    # 2. Load active YouTube sources (static yaml + DB-approved)
    sources_data = yaml.safe_load(SOURCES_YAML.read_text())
    yaml_sources = [
        s for s in sources_data.get("sources", [])
        if s.get("status") == "active" and s.get("platform") == "youtube" and s.get("feed")
    ]
    db_sources = [
        s for s in get_approved_sources()
        if s.get("platform") == "youtube" and s.get("feed_url")
    ]
    # Normalise db sources to match yaml shape
    for s in db_sources:
        s["feed"] = s.pop("feed_url", None)
        s["id"] = s.get("handle", str(s["id"]))
    active_sources = yaml_sources + db_sources
    log.info("Active sources: %s", [s["id"] for s in active_sources])

    # 3. Ingest new items from all active sources
    all_leads = []
    for source in active_sources:
        try:
            items = ingest_source(source)
            all_leads.extend(items)
            log.info("%s: %d new item(s)", source["name"], len(items))
        except Exception as e:
            log.error("Ingest failed for %s: %s", source["name"], e)

    if not all_leads:
        _notify("Thelivu daily cycle: no new leads today. Nothing to investigate.")
        log.info("No new leads. Exiting.")
        return

    # 4. news-monitor: pick the top lead by impact × under-coverage
    log.info("Running news-monitor on %d lead(s)...", len(all_leads))
    leads_text = "LEADS TO EVALUATE:\n\n" + "\n\n---\n\n".join(
        f"**Lead {i+1}** (source: {item['source']})\n"
        f"Throughline: {item['throughline']}\n"
        f"URL: {item['video_url']}\n"
        f"Claims ({len(item['claims'])}): "
        + "; ".join(c.get("text", "")[:80] for c in item["claims"][:3])
        for i, item in enumerate(all_leads)
    )

    monitor_output = run_skill("news-monitor", leads_text)

    # Pick the selected lead (monitor should identify it clearly)
    selected = all_leads[0]  # fallback: first lead
    for item in all_leads:
        if item["video_url"] in monitor_output or item["throughline"][:40] in monitor_output:
            selected = item
            break

    log.info("Selected: %s", selected["throughline"][:80])

    # 4. news-investigator: build evidence dossier (uses web_search)
    log.info("Running news-investigator...")
    investigate_input = (
        f"LEAD TO INVESTIGATE:\n\n"
        f"Source: {selected['source']}\n"
        f"URL: {selected['video_url']}\n"
        f"Throughline: {selected['throughline']}\n\n"
        f"Extracted claims:\n"
        + json.dumps(selected["claims"], indent=2, ensure_ascii=False)
        + f"\n\nMonitor context:\n{monitor_output}"
    )
    dossier = run_skill("news-investigator", investigate_input)

    # 5. source-verifier: trust gate (uses web_search)
    log.info("Running source-verifier...")
    verification = run_skill(
        "source-verifier",
        f"EVIDENCE DOSSIER TO VERIFY:\n\n{dossier}",
    )

    gate = _parse_gate(verification)
    log.info("Trust gate: %s", gate)

    if gate in ("KILL", "HOLD"):
        run_id = save_run(
            video_id=selected["video_id"],
            source=selected["source"],
            throughline=selected["throughline"],
            trust_gate=gate,
            verification_report=verification,
            status=gate.lower(),
        )
        _notify(
            f"Thelivu: today's story {gate}ed (run #{run_id}).\n\n"
            f"Reason:\n{verification[:600]}"
        )
        log.info("Story %s. Run #%d saved.", gate, run_id)
        return

    if gate == "FRAMING-FIX":
        # Continue — the writer and reviewer will address framing
        log.info("FRAMING-FIX: continuing to write with framing notes.")

    # 6. pattern-synthesizer: look for cross-story patterns
    log.info("Running pattern-synthesizer...")
    pattern = run_skill(
        "pattern-synthesizer",
        f"VERIFIED DOSSIER:\n\n{dossier}\n\nVERIFICATION REPORT:\n\n{verification}",
    )

    # 7. article-writer: transparent-perspective draft
    log.info("Running article-writer...")
    draft = run_skill(
        "article-writer",
        f"VERIFIED DOSSIER:\n\n{dossier}\n\n"
        f"VERIFICATION REPORT:\n\n{verification}\n\n"
        f"PATTERN ANALYSIS:\n\n{pattern}",
    )

    # 8. editorial-reviewer: framing, symmetry, legal check
    log.info("Running editorial-reviewer...")
    review = run_skill("editorial-reviewer", draft)

    # 9. Save and send for approval
    run_id = save_run(
        video_id=selected["video_id"],
        source=selected["source"],
        throughline=selected["throughline"],
        trust_gate=gate,
        draft_text=draft,
        review_text=review,
        verification_report=verification,
        status="pending_human",
    )

    log.info("Sending draft for approval (run #%d)...", run_id)
    send_for_approval(run_id, draft, verification, review)
    log.info("=== Cycle complete. Run #%d pending human review. ===", run_id)


# ---------------------------------------------------------------------------
# Source scout (runs weekly, proposes new sources via Telegram)
# ---------------------------------------------------------------------------

def run_source_scout():
    log.info("Running source-scout...")

    # Load current sources so the skill knows what's already in the pool
    sources_data = yaml.safe_load(SOURCES_YAML.read_text())
    current_sources = sources_data.get("sources", [])
    db_sources = get_approved_sources()

    sources_summary = "CURRENT SOURCE POOL (do not re-nominate these):\n\n"
    for s in current_sources:
        sources_summary += f"- {s['name']} ({s.get('platform')}) | role: {s.get('role')} | lean: {s.get('lean','')} | status: {s.get('status')}\n"
    for s in db_sources:
        sources_summary += f"- {s['name']} ({s.get('platform')}) | role: {s.get('role')} | lean: {s.get('lean','')} [approved via bot]\n"

    prompt = (
        f"Run the weekly source scout for the Kerala/India investigative beat.\n\n"
        f"{sources_summary}\n"
        f"Focus on finding verification-grade (Tier 1-2) and cross-spectrum sources "
        f"that fill gaps in the current pool. Use Google Search to research candidates thoroughly."
    )

    output = run_skill("source-scout", prompt)

    # Parse PROPOSALS JSON block
    import re as _re
    match = _re.search(r"PROPOSALS\s*(\[.*?\])\s*END_PROPOSALS", output, _re.DOTALL)
    if not match:
        log.info("Source scout: no proposals block found.")
        _notify(f"Source scout ran but found no new proposals this week.\n\n{output[:600]}")
        return

    try:
        proposals = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        log.error("Source scout: failed to parse proposals JSON: %s", e)
        _notify(f"Source scout ran but proposals JSON was malformed.\n\n{output[:600]}")
        return

    if not proposals:
        _notify("Source scout ran — no sources meet the bar this week.")
        return

    _notify(f"Source scout found {len(proposals)} candidate(s). Review below:")

    for p in proposals:
        proposal_id = save_proposal(
            name=p.get("name", "Unknown"),
            platform=p.get("platform", "web"),
            handle=p.get("handle", ""),
            feed_url=p.get("feed_url", ""),
            lean=p.get("lean", ""),
            role=p.get("role", "lead"),
            tier=p.get("tier", 3),
            notes=p.get("notes", ""),
        )
        text = (
            f"New source proposal #{proposal_id}\n\n"
            f"Name: {p.get('name')}\n"
            f"Platform: {p.get('platform')} | Role: {p.get('role')} | Tier: {p.get('tier')}\n"
            f"Handle: {p.get('handle')}\n"
            f"Lean: {p.get('lean')}\n\n"
            f"{p.get('notes', '')}"
        )
        keyboard = {
            "inline_keyboard": [[
                {"text": "✓ Add",  "callback_data": f"addsrc_{proposal_id}"},
                {"text": "✗ Skip", "callback_data": f"skipsrc_{proposal_id}"},
            ]]
        }
        msg_id = _tg_post(TELEGRAM_DRAFT_CHAT_ID, text, reply_markup=keyboard)
        if msg_id:
            set_proposal_msg_id(proposal_id, msg_id)

    kv_set("last_scout_at", datetime.now(timezone.utc).isoformat())
    log.info("Source scout complete. %d proposal(s) sent.", len(proposals))


# ---------------------------------------------------------------------------
# Daily cost report (sent at 8pm IST / 14:30 UTC)
# ---------------------------------------------------------------------------

_CLAUDE_IN_PER_M  = 3.00
_CLAUDE_OUT_PER_M = 15.00
_GEMINI_IN_PER_M  = 0.30
_GEMINI_OUT_PER_M = 1.00
_USD_TO_INR       = 84


def _calc_cost(model, in_tok, out_tok):
    if "gemini" in model.lower():
        return (in_tok / 1_000_000 * _GEMINI_IN_PER_M) + (out_tok / 1_000_000 * _GEMINI_OUT_PER_M)
    return (in_tok / 1_000_000 * _CLAUDE_IN_PER_M) + (out_tok / 1_000_000 * _CLAUDE_OUT_PER_M)


def send_cost_report():
    from datetime import date
    data = get_cost_report_data()
    rows = data["by_model"]
    runs_today = data["runs_today"]
    today = date.today().isoformat()

    today_usd = month_usd = total_usd = 0.0
    lines = []
    for row in rows:
        model = row["model"]
        c_today = _calc_cost(model, row["today_in"] or 0, row["today_out"] or 0)
        c_month = _calc_cost(model, row["month_in"] or 0, row["month_out"] or 0)
        c_total = _calc_cost(model, row["total_in"] or 0, row["total_out"] or 0)
        today_usd += c_today
        month_usd += c_month
        total_usd += c_total
        lines.append(
            f"  {model}: {row['today_in'] or 0}in + {row['today_out'] or 0}out tokens = ${c_today:.4f}"
        )

    report = (
        f"Thelivu Cost Report — {today}\n\n"
        f"Today: ₹{today_usd * _USD_TO_INR:.2f} (~${today_usd:.4f})\n"
        f"This month: ₹{month_usd * _USD_TO_INR:.2f} (~${month_usd:.4f})\n"
        f"All time: ₹{total_usd * _USD_TO_INR:.2f} (~${total_usd:.4f})\n\n"
        f"Today's breakdown:\n" + "\n".join(lines or ["  No usage recorded."]) + "\n\n"
        f"Pipeline runs today: {runs_today}"
    )
    _notify(report)
    log.info("Cost report sent.")


# ---------------------------------------------------------------------------
# Retry held stories (runs as part of the daily cycle)
# ---------------------------------------------------------------------------

def retry_held():
    held = get_held_runs(older_than_days=3)
    if not held:
        return
    log.info("Retrying %d held story/stories...", len(held))
    for run in held:
        log.info("  Retrying run #%d: %s", run["id"], run["throughline"][:60])
        # Re-verify with fresh sources
        try:
            verification = run_skill(
                "source-verifier",
                f"RE-VERIFY (previously HOLD):\n\n{run.get('verification_report', 'N/A')}",
            )
            gate = _parse_gate(verification)
            if gate == "READY-FOR-HUMAN":
                update_run(run["id"], trust_gate=gate, verification_report=verification, status="pending_human")
                send_for_approval(run["id"], run["draft_text"] or "", verification, run["review_text"] or "")
            else:
                update_run(run["id"], trust_gate=gate, verification_report=verification)
                log.info("  Still %s — keeping on hold.", gate)
        except Exception as e:
            log.error("  Retry failed for run #%d: %s", run["id"], e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set. Exiting.")
        sys.exit(1)
    if APPROVAL_MODE == "telegram" and (not TELEGRAM_BOT_TOKEN or not TELEGRAM_DRAFT_CHAT_ID):
        log.error("APPROVAL_MODE=telegram but TELEGRAM_BOT_TOKEN or TELEGRAM_DRAFT_CHAT_ID not set.")
        sys.exit(1)

    # --once: run a single cycle and exit (used by /topic and /runnow triggers)
    if "--once" in sys.argv:
        log.info("Single-cycle mode (--once)")
        run_daily_cycle()
        retry_held()
        sys.exit(0)

    log.info("Approval mode: %s | Polling every %dh", APPROVAL_MODE, CHECK_INTERVAL_HOURS)

    _cost_report_sent_date = None

    while True:
        now_utc = datetime.now(timezone.utc)

        # Send cost report once per day at 14:30 UTC (8pm IST)
        today = now_utc.date()
        if now_utc.hour == 14 and now_utc.minute >= 30 and _cost_report_sent_date != today:
            try:
                send_cost_report()
                _cost_report_sent_date = today
            except Exception as e:
                log.error("Cost report failed: %s", e)

        # Run source scout weekly (every 7 days)
        try:
            last_scout = kv_get("last_scout_at")
            if last_scout:
                from datetime import timedelta
                last_dt = datetime.fromisoformat(last_scout)
                if (now_utc - last_dt).days >= 7:
                    run_source_scout()
            else:
                run_source_scout()  # first run
        except Exception as e:
            log.error("Source scout failed: %s", e)

        try:
            run_daily_cycle()
            retry_held()
        except Exception as e:
            log.error("Cycle failed: %s", e, exc_info=True)

        log.info("Sleeping %dh until next cycle...", CHECK_INTERVAL_HOURS)
        time.sleep(CHECK_INTERVAL_HOURS * 3600)
