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
    update_run_legal_flag,
    get_held_runs,
    get_cost_report_data,
    get_approved_sources,
    get_source_reliability,
    get_published_stories,
    get_all_runs_summary,
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


def _extract_claims_via_skill(url, transcript=None):
    """Use source-ingestor skill to extract structured claims from a video."""
    prompt = f"URL: {url}\n\n"
    if transcript:
        prompt += f"TRANSCRIPT:\n{transcript}"
    else:
        prompt += "(No transcript available — extract from video context if possible.)"
    output = run_skill("source-ingestor", prompt)
    text = re.sub(r"^```(?:json)?|```$", "", output.strip(), flags=re.MULTILINE).strip()
    # Find the JSON object in the output
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("source-ingestor did not return valid JSON")


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

    platform = source.get("platform", "web")
    feed = feedparser.parse(feed_url)
    items = []

    for entry in feed.entries:
        # Use URL as the unique ID for web articles, video_id for YouTube
        if platform == "youtube":
            item_id = _video_id(entry.link)
            transcript = _get_transcript(item_id)
        else:
            item_id = entry.link
            transcript = None  # web articles: use title + summary as context

        if is_seen(item_id):
            continue

        if platform == "youtube":
            try:
                extracted = _extract_claims_via_skill(entry.link, transcript)
                method = "transcript" if transcript else "skill_only"
            except Exception as e:
                log.warning("source-ingestor failed for %s (%s) — title only", item_id, e)
                extracted = {"throughline": entry.title, "claims": []}
                method = "title_only"
        else:
            # Web article: use title + summary as the throughline; skip full skill call
            summary = getattr(entry, "summary", "") or ""
            extracted = {
                "throughline": entry.title,
                "claims": [{"text": summary[:300], "provisional_bucket": "allegation", "timestamp": None, "video_cited_source": None}] if summary else [],
            }
            method = "rss_summary"

        mark_seen(item_id, source["id"])
        items.append({
            "video_id": item_id,
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
# Lead pre-filter — drop entertainment/gossip before they reach the model
# ---------------------------------------------------------------------------

_EXCLUDE_KEYWORDS = [
    # Cinema / entertainment
    "film", "movie", "cinema", "actor", "actress", "director", "ott", "streaming",
    "box office", "trailer", "release", "collection", "award", "oscar", "filmfare",
    "iifa", "bollywood", "kollywood", "mollywood", "tollywood", "web series",
    "series review", "movie review", "film review",
    # Named directors / actors (expand as needed)
    "priyadarshan", "mohanlal", "mammootty", "fahadh", "dulquer",
    "vijay", "rajinikanth", "aamir khan", "shah rukh", "deepika", "priyanka",
    # Celebrity / gossip
    "celebrity", "gossip", "dating", "breakup", "wedding", "divorce", "baby",
    "pregnancy", "baby shower", "couple", "love life", "affair",
    # Sports scores / match news
    "match report", "scorecard", "wickets", "innings", "fixtures", "standings",
    "transfer window", "ipl", "fifa", "champions league", "premier league",
    # Lifestyle / PR
    "recipe", "fashion week", "skincare", "makeup", "horoscope", "astrology",
    "zodiac", "product launch", "brand ambassador", "collaboration",
]

def _is_entertainment(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _EXCLUDE_KEYWORDS)


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


def _parse_legal_flag(review_text):
    """Extract LEGAL-FLAG and LEGAL-REASON from editorial reviewer output."""
    flag = False
    reason = ""
    for line in (review_text or "").splitlines():
        if line.startswith("LEGAL-FLAG:"):
            flag = "YES" in line.upper()
        if line.startswith("LEGAL-REASON:"):
            reason = line.split(":", 1)[-1].strip()
    return flag, reason


def _send_via_telegram(run_id, draft_text, verification_report, review_text):
    legal_flag, legal_reason = _parse_legal_flag(review_text)

    # Persist legal flag to DB
    if legal_flag:
        update_run_legal_flag(run_id, True, legal_reason)

    title = draft_text.lstrip("# ").splitlines()[0][:80]

    legal_warning = ""
    if legal_flag:
        legal_warning = (
            f"\n\n⚠️ LEGAL REVIEW REQUIRED before approving.\n"
            f"Reason: {legal_reason}\n"
            f"Do NOT approve until a legal read has been done."
        )

    # Pull a one-line verdict from the review (first non-empty line after APPROVED/PASS)
    verdict = ""
    for ln in (review_text or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and not ln.startswith("```"):
            verdict = ln[:120]
            break

    summary = (
        f"📰 New story ready — run #{run_id}\n\n"
        f"*{title}*"
        f"{legal_warning}\n\n"
        f"Read the draft below, then tap to decide."
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✓ Approve", "callback_data": f"approve_{run_id}"},
            {"text": "✗ Kill",    "callback_data": f"kill_{run_id}"},
            {"text": "⏸ Hold",   "callback_data": f"hold_{run_id}"},
        ]]
    }
    msg_id = _tg_post(TELEGRAM_DRAFT_CHAT_ID, summary[:_TG_LIMIT], reply_markup=keyboard)
    update_run(run_id, tg_msg_id=msg_id)
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
# Revision loop helpers
# ---------------------------------------------------------------------------

_MAX_REVISIONS = 2


def _parse_revision(review_text):
    """Return (needs_revision, investigator_tasks, writer_tasks)."""
    if "REVISION_NEEDED" not in review_text:
        return False, "", ""
    m_inv = re.search(r"Investigator tasks:(.*?)(?:Writer tasks:|END_REVISION)", review_text, re.DOTALL)
    m_wri = re.search(r"Writer tasks:(.*?)END_REVISION", review_text, re.DOTALL)
    inv = m_inv.group(1).strip() if m_inv else ""
    wri = m_wri.group(1).strip() if m_wri else ""
    return True, inv, wri


def _revision_loop(brief, dossier, verification, pattern, draft, run_id, topic_label, revision_num=0):
    """Run reviewer; if REVISION_NEEDED send back to investigator/writer; repeat up to _MAX_REVISIONS."""
    review = run_skill("editorial-reviewer",
        _with_brief(brief, f"DRAFT:\n\n{draft}\n\nVERIFICATION REPORT:\n\n{verification}"),
        run_id=run_id, topic=topic_label)

    needs_revision, inv_tasks, wri_tasks = _parse_revision(review)

    if not needs_revision or revision_num >= _MAX_REVISIONS:
        if revision_num >= _MAX_REVISIONS and needs_revision:
            log.warning("Max revisions (%d) reached — sending to human anyway.", _MAX_REVISIONS)
            review += f"\n\n[Note: sent after {_MAX_REVISIONS} revision cycles — reviewer still had notes.]"
        return draft, review

    log.info("Reviewer requested revision (cycle %d/%d).", revision_num + 1, _MAX_REVISIONS)

    if inv_tasks:
        log.info("Re-running investigator with revision tasks...")
        revision_prompt = (
            f"REVISION REQUEST FROM EDITORIAL REVIEWER:\n\n{inv_tasks}\n\n"
            f"ORIGINAL DOSSIER:\n\n{dossier}"
        )
        dossier = run_skill("news-investigator",
            _with_brief(brief, revision_prompt), run_id=run_id, topic=topic_label)

    if wri_tasks:
        log.info("Re-running writer with revision tasks...")
        revision_prompt = (
            f"REVISION REQUEST FROM EDITORIAL REVIEWER:\n\n{wri_tasks}\n\n"
            f"ORIGINAL DRAFT:\n\n{draft}"
        )
        draft = run_skill("article-writer",
            _with_brief(brief,
                f"{revision_prompt}\n\nDOSSIER:\n\n{dossier}\n\n"
                f"VERIFICATION REPORT:\n\n{verification}\n\nPATTERN:\n\n{pattern}"),
            run_id=run_id, topic=topic_label)
    elif inv_tasks:
        # Investigator produced new material — re-run writer too
        draft = run_skill("article-writer",
            _with_brief(brief,
                f"UPDATED DOSSIER (revised by investigator):\n\n{dossier}\n\n"
                f"VERIFICATION REPORT:\n\n{verification}\n\nPATTERN:\n\n{pattern}"),
            run_id=run_id, topic=topic_label)

    return _revision_loop(brief, dossier, verification, pattern, draft,
                          run_id, topic_label, revision_num + 1)


# ---------------------------------------------------------------------------
# Trust gate parser
# ---------------------------------------------------------------------------

def _parse_gate(text):
    for gate in ("KILL", "FRAMING-FIX", "HOLD", "READY-FOR-HUMAN"):
        if gate in text:
            return gate
    return "HOLD"  # conservative default


def _extract_brief(text):
    """Pull the STORY_BRIEF block out of topic-intake output. Returns the block
    as a string (with delimiters) or empty string if not present."""
    m = re.search(r"(STORY_BRIEF\b.*?END_STORY_BRIEF)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _with_brief(brief, input_text):
    """Prepend the story brief to a skill input so every agent shares the frame."""
    if not brief:
        return input_text
    return f"{brief}\n\n{input_text}"


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

    # topic-intake may DECLINE — only match the structured Decision line, not stray mentions
    import re as _re
    _decision = _re.search(r'Decision:\s*(PARK|DECLINE)', intake_output, _re.IGNORECASE)
    if _decision:
        finish_topic(topic_id)
        _notify(f"Topic-intake declined this topic ({_decision.group(1).upper()}):\n\n{intake_output[:800]}")
        log.info("Topic declined by topic-intake: %s", _decision.group(1))
        return

    # Otherwise topic-intake passes a scoped lead — run the full spine
    brief = _extract_brief(intake_output)
    if brief:
        log.info("Story brief extracted:\n%s", brief)
    else:
        log.warning("No STORY_BRIEF block in topic-intake output — proceeding without brief.")

    log.info("Topic accepted. Running investigation...")
    live_run_id = save_run(
        video_id=f"topic-{topic_id}",
        source=pending.get("source", "owner"),
        throughline=topic_text[:200],
        trust_gate="investigating",
        status="investigating",
    )

    topic_label = topic_text[:120]
    dossier = run_skill("news-investigator",
        _with_brief(brief, intake_output),
        run_id=live_run_id, topic=topic_label)

    log.info("Running source-verifier...")
    verification = run_skill("source-verifier",
        _with_brief(brief, f"EVIDENCE DOSSIER:\n\n{dossier}"),
        run_id=live_run_id, topic=topic_label)
    gate = _parse_gate(verification)
    log.info("Trust gate: %s", gate)

    if gate in ("KILL", "HOLD"):
        update_run(live_run_id, trust_gate=gate, verification_report=verification, status=gate.lower())
        finish_topic(topic_id)
        _notify(f"Your topic was {gate}ed (run #{live_run_id}).\n\n{verification}")
        return

    update_run(live_run_id, trust_gate=gate, status="writing")
    pattern = run_skill("pattern-synthesizer",
        _with_brief(brief, f"VERIFIED DOSSIER:\n\n{dossier}\n\nVERIFICATION:\n\n{verification}"),
        run_id=live_run_id, topic=topic_label)
    draft = run_skill("article-writer",
        _with_brief(brief, f"DOSSIER:\n\n{dossier}\n\nVERIFICATION:\n\n{verification}\n\nPATTERN:\n\n{pattern}"),
        run_id=live_run_id, topic=topic_label)
    draft, review = _revision_loop(brief, dossier, verification, pattern, draft,
                                   live_run_id, topic_label)

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
    log.info("Topic pipeline complete. Run #%d pending review.", live_run_id)


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
        if s.get("status") == "active" and s.get("feed")
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

    # 3b. beat-monitor: scan primary govt feeds for under-covered leads
    log.info("Running beat-monitor (courts, ECI, RBI, CAG, govt portals)...")
    try:
        beat_output = run_skill("beat-monitor",
            "Run the beat monitor for today's cycle. "
            "Scan primary feeds: Kerala High Court, ECI, RBI, CAG, government portals. "
            "Surface under-covered leads only — skip anything already well-covered.")
        # Parse beat-monitor leads and add to pool as synthetic lead dicts
        for line in beat_output.splitlines():
            if line.startswith("## Lead"):
                all_leads.append({
                    "video_id": f"beat-{len(all_leads)}",
                    "video_url": "",
                    "title": line.replace("## Lead", "").strip(),
                    "source": "beat-monitor",
                    "source_id": "beat-monitor",
                    "throughline": line.replace("## ", "").strip(),
                    "claims": [],
                    "ingest_method": "beat_monitor",
                    "raw_beat_output": beat_output,
                })
        log.info("Beat monitor added %d lead(s) to the pool.", sum(1 for l in all_leads if l.get("source") == "beat-monitor"))
    except Exception as e:
        log.warning("Beat monitor failed: %s", e)

    # Pre-filter: drop entertainment / celebrity / gossip before touching the model
    before = len(all_leads)
    all_leads = [l for l in all_leads if not _is_entertainment(l.get("title", "") + " " + l.get("throughline", ""))]
    dropped = before - len(all_leads)
    if dropped:
        log.info("Pre-filter dropped %d entertainment/gossip lead(s).", dropped)

    if not all_leads:
        _notify("Thelivu daily cycle: no new leads today. Nothing to investigate.")
        log.info("No new leads. Exiting.")
        return

    # 4. news-monitor: pick the top lead by impact × under-coverage
    log.info("Running news-monitor on %d lead(s)...", len(all_leads))

    # Prepend source reliability context so the monitor can weight sources
    reliability = get_source_reliability()
    reliability_ctx = ""
    if reliability:
        lines = ["SOURCE RELIABILITY (from past pipeline runs):"]
        for r in reliability:
            pct = int(r["verified"] / r["total"] * 100) if r["total"] else 0
            lines.append(f"  {r['source']}: {r['total']} stories, {pct}% verified, {r['killed']} killed")
        reliability_ctx = "\n".join(lines) + "\n\nUse this to weight leads — prefer sources with higher verified rates.\n\n"

    leads_text = reliability_ctx + "LEADS TO EVALUATE:\n\n" + "\n\n---\n\n".join(
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

    # Build a story brief from the selected lead for downstream context
    rss_brief = (
        f"STORY_BRIEF\n"
        f"Geography: Follow the story — match scope to evidence and impact\n"
        f"Angle: {selected['throughline'][:200]}\n"
        f"Source: {selected['source']}\n"
        f"Scope: Investigate as reported; expand or narrow based on what the evidence shows\n"
        f"END_STORY_BRIEF"
    )
    topic_label = selected["throughline"][:120]

    # 4. news-investigator: build evidence dossier (uses web_search / Gemini)
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
    dossier = run_skill("news-investigator",
        _with_brief(rss_brief, investigate_input), topic=topic_label)

    # 5. source-verifier: trust gate (uses web_search / Gemini)
    log.info("Running source-verifier...")
    verification = run_skill("source-verifier",
        _with_brief(rss_brief, f"EVIDENCE DOSSIER TO VERIFY:\n\n{dossier}"),
        topic=topic_label)

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
            f"Reason:\n{verification}"
        )
        log.info("Story %s. Run #%d saved.", gate, run_id)
        return

    if gate == "FRAMING-FIX":
        log.info("FRAMING-FIX: continuing to write with framing notes.")

    # 6. pattern-synthesizer
    log.info("Running pattern-synthesizer...")
    pattern = run_skill("pattern-synthesizer",
        _with_brief(rss_brief, f"VERIFIED DOSSIER:\n\n{dossier}\n\nVERIFICATION REPORT:\n\n{verification}"),
        topic=topic_label)

    # 7. article-writer
    log.info("Running article-writer...")
    draft = run_skill("article-writer",
        _with_brief(rss_brief,
            f"VERIFIED DOSSIER:\n\n{dossier}\n\n"
            f"VERIFICATION REPORT:\n\n{verification}\n\n"
            f"PATTERN ANALYSIS:\n\n{pattern}"),
        topic=topic_label)

    # 8. editorial-reviewer with revision loop
    log.info("Running editorial-reviewer (with revision loop)...")
    draft, review = _revision_loop(rss_brief, dossier, verification, pattern, draft,
                                   None, topic_label)

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

def run_story_scout():
    """Weekly dig: pick one watchlist theme and produce a dig brief via story-scout."""
    log.info("Running story-scout on watchlist...")
    try:
        watchlist_text = WATCHLIST_YAML.read_text() if WATCHLIST_YAML.exists() else "(no watchlist yet)"
    except Exception:
        watchlist_text = "(watchlist unreadable)"

    prompt = (
        "Run the weekly story scout. Pick the highest-priority theme from the "
        "watchlist below that doesn't already have a story in progress, form a "
        "sharp falsifiable question, identify the primary records to pull, and "
        "output a dig brief.\n\n"
        f"WATCHLIST:\n{watchlist_text}"
    )
    try:
        brief = run_skill("story-scout", prompt)
        _notify(f"Story scout — new dig brief:\n\n{brief}")
        log.info("Story scout complete.")
    except Exception as e:
        log.error("Story scout failed: %s", e)


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
# Story tracker (runs weekly — follow up on published stories)
# ---------------------------------------------------------------------------

def run_story_tracker():
    """Weekly pass: check published stories for new developments, queue follow-ups."""
    log.info("Running story-tracker on published stories...")
    try:
        stories = get_published_stories(days=90)
        if not stories:
            log.info("Story tracker: no published stories to check yet.")
            return

        stories_text = "PUBLISHED STORIES TO CHECK FOR DEVELOPMENTS:\n\n"
        for s in stories:
            stories_text += (
                f"--- Story #{s['id']} ---\n"
                f"Throughline: {s['throughline']}\n"
                f"Published: {s['created_at']}\n"
                f"Source: {s['source']}\n"
                f"Summary: {(s.get('draft_summary') or '')[:400]}\n\n"
            )

        output = run_skill("story-tracker", stories_text)
        log.info("Story tracker complete.")

        # Queue any high/medium priority follow-ups as pending topics
        follow_ups = 0
        in_brief = False
        current_brief = []
        for line in output.splitlines():
            if line.startswith("- Follow-up brief:") and ("High" in output[max(0, output.find(line)-200):output.find(line)] or
                                                            "Medium" in output[max(0, output.find(line)-200):output.find(line)]):
                in_brief = True
                current_brief = [line.replace("- Follow-up brief:", "").strip()]
            elif in_brief and line.startswith("-"):
                in_brief = False
                if current_brief:
                    from shared.db import queue_topic
                    queue_topic("[FOLLOW-UP] " + " ".join(current_brief), source="story-tracker")
                    follow_ups += 1
                    current_brief = []

        if follow_ups:
            _notify(f"Story tracker: {follow_ups} follow-up(s) queued from {len(stories)} published stories.")
        else:
            _notify(f"Story tracker: checked {len(stories)} stories — no significant new developments this week.")

        kv_set("last_tracker_at", datetime.now(timezone.utc).isoformat())
    except Exception as e:
        log.error("Story tracker failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Meta-synthesizer (runs monthly — find patterns across all stories)
# ---------------------------------------------------------------------------

def run_meta_synthesis():
    """Monthly pass: find patterns across all published and killed stories."""
    log.info("Running meta-synthesis across all pipeline runs...")
    try:
        all_runs = get_all_runs_summary(limit=60)
        if len(all_runs) < 3:
            log.info("Meta-synthesis: fewer than 3 runs — skipping, not enough data.")
            return

        published = [r for r in all_runs if r.get("published")]
        killed = [r for r in all_runs if r.get("trust_gate") == "KILL"]
        held = [r for r in all_runs if r.get("status") in ("held", "hold")]

        runs_text = (
            f"ALL PIPELINE RUNS ({len(all_runs)} total, "
            f"{len(published)} published, {len(killed)} killed, {len(held)} held):\n\n"
        )
        for r in all_runs:
            outcome = "PUBLISHED" if r.get("published") else r.get("trust_gate") or r.get("status")
            runs_text += (
                f"#{r['id']} [{r['date']}] {outcome} — {r['throughline']}\n"
                f"  Source: {r['source']} | Gate: {r['trust_gate']}\n"
            )
            if r.get("review_summary"):
                runs_text += f"  Review: {r['review_summary'][:200]}\n"
            runs_text += "\n"

        output = run_skill("meta-synthesizer", runs_text)
        log.info("Meta-synthesis complete.")

        _notify(f"Monthly meta-synthesis complete — {len(all_runs)} stories reviewed.\n\n{output}")
        kv_set("last_meta_at", datetime.now(timezone.utc).isoformat())
    except Exception as e:
        log.error("Meta-synthesis failed: %s", e, exc_info=True)


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

    # Build raw data for finance-manager skill
    claude_in = claude_out = gemini_in = gemini_out = 0
    month_claude_in = month_claude_out = month_gemini_in = month_gemini_out = 0
    total_claude_in = total_claude_out = total_gemini_in = total_gemini_out = 0
    for row in rows:
        if "gemini" in (row["model"] or "").lower():
            gemini_in  += row["today_in"] or 0; gemini_out  += row["today_out"] or 0
            month_gemini_in  += row["month_in"] or 0; month_gemini_out  += row["month_out"] or 0
            total_gemini_in  += row["total_in"] or 0; total_gemini_out  += row["total_out"] or 0
        else:
            claude_in  += row["today_in"] or 0; claude_out  += row["today_out"] or 0
            month_claude_in  += row["month_in"] or 0; month_claude_out  += row["month_out"] or 0
            total_claude_in  += row["total_in"] or 0; total_claude_out  += row["total_out"] or 0

    today_usd  = _calc_cost("claude", claude_in, claude_out) + _calc_cost("gemini", gemini_in, gemini_out)
    month_usd  = _calc_cost("claude", month_claude_in, month_claude_out) + _calc_cost("gemini", month_gemini_in, month_gemini_out)
    total_usd  = _calc_cost("claude", total_claude_in, total_claude_out) + _calc_cost("gemini", total_gemini_in, total_gemini_out)

    data_prompt = (
        f"Date: {today}\n"
        f"Today — Claude: {claude_in} input + {claude_out} output tokens | "
        f"Gemini: {gemini_in} input + {gemini_out} output tokens\n"
        f"Today USD: ${today_usd:.6f} | Month USD: ${month_usd:.6f} | All-time USD: ${total_usd:.6f}\n"
        f"USD to INR: 84\n"
        f"Pipeline runs today: {runs_today}\n"
        f"Month — Claude: {month_claude_in}in + {month_claude_out}out | "
        f"Gemini: {month_gemini_in}in + {month_gemini_out}out\n"
        f"All-time — Claude: {total_claude_in}in + {total_claude_out}out | "
        f"Gemini: {total_gemini_in}in + {total_gemini_out}out"
    )
    try:
        report = run_skill("finance-manager", data_prompt)
    except Exception as e:
        log.warning("finance-manager skill failed (%s) — using raw data", e)
        report = (
            f"Thelivu Cost Report — {today}\n"
            f"Today: ₹{today_usd*_USD_TO_INR:.2f} | Month: ₹{month_usd*_USD_TO_INR:.2f} | "
            f"All-time: ₹{total_usd*_USD_TO_INR:.2f}\nRuns today: {runs_today}"
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
