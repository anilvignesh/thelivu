"""
Thelivu agent orchestrator — always-on pipeline loop.

Entry point: python -m engine.agents.orchestrator

Runs a pipeline cycle every CHECK_INTERVAL_HOURS (default 6), sleeping between:
  ingest → monitor → investigate → verify → pattern → write → review → Telegram

Agents can use web_search to verify claims and create_skill to add new skills
when they identify recurring editorial patterns.
"""

import difflib
import hashlib
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
    get_daily_costs,
    get_approved_sources,
    get_source_reliability,
    get_published_stories,
    get_all_runs_summary,
    save_proposal,
    set_proposal_msg_id,
    pop_next_topic,
    finish_topic,
    requeue_topic,
    enqueue_lead,
    get_queued_leads,
    mark_lead_processed,
    requeue_lead,
    expire_old_leads,
    kv_set,
    kv_get,
    queue_topic,
    create_dig,
    add_dig_update,
    update_dig,
    get_dig,
    list_digs,
    get_dig_updates,
    get_due_digs,
)
from engine.agents.skill_runner import run_skill, run_structured_skill, StructuredOutputError

# Structured-output markers each decision skill MUST emit (anchored to the exact
# formats in their SKILL.md). run_structured_skill validates + retries on these.
_M_GATE     = r"Trust gate:\s*\**\s*(KILL|HOLD|FRAMING-FIX|READY-FOR-HUMAN)"
_M_DECISION = r"Decision:\s*(PROCEED|PARK|DECLINE)"
_M_SELECTED = r"SELECTED_LEAD:\s*(NONE|\d+)"
_M_VERDICT  = r"VERDICT:\s*(PURSUE|DROP)"
# Anchored to a real heading at line start — a conversational "I'm ready to build
# the Evidence Dossier…" must NOT pass (that was the run #18 poisoning vector).
_M_DOSSIER  = r"^#{1,3}\s+(Evidence Dossier|Claims|Handoff note)"
_M_CAROUSEL = r"^SLIDE\s+1:\s*.+"

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


def _enrich_topic_with_link(topic_text):
    """If a submitted topic contains a URL, fetch its content and fold it into
    the topic text so topic-intake triages against the real material, not just a
    bare link. Handles both the [LINK] ingest marker and a URL pasted as a topic.

    YouTube → transcript (+ source-ingestor claims). Article → readable text.
    Fetch failures degrade gracefully: the link stays in the topic and the open
    web verifies. Never raises."""
    try:
        from ingestion.fetch import find_url, classify, fetch_article
    except Exception:
        return topic_text
    url = find_url(topic_text)
    if not url:
        return topic_text
    try:
        if classify(url) == "youtube":
            vid = _video_id(url)
            transcript = _get_transcript(vid)
            block = f"\n\n--- INGESTED VIDEO ({url}) ---\n"
            if transcript:
                block += f"TRANSCRIPT (one source's claims — verify):\n{transcript[:6000]}"
            else:
                block += "(No transcript available; treat the link as a lead and verify on the open web.)"
            log.info("Enriched topic with YouTube transcript: %s", url)
            return topic_text + block
        # Web article
        art = fetch_article(url)
        if art.get("text"):
            log.info("Enriched topic with article text (%d chars): %s", len(art["text"]), url)
            return (topic_text +
                    f"\n\n--- INGESTED ARTICLE ({url}) ---\n"
                    f"Title: {art.get('title','')}\n\n{art['text']}\n"
                    "(One source's reporting — a lead, not a finding. Verify independently.)")
        log.warning("Article fetch returned no text: %s", url)
        return topic_text
    except Exception as e:
        log.warning("Link enrichment failed for %s: %s — passing bare link", url, e)
        return topic_text


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
    # Browser UA — some publishers UA-block feedparser's default agent. (Not a
    # cure-all: IndiaSpend's feed turned out to be valid-but-EMPTY under any UA;
    # see HANDOFF §5.18. This just removes one silent failure mode.)
    feed = feedparser.parse(
        feed_url,
        agent="Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
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


def _tg_post(chat_id, text, reply_markup=None, parse_mode=None):
    """Send a single message — caller must ensure len(text) ≤ 4096."""
    payload = {"chat_id": str(chat_id), "text": text, "disable_web_page_preview": False}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        # An HTML send can fail if a 4096-cut split a tag/entity ("can't parse
        # entities"). Never lose the message (or an attached approval keyboard) —
        # retry once as plain text with the markup stripped of tags.
        if parse_mode:
            log.warning("Telegram HTML send failed (%s) — retrying as plain text", e)
            plain = re.sub(r"<[^>]+>", "", text)
            return _tg_post(chat_id, plain, reply_markup=reply_markup, parse_mode=None)
        log.error("Telegram send failed: %s", e)
        return None


def _tg_post_photo(chat_id, photo_path, caption="", reply_markup=None):
    """Send a local image file as a Telegram photo message. Returns
    (message_id, file_url) — file_url is Telegram's own CDN link for the
    largest photo size Telegram generated, reusable as a public image_url
    elsewhere (Instagram's Graph API needs one). Telegraph's unofficial
    upload endpoint proved too unreliable ("Unknown error" on valid images)
    to depend on for this."""
    payload = {"chat_id": str(chat_id)}
    if caption:
        payload["caption"] = caption[:1024]
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        with open(photo_path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data=payload,
                files={"photo": f},
                timeout=30,
            )
        r.raise_for_status()
        result = r.json().get("result", {})
        message_id = result.get("message_id")
        photos = result.get("photo") or []
        file_id = photos[-1]["file_id"] if photos else None
        file_url = _tg_file_url(file_id) if file_id else None
        return message_id, file_url
    except Exception as e:
        log.error("Telegram photo send failed: %s", e)
        return None, None


def _tg_file_url(file_id):
    """Resolve a Telegram file_id to its public CDN URL."""
    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=15,
    )
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"


def _tg_post_media_group(chat_id, photo_paths, caption, reply_markup):
    """Send up to 10 local images as one Telegram album (sendMediaGroup), then
    a separate follow-up text message carrying the Approve/Kill buttons —
    Telegram's API doesn't allow reply_markup on sendMediaGroup itself.
    Returns the button message's id (that's the one the callback handler
    needs to clear after a tap)."""
    photo_paths = photo_paths[:10]
    files = {}
    media = []
    opened = []
    try:
        for i, path in enumerate(photo_paths):
            f = open(path, "rb")
            opened.append(f)
            key = f"photo{i}"
            files[key] = f
            media.append({"type": "photo", "media": f"attach://{key}"})
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup",
            data={"chat_id": str(chat_id), "media": json.dumps(media)},
            files=files,
            timeout=60,
        )
        r.raise_for_status()
    except Exception as e:
        log.error("Telegram media group send failed: %s", e)
        return None
    finally:
        for f in opened:
            f.close()

    return _tg_post(chat_id, caption, reply_markup=reply_markup)


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
    """Send a short status notification to Anil's draft chat (plain text)."""
    _tg_send_long(TELEGRAM_DRAFT_CHAT_ID, text)


# ── Owner-facing cards — clean HTML, long reports offloaded to Telegraph ────────

def _esc(s):
    import html as _html
    return _html.escape(str(s), quote=False)


def _md_to_tg_html(s, limit=1000):
    """LLM output arrives as Markdown, but owner cards send as Telegram HTML —
    without this the chat shows literal **asterisks** and ### hashes (Anil's
    'rendering issue', 2026-07-14). Escapes first, then converts the handful of
    Markdown forms the skills actually emit. Truncates the RAW text at a line
    boundary before converting, so a cut can never split an HTML tag (which
    would make Telegram reject the whole message)."""
    s = (s or "").strip()
    if len(s) > limit:
        s = s[:limit].rsplit("\n", 1)[0] or s[:limit]
        s += " …"
    lines = []
    for line in _esc(s).splitlines():
        l = line.rstrip()
        m = re.match(r"^\s*#{1,6}\s+(.*)$", l)
        if m:
            lines.append(f"<b>{m.group(1)}</b>")
            continue
        lines.append(re.sub(r"^(\s*)[-*]\s+", r"\1• ", l))
    s = "\n".join(lines)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
    # href is already entity-escaped (&amp; is valid inside an attribute)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def _report_link(title, markdown):
    """Publish a long report to Telegraph; return an HTML link, or '' on failure."""
    if not markdown:
        return ""
    try:
        from publishing.telegram import report_to_telegraph
        import html as _html
        url = report_to_telegraph(title, markdown)
        return f'▸ <a href="{_html.escape(url, quote=True)}">Full report</a>'
    except Exception as e:
        log.warning("Telegraph report failed (%s) — trimming inline", e)
        return _md_to_tg_html(markdown, limit=1200)


def _reason_from_report(report):
    """Pull a one-line reason out of a verification/review report."""
    for label in ("Blocking claims", "Required before it moves", "Required Edit"):
        m = re.search(rf"{label}\s*[:\-]?\s*(.+)", report or "")
        if m and m.group(1).strip() and m.group(1).strip() not in ("[", "—"):
            return m.group(1).strip()[:300]
    return ""


def _notify_card(emoji, title, body="", report_title=None, report_md=None,
                 reply_markup=None):
    """Build and send a clean HTML card to the owner. Long report_md goes to
    Telegraph as a 'Full report' link instead of flooding the chat."""
    parts = [f"{emoji} <b>{_esc(title)}</b>"]
    if body:
        parts += ["", body]
    link = _report_link(report_title or title, report_md)
    if link:
        parts += ["", link]
    html = "\n".join(parts)
    _tg_post(TELEGRAM_DRAFT_CHAT_ID, html[:4096], reply_markup=reply_markup,
             parse_mode="HTML")


def send_for_approval(run_id, draft_text, verification_report, review_text):
    """Route the finished draft based on APPROVAL_MODE."""
    if APPROVAL_MODE == "telegram":
        _send_via_telegram(run_id, draft_text, verification_report, review_text)
    else:
        _save_to_file(run_id, draft_text, verification_report, review_text)


def _parse_legal_flag(review_text):
    """Extract LEGAL-FLAG and LEGAL-REASON from editorial reviewer output.

    Anchored so an indented 'LEGAL-FLAG: YES' is still caught, and the verdict is
    matched as a whole word (not a stray 'YES' inside 'LEGAL-FLAG: NO — ...YES...')
    — a missed or spurious legal flag is a safety problem either way."""
    text = review_text or ""
    fm = re.search(r"^\s*LEGAL-FLAG:\s*(YES|NO)\b", text, re.IGNORECASE | re.MULTILINE)
    flag = bool(fm) and fm.group(1).upper() == "YES"
    rm = re.search(r"^\s*LEGAL-REASON:\s*(.+)", text, re.IGNORECASE | re.MULTILINE)
    reason = rm.group(1).strip() if rm else ""
    return flag, reason


def _send_via_telegram(run_id, draft_text, verification_report, review_text):
    legal_flag, legal_reason = _parse_legal_flag(review_text)

    # Persist legal flag to DB
    if legal_flag:
        update_run_legal_flag(run_id, True, legal_reason)

    # The real headline, not the scaffolding header or the italic preamble —
    # this title also names the draft-preview Telegraph page, and the ad-hoc
    # first-line scan this replaces shipped a dozen preview pages titled
    # "*From Thelivu — explanatory journalism…".
    from publishing.parser import extract_headline
    title = extract_headline(draft_text)[:120] or f"Run #{run_id}"

    parts = [f"📰 <b>New story ready — run #{run_id}</b>", "", f"<b>{_esc(title)}</b>"]
    if legal_flag:
        parts += ["", "⚠️ <b>LEGAL REVIEW REQUIRED before approving.</b>",
                  f"Reason: {_esc(legal_reason)}",
                  "Do NOT approve until a legal read has been done."]

    # Charter §5 furniture check — warn the human if the mandatory confidence label
    # or sources block is missing, so it's caught before it reaches readers.
    _d = draft_text or ""
    missing = []
    if not re.search(r"Confidence\s*[:—-]", _d, re.IGNORECASE):
        missing.append("confidence label")
    if not re.search(r"^\s*\*?\s*Sources?\s*:", _d, re.IGNORECASE | re.MULTILINE):
        missing.append("sources block")
    if missing:
        parts += ["", f"⚠️ <b>Missing required furniture:</b> {_esc(', '.join(missing))} "
                      "(charter §5). Add it before approving."]

    # Offer the draft as a clean Telegraph read; fall back to raw chunks if it fails.
    preview_ok = False
    try:
        from publishing.telegram import report_to_telegraph
        import html as _html
        url = report_to_telegraph(title, draft_text)
        parts += ["", f'▸ <a href="{_html.escape(url, quote=True)}">Read the draft</a>, then tap to decide.']
        preview_ok = True
    except Exception as e:
        log.warning("Draft preview to Telegraph failed (%s) — sending raw", e)
        parts += ["", "Read the draft below, then tap to decide."]

    summary = "\n".join(parts)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✓ Approve", "callback_data": f"approve_{run_id}"},
            {"text": "✗ Kill",    "callback_data": f"kill_{run_id}"},
            {"text": "⏸ Hold",   "callback_data": f"hold_{run_id}"},
        ]]
    }
    msg_id = _tg_post(TELEGRAM_DRAFT_CHAT_ID, summary[:_TG_LIMIT], reply_markup=keyboard,
                      parse_mode="HTML")
    update_run(run_id, tg_msg_id=msg_id)
    if not preview_ok:
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
    # Give the reviewer the recent archive so its charter-mandated anti-monotony /
    # self-similarity check (same opening device / throughline / house line) can
    # actually run against real prior pieces instead of nothing.
    archive = _published_context(
        header="RECENT PUBLISHED PIECES (check this draft isn't a structural repeat):")
    review = run_skill("editorial-reviewer",
        _with_brief(brief, f"{archive}DRAFT:\n\n{draft}\n\nVERIFICATION REPORT:\n\n{verification}"),
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
        dossier = run_structured_skill(
            "news-investigator", _with_brief(brief, revision_prompt),
            marker=_M_DOSSIER, run_id=run_id, topic=topic_label)

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
    """Read the verifier's gate from its anchored '## Trust gate: <D>' line.
    Returns the decision, or None if the line is absent (caller halts loudly
    instead of silently defaulting to HOLD)."""
    m = re.search(_M_GATE, text or "", re.IGNORECASE)
    return m.group(1).upper() if m else None


def _undersourced_load_bearing(verification):
    """Charter §4.1 backstop. Parse the verifier's per-claim table and return any
    LOAD-BEARING claim marked 'Verified' that lists FEWER THAN TWO independent
    sources — i.e. the model called something confirmed on a single source, which
    the two-source rule forbids.

    Table columns: | Claim | Load-bearing | Verdict | Independent sources | ... |
    This only ever makes the gate STRICTER, and only on rows it can parse cleanly;
    an unparseable/absent table yields [] so it can never falsely block a story."""
    out = []
    for line in (verification or "").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        # Separator row (|---|---|) — only dashes/colons/spaces.
        if set(s) <= {"|", "-", ":", " "}:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 4:
            continue
        claim, lb, verdict, sources = cells[0], cells[1].lower(), cells[2].lower(), cells[3]
        # Header row — the load-bearing/verdict cells carry their column names.
        if lb in ("load-bearing", "load bearing") or verdict == "verdict":
            continue
        if "yes" not in lb:
            continue
        if verdict != "verified":          # exact: 'unverified'/'failed' already HOLD/KILL
            continue
        nums = re.findall(r"\d+", sources)
        if nums and int(nums[0]) < 2:
            out.append(claim[:120])
    return out


def _halt_run(run_id, stage, raw):
    """Fail-loud: a stage returned no usable structured output even after a retry.
    Park the run as needs_attention (NOT a silent HOLD) and tell the owner."""
    if run_id is not None:
        update_run(run_id, status="needs_attention", trust_gate="NEEDS-ATTENTION",
                   verification_report=(raw or "")[:4000])
    _notify_card(
        "⚠️", f"Run #{run_id} halted at “{stage}”",
        body=("It returned no valid structured output after a retry, so the pipeline "
              "stopped rather than publish or silently hold garbage. Nothing was posted."),
        report_title=f"Halt — {stage} — run #{run_id}", report_md=raw,
    )
    log.error("Run #%s halted at %s (no structured output).", run_id, stage)


def _provider_from_err(err):
    """Best-effort guess at which provider caused an outage, from the error text."""
    m = str(err).lower()
    if any(k in m for k in ("gemini", "google", "generativelanguage", "resource_exhausted", "aistudio")):
        return "Gemini"
    if any(k in m for k in ("anthropic", "claude", "overloaded", "x-api-key")):
        return "Claude"
    return "Unknown provider"


def _pause_run(run_id, label, err):
    """A provider went down mid-spine. Drop the half-finished run and let the
    caller re-queue the work, so it resumes when credit returns — never lost,
    never run on a substitute engine."""
    provider = _provider_from_err(err)
    if run_id is not None:
        update_run(run_id, status="dropped", trust_gate="PAUSED")
    _notify_card(
        "⏸", f"Paused — {provider} unavailable",
        body=(f"<b>{_esc(label)}</b>\n\n<b>{provider}</b> is out of credit or unreachable. "
              f"The run paused and the work went back in the queue. It resumes "
              f"automatically when {provider} is back — nothing was lost.\n\n"
              f"<i>{_esc(str(err)[:200])}</i>"),
    )
    log.warning("Paused run #%s — %s (%s): %s", run_id, provider, label, err)


def _published_context(days=45, header="RECENTLY PUBLISHED (do not repeat these):"):
    """A compact list of what the channel already ran — fed to news-monitor (so it
    doesn't re-select a covered topic) and to the reviewer (anti-monotony /
    self-similarity check the charter mandates). Empty string if nothing/failure."""
    try:
        rows = get_published_stories(days=days)
    except Exception as e:
        log.warning("Could not load published context: %s", e)
        return ""
    if not rows:
        return ""
    lines = [header]
    for r in rows[:15]:
        d = str(r.get("created_at", ""))[:10]
        lines.append(f"  - [{d}] {(r.get('throughline') or '')[:140]}")
    return "\n".join(lines) + "\n\n"


# A transient provider/infra failure (retry forever — not the item's fault) vs a
# content/code failure that reliably breaks on this specific item (cap + drop, so
# it can't head-of-line-block the queue or loop until the 7-day TTL).
_OUTAGE_MARKERS = (
    "429", "quota", "rate limit", "resource_exhausted", "resource exhausted",
    "overloaded", "unavailable", "503", "502", "500", "timeout", "timed out",
    "connection", "insufficient", "balance", "billing", "credit",
)
_MAX_SPINE_FAILS = 3


def _is_provider_outage(exc):
    m = str(exc).lower()
    return any(k in m for k in _OUTAGE_MARKERS)


def _route_spine_failure(run_id, label, err, fail_key, requeue_fn, drop_fn):
    """Decide what a mid-spine exception means and act:
      • provider outage  → pause + requeue (transient; resumes when credit's back)
      • content/code bug  → count it; requeue until _MAX_SPINE_FAILS, then DROP it
        (notify) so a poison item can't block the queue or loop for 7 days."""
    if _is_provider_outage(err):
        requeue_fn()
        _pause_run(run_id, label, err)
        return
    n = int(kv_get(fail_key) or 0) + 1
    if n >= _MAX_SPINE_FAILS:
        kv_set(fail_key, "")
        if run_id is not None:
            update_run(run_id, status="needs_attention", trust_gate="NEEDS-ATTENTION")
        drop_fn()
        _notify_card(
            "⚠️", "Dropped a repeatedly-failing item",
            body=(f"<b>{_esc(label)}</b>\n\nThis failed {n}× with a non-outage error, so "
                  f"it was dropped to stop it blocking the queue. Not a provider outage.\n\n"
                  f"<i>{_esc(str(err)[:200])}</i>"),
        )
        log.error("Dropped poison item after %d fails (%s): %s", n, fail_key, err)
    else:
        kv_set(fail_key, str(n))
        requeue_fn()
        log.warning("Item %s failed %d× (non-outage, will retry): %s", fail_key, n, err)


def _run_spine(brief, investigate_input, run_id, topic_label, display_label,
               display_title, on_pause):
    """The shared investigation spine: investigate → verify → trust gate →
    pattern → write → editorial review. Used by both the RSS daily cycle and the
    owner-topic path so the logic lives in exactly one place.

    Returns (draft, review, verification, gate) on success. Returns None when the
    run terminated inside the spine — KILL/HOLD (notified + DB-updated here), a
    malformed stage (halted), or a provider outage (on_pause callback re-queues
    the work). The caller only handles the success case.
    """
    try:
        dossier = run_structured_skill(
            "news-investigator", _with_brief(brief, investigate_input),
            marker=_M_DOSSIER, run_id=run_id, topic=topic_label)
        verification = run_structured_skill(
            "source-verifier", _with_brief(brief, f"EVIDENCE DOSSIER TO VERIFY:\n\n{dossier}"),
            marker=_M_GATE, run_id=run_id, topic=topic_label)

        gate = _parse_gate(verification)
        log.info("Trust gate: %s", gate)

        # Two-source backstop: if the verifier passed a story (READY / FRAMING-FIX)
        # while its own table shows a load-bearing claim "Verified" on <2 sources,
        # override to HOLD. This catches model leniency the prose verdict misses
        # (the kind that let a single-sourced load-bearing claim publish before).
        if gate in ("READY-FOR-HUMAN", "FRAMING-FIX"):
            undersourced = _undersourced_load_bearing(verification)
            if undersourced:
                log.warning("Two-source backstop forced HOLD: %s", undersourced)
                gate = "HOLD"
                verification += (
                    "\n\n## Two-source backstop (automated)\n"
                    "Forced HOLD — load-bearing claim(s) marked Verified but listing "
                    "fewer than two independent sources (charter §4.1):\n"
                    + "\n".join(f"- {c}" for c in undersourced)
                )

        if gate in ("KILL", "HOLD"):
            update_run(run_id, trust_gate=gate, verification_report=verification, status=gate.lower())
            reason = _reason_from_report(verification)
            verb = "Killed" if gate == "KILL" else "Held"
            _notify_card(
                "❌" if gate == "KILL" else "⏸",
                f"{display_label} {verb} — run #{run_id}",
                body=f"<b>{_esc(display_title[:160])}</b>" + (f"\n\n{_md_to_tg_html(reason, limit=300)}" if reason else ""),
                report_title=f"Verification — run #{run_id}", report_md=verification,
            )
            return None

        # On FRAMING-FIX the facts hold but the verifier flagged how they're framed.
        # Surface that requirement to the writer up front (not buried in the report);
        # the editorial-reviewer then re-checks framing and can still send it back.
        framing_directive = ""
        if gate == "FRAMING-FIX":
            fix = _reason_from_report(verification)
            log.info("FRAMING-FIX: %s", fix or "(see report)")
            framing_directive = (
                "FRAMING FIX REQUIRED (the facts hold; the framing does not). The "
                "verifier flagged this — apply it and let the evidence speak, do not "
                f"assert beyond it:\n{fix or '(see the verification report below)'}\n\n"
            )

        update_run(run_id, trust_gate=gate, status="writing")
        pattern = run_skill("pattern-synthesizer",
            _with_brief(brief, f"VERIFIED DOSSIER:\n\n{dossier}\n\nVERIFICATION REPORT:\n\n{verification}"),
            run_id=run_id, topic=topic_label)
        draft = run_skill("article-writer",
            _with_brief(brief,
                f"{framing_directive}"
                f"VERIFIED DOSSIER:\n\n{dossier}\n\n"
                f"VERIFICATION REPORT:\n\n{verification}\n\n"
                f"PATTERN ANALYSIS:\n\n{pattern}"),
            run_id=run_id, topic=topic_label)
        draft, review = _revision_loop(brief, dossier, verification, pattern, draft,
                                       run_id, topic_label)
        return (draft, review, verification, gate)
    except StructuredOutputError as e:
        _halt_run(run_id, e.skill_name, e.raw)
        return None
    except Exception as e:
        if _is_provider_outage(e):
            on_pause(e)
        else:
            log.error("Spine code bug (not a provider outage): %s", e, exc_info=True)
            _halt_run(run_id, "spine", str(e))
        return None


def _parse_selected_lead(text, n_leads):
    """Read the 'SELECTED_LEAD: <n|NONE>' block from news-monitor output.

    Returns (status, idx): ('none', None) when the monitor found nothing worth
    investigating, ('ok', 0-based index) for a valid pick, ('unparsed', None)
    when the block is missing/out of range (caller falls back to fuzzy match).
    """
    m = re.search(r"SELECTED_LEAD:\s*(NONE|\d+)", text, re.IGNORECASE)
    if not m:
        return ("unparsed", None)
    val = m.group(1).upper()
    if val == "NONE":
        return ("none", None)
    idx = int(val) - 1
    return ("ok", idx) if 0 <= idx < n_leads else ("unparsed", None)


def _norm_line(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _resolve_selected_lead(text, all_leads, idx):
    """Map news-monitor's pick back to an INPUT lead. Returns (lead, how).

    Two numbering schemes collide here. We hand the monitor leads numbered
    'Lead 1..N' in INPUT order, but SKILL.md tells it to emit its own queue
    '## Lead 1..n' in RANKED order after dropping exclusions. Indexing all_leads
    by the output's number is therefore only correct by accident: on 2026-07-22 a
    monitor that had chosen an Andhra land-records story emitted SELECTED_LEAD: 1
    and the cycle went off to investigate 'Chemical leak after truck overturns on
    Tumakuru-Bengaluru highway' — input lead 1 — which the skill's own hard
    exclusions would have dropped on sight.

    So the number is no longer authoritative: the monitor must echo the
    throughline it picked, and we match on that. The index is the fallback for
    output that predates the contract.
    """
    m = re.search(r"SELECTED_THROUGHLINE:\s*(.+)", text)
    want = _norm_line(m.group(1)) if m else ""
    if not want:
        return all_leads[idx], "index (no SELECTED_THROUGHLINE)"

    best, score = None, 0.0
    for lead in all_leads:
        s = difflib.SequenceMatcher(None, want, _norm_line(lead.get("throughline"))).ratio()
        if s > score:
            best, score = lead, s
    if best is not None and score >= 0.60:
        return best, f"throughline match {score:.2f}"
    return all_leads[idx], f"index (throughline unmatched, best {score:.2f})"


def _newsworthiness_verdict(selected):
    """Absolute-floor gate on the selected lead, run before the expensive
    investigation spine. Returns (pursue: bool, reason: str). Fails OPEN — a gate
    error must never silently drop a real story."""
    lead = (
        f"Throughline: {selected.get('throughline', '')}\n"
        f"Source: {selected.get('source', '')}\n"
        "Claims: " + "; ".join(c.get("text", "")[:120] for c in selected.get("claims", [])[:5])
    )
    priors_block = ""
    try:
        from engine.agents.learning import format_priors_block
        priors_block = format_priors_block()
        if priors_block:
            priors_block = "\n\n" + priors_block
    except Exception as e:
        log.warning("Learned priors unavailable for gate: %s", e)
    try:
        out = run_skill("newsworthiness-gate", f"SELECTED LEAD:\n\n{lead}{priors_block}", max_tokens=200)
    except Exception as e:
        log.warning("Newsworthiness gate failed (%s) — defaulting to PURSUE", e)
        return True, "gate error — defaulted to pursue"
    rm = re.search(r"REASON:\s*(.+)", out)
    reason = rm.group(1).strip()[:200] if rm else out.strip()[:160]
    drop = re.search(r"VERDICT:\s*DROP", out, re.IGNORECASE)
    return (not drop, reason)


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
    """Run the full pipeline on an owner-submitted topic via topic-intake.

    Hardened: topic-intake must return a structured Decision; only the extracted
    STORY_BRIEF (never the raw, possibly-chatty reply) is passed downstream; the
    newsworthiness gate runs before the expensive spine; and any stage that fails
    to return valid structured output halts the run loudly instead of cascading.
    """
    topic_id = pending["id"]
    topic_text = pending["topic"]
    topic_label = topic_text[:120]

    # If the topic is (or contains) a pasted link, fetch its content first so
    # intake triages the real material. [LINK] topics come from queue_ingest.
    if "[LINK]" in topic_text or "http://" in topic_text or "https://" in topic_text:
        topic_text = _enrich_topic_with_link(topic_text)

    log.info("Running topic-intake on: %s", topic_label[:80])
    try:
        intake_output = run_structured_skill(
            "topic-intake",
            f"SUBMITTED TOPIC:\n\n{topic_text}\n\nSource: {pending.get('source', 'owner')}",
            marker=_M_DECISION,
        )
    except StructuredOutputError as e:
        finish_topic(topic_id)
        _halt_run(None, "topic-intake", e.raw)
        return
    except Exception as e:
        # Provider outage → requeue and wait; a content/code failure that keeps
        # breaking gets capped and dropped so it can't head-of-line-block the queue.
        _route_spine_failure(
            None, topic_text[:120], e, fail_key=f"topicfail_{topic_id}",
            requeue_fn=lambda: requeue_topic(topic_id),
            drop_fn=lambda: finish_topic(topic_id),
        )
        return

    decision = re.search(_M_DECISION, intake_output, re.IGNORECASE).group(1).upper()
    if decision in ("PARK", "DECLINE"):
        finish_topic(topic_id)
        _notify_card(
            "🚫" if decision == "DECLINE" else "🅿️",
            f"Topic {decision.title()}d by intake",
            body=_esc(topic_text[:200]),
            report_title=f"Intake {decision} — {topic_text[:50]}", report_md=intake_output,
        )
        log.info("Topic %s by topic-intake.", decision)
        return

    # PROCEED — require a clean STORY_BRIEF; pass ONLY that downstream (no raw reply).
    brief = _extract_brief(intake_output)
    if not brief:
        finish_topic(topic_id)
        _notify_card(
            "⚠️", "Intake said PROCEED but gave no brief",
            body="Not investigating (it would run unframed).",
            report_title="Intake output", report_md=intake_output,
        )
        log.warning("PROCEED without STORY_BRIEF — skipping.")
        return

    # Absolute-floor newsworthiness gate before any expensive work.
    angle = ""
    m_angle = re.search(r"Angle:\s*(.+)", brief)
    if m_angle:
        angle = m_angle.group(1).strip()
    pursue, why = _newsworthiness_verdict(
        {"throughline": angle or topic_text, "source": "owner-topic", "claims": []}
    )
    if not pursue:
        finish_topic(topic_id)
        _notify_card(
            "🗑", "Topic dropped — not our kind of story",
            body=f"<b>Topic:</b> {_esc(topic_text[:200])}\n<b>Reason:</b> {_md_to_tg_html(why, limit=300)}",
        )
        log.info("Owner topic dropped by newsworthiness gate: %s", why)
        return

    log.info("Topic accepted (PROCEED). Brief:\n%s", brief)
    live_run_id = save_run(
        video_id=f"topic-{topic_id}",
        source=pending.get("source", "owner"),
        throughline=(angle or topic_text)[:200],
        trust_gate="investigating",
        status="investigating",
    )
    finish_topic(topic_id)

    def _on_pause(e):
        _route_spine_failure(
            live_run_id, (angle or topic_text)[:120], e,
            fail_key=f"topicfail_{topic_id}",
            requeue_fn=lambda: requeue_topic(topic_id),
            drop_fn=lambda: finish_topic(topic_id),
        )

    result = _run_spine(
        brief, f"TOPIC AS SUBMITTED:\n{topic_text}", live_run_id, topic_label,
        display_label="Your topic was", display_title=(angle or topic_text),
        on_pause=_on_pause,
    )
    if result is None:
        return
    draft, review, verification, gate = result

    update_run(live_run_id,
        throughline=(angle or topic_text)[:200],
        trust_gate=gate,
        draft_text=draft,
        review_text=review,
        verification_report=verification,
        status="pending_human",
    )
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
    # Any DB-approved source with a feed ingests — ingest_source() handles both
    # youtube and web/rss platforms. The old platform=='youtube' filter silently
    # dropped every RSS source approved via bot/dashboard (found 2026-07-26 when
    # the command center grew candidate activation).
    db_sources = [s for s in get_approved_sources() if s.get("feed_url")]
    # Normalise db sources to match yaml shape
    for s in db_sources:
        s["feed"] = s.pop("feed_url", None)
        # handle is often "" for RSS sources added via dashboard — fall through
        # to name/id rather than tagging their leads with an empty source id.
        s["id"] = s.get("handle") or s.get("name") or str(s["id"])
    active_sources = yaml_sources + db_sources
    log.info("Active sources: %s", [s["id"] for s in active_sources])

    # 3. Ingest new items from all active sources
    all_leads = []
    for source in active_sources:
        try:
            items = ingest_source(source)
            all_leads.extend(items)
            log.info("%s: %d new item(s)", source["name"], len(items))
            # Track consecutive silent cycles — alert at 3, reset on new items
            sid = str(source.get("id", source.get("name", "?"))).replace(" ", "_")
            if items:
                kv_set(f"src_silent_{sid}", "0")
            else:
                n = int(kv_get(f"src_silent_{sid}") or 0) + 1
                kv_set(f"src_silent_{sid}", str(n))
                # Alert at 3, then re-alert every 100 silent cycles — the
                # one-shot ==3 alert let dead feeds sit unnoticed for weeks
                # once the single ping scrolled by (audit 2026-07-26).
                if n == 3 or n % 100 == 0:
                    _notify_card(
                        "📡", f"Source silent for 3+ cycles: {source['name']}",
                        body=f"No new items from <b>{_esc(source['name'])}</b> for 3 consecutive cycles.\n"
                             f"Check if the feed URL is still valid: "
                             f"<code>{_esc(str(source.get('feed', source.get('feed_url', '')))[:100])}</code>",
                    )
        except Exception as e:
            log.error("Ingest failed for %s: %s", source["name"], e)

    # 3b. beat-monitor: scan primary govt feeds for under-covered leads.
    # Once per day, not every cycle — courts/ECI/RBI/CAG don't post intraday, and
    # this is a grounded (search-billed) Gemini call. Leads it finds sit in the
    # same 7-day queue, so nothing is lost by scanning daily instead of 4×/day.
    last_beat = kv_get("last_beat_at")
    beat_due = (not last_beat) or (
        (datetime.now(timezone.utc) - datetime.fromisoformat(last_beat)).total_seconds() >= 20 * 3600
    )
    if not beat_due:
        log.info("beat-monitor already ran today — skipping this cycle.")
    else:
        log.info("Running beat-monitor (courts, ECI, RBI, CAG, govt portals)...")
        try:
            kv_set("last_beat_at", datetime.now(timezone.utc).isoformat())
            beat_output = run_skill("beat-monitor",
                "Run the beat monitor for today's cycle. "
                "Scan primary feeds: Kerala High Court, ECI, RBI, CAG, government portals. "
                "Surface under-covered leads only — skip anything already well-covered.")
            # Parse beat-monitor leads and add to pool as synthetic lead dicts
            for line in beat_output.splitlines():
                if line.startswith("## Lead"):
                    # Strip "## Lead N: " prefix to get a clean throughline, e.g.
                    # "## Lead 1: CAG flags..." → "CAG flags..."
                    raw = line.lstrip("# ").strip()
                    throughline = re.sub(r"^Lead\s+\d+\s*:\s*", "", raw).strip() or raw
                    # Content-based id so the SAME beat lead dedups across cycles and
                    # DIFFERENT leads never collide. (A positional f"beat-{len}" id
                    # collided on RSS-volume coincidence and permanently blocked slots.)
                    vid = "beat-" + hashlib.sha1(throughline.encode("utf-8")).hexdigest()[:16]
                    all_leads.append({
                        "video_id": vid,
                        "video_url": "",
                        "title": throughline,
                        "source": "beat-monitor",
                        "source_id": "beat-monitor",
                        "throughline": throughline,
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

    # Capture: persist newly-found leads to the queue so they survive a provider
    # outage. This is the cheap "find leads, hold them" stage — it runs whether or
    # not the expensive spine can.
    captured = sum(1 for l in all_leads if enqueue_lead(l))
    expired = expire_old_leads(max_age_days=7)
    log.info("Captured %d new lead(s); expired %d stale.", captured, expired)

    # Process: draw from the accumulated queue (not just this cycle's finds), so a
    # backlog built up during an outage drains once credit returns.
    # Pull a generous window so older queued leads still reach the selector and
    # aren't truncated out (and silently expired) by a burst of fresh ones.
    all_leads = get_queued_leads(limit=60, max_age_days=7)
    if not all_leads:
        _notify("Thelivu daily cycle: no leads in the queue. Nothing to investigate.")
        log.info("Empty lead queue. Exiting.")
        return

    # 4. news-monitor: pick the top lead by impact × under-coverage
    log.info("Running news-monitor on %d queued lead(s)...", len(all_leads))

    # Prepend source reliability context so the monitor can weight sources
    reliability = get_source_reliability()
    reliability_ctx = ""
    if reliability:
        lines = ["SOURCE RELIABILITY (from past pipeline runs):"]
        for r in reliability:
            pct = int(r["verified"] / r["total"] * 100) if r["total"] else 0
            lines.append(f"  {r['source']}: {r['total']} stories, {pct}% verified, {r['killed']} killed")
        reliability_ctx = "\n".join(lines) + "\n\nUse this to weight leads — prefer sources with higher verified rates.\n\n"

    # Learned priors: the engine's own outcome history as an advisory signal
    # (docs/learning-loop.md). Selection bias only — never verification.
    try:
        from engine.agents.learning import format_priors_block
        priors_block = format_priors_block()
        if priors_block:
            reliability_ctx += priors_block + "\n\n"
    except Exception as e:
        log.warning("Learned priors unavailable: %s", e)

    # Archive context so the monitor doesn't re-select a story we've already run.
    published_ctx = _published_context(
        header="ALREADY PUBLISHED — do not pick a lead that merely repeats one of these:")
    # The skill's generic output format numbers leads by RANK in its own queue.
    # This pipeline resolves the pick against the INPUT list below, so the two
    # numberings must be disambiguated explicitly or the wrong story gets
    # investigated (see _resolve_selected_lead).
    selection_contract = (
        "SELECTION CONTRACT (this pipeline — overrides the skill's generic numbering):\n"
        "  SELECTED_LEAD must be the **input** Lead number from the list below\n"
        "  (e.g. `SELECTED_LEAD: 51`), NOT the position in your own ranked output.\n"
        "  Immediately after it, emit one more line:\n"
        "    SELECTED_THROUGHLINE: <that input lead's Throughline, copied exactly>\n"
        "  The orchestrator matches on the throughline, so the two must agree.\n"
        "  For SELECTED_LEAD: NONE, omit SELECTED_THROUGHLINE.\n\n"
    )
    leads_text = published_ctx + reliability_ctx + selection_contract + "LEADS TO EVALUATE:\n\n" + "\n\n---\n\n".join(
        f"**Lead {i+1}** (source: {item['source']})\n"
        f"Throughline: {item['throughline']}\n"
        f"URL: {item['video_url']}\n"
        f"Claims ({len(item['claims'])}): "
        + "; ".join(c.get("text", "")[:80] for c in item["claims"][:3])
        for i, item in enumerate(all_leads)
    )

    try:
        monitor_output = run_structured_skill("news-monitor", leads_text, marker=_M_SELECTED)
    except StructuredOutputError as e:
        _notify("Thelivu daily cycle: news-monitor returned no usable selection after a retry — "
                "skipping this cycle, nothing investigated.")
        log.error("news-monitor: no SELECTED_LEAD. Raw: %s", (e.raw or "")[:200])
        return

    # Honour news-monitor's structured pick — including an explicit "nothing worthy".
    status, idx = _parse_selected_lead(monitor_output, len(all_leads))
    if status == "none":
        _notify(
            f"Thelivu daily cycle: scanned {len(all_leads)} lead(s) — none worth investigating "
            f"today. Nothing was investigated, no tokens spent on the spine."
        )
        log.info("news-monitor returned NONE — skipping investigation.")
        return
    if status != "ok":
        # Marker present but index out of range — skip, never force lead #0.
        _notify("Thelivu daily cycle: news-monitor picked an out-of-range lead — skipping this cycle.")
        log.error("Selection out of range. Raw: %s", monitor_output[:200])
        return
    selected, how = _resolve_selected_lead(monitor_output, all_leads, idx)
    if selected is not all_leads[idx]:
        log.warning("SELECTED_LEAD said input lead %d (%s) but SELECTED_THROUGHLINE "
                    "resolved to '%s' — trusting the throughline (%s).",
                    idx + 1, all_leads[idx]["throughline"][:50],
                    selected["throughline"][:50], how)

    log.info("Selected: %s  [%s]", selected["throughline"][:80], how)

    # Absolute-floor newsworthiness gate BEFORE the expensive investigation spine:
    # one cheap call that drops commodity / routine-process news so the engine
    # never spends investigation + verification tokens on a non-story.
    pursue, why = _newsworthiness_verdict(selected)
    if not pursue:
        mark_lead_processed(selected.get("queue_id"))
        _notify_card(
            "🗑", "Dropped today's top lead — not our kind of story",
            body=f"<b>{_esc(selected['throughline'][:160])}</b>\n\n"
                 f"<b>Reason:</b> {_md_to_tg_html(why, limit=300)}\nTrying next-best lead.",
        )
        log.info("Newsworthiness gate DROPPED lead: %s — trying fallback", why)
        # One fallback: try the next lead in the pool that wasn't the dropped one
        fallback = next(
            (l for l in all_leads if l.get("queue_id") != selected.get("queue_id")), None
        )
        if not fallback:
            log.info("No fallback lead available — nothing investigated this cycle.")
            return
        log.info("Fallback lead: %s", fallback["throughline"][:80])
        selected = fallback
        pursue2, why2 = _newsworthiness_verdict(selected)
        if not pursue2:
            mark_lead_processed(selected.get("queue_id"))
            _notify_card(
                "🗑", "Fallback lead also dropped",
                body=f"<b>{_esc(selected['throughline'][:160])}</b>\n\n"
                     f"<b>Reason:</b> {_md_to_tg_html(why2, limit=300)}\nNothing investigated this cycle.",
            )
            log.info("Fallback also dropped: %s", why2)
            return
        log.info("Fallback cleared gate: PURSUE (%s)", why2)
    else:
        log.info("Newsworthiness gate: PURSUE (%s)", why)

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

    # Create the run now so a downstream halt has an id to mark. The lead is now
    # "taken" — mark it processed so it won't be re-selected next cycle (its run
    # carries it from here; a mid-spine failure halts the run, not the queue).
    run_id = save_run(
        video_id=selected["video_id"], source=selected["source"],
        throughline=selected["throughline"], trust_gate="investigating",
        status="investigating",
    )
    mark_lead_processed(selected.get("queue_id"))

    # Investigate from the brief + lead facts — NOT the raw monitor reply (that
    # cascade is the run #18 poisoning vector). The shared spine wraps the rest:
    # a malformed stage halts (needs_attention); a provider outage pauses + re-
    # queues the lead, to resume when credit returns.
    investigate_input = (
        f"LEAD TO INVESTIGATE:\n\n"
        f"Source: {selected['source']}\n"
        f"URL: {selected['video_url']}\n"
        f"Throughline: {selected['throughline']}\n\n"
        f"Extracted claims:\n"
        + json.dumps(selected["claims"], indent=2, ensure_ascii=False)
    )

    def _on_pause(e):
        _route_spine_failure(
            run_id, selected["throughline"][:120], e,
            fail_key=f"leadfail_{selected['video_id']}",
            requeue_fn=lambda: requeue_lead(selected.get("queue_id")),
            drop_fn=lambda: mark_lead_processed(selected.get("queue_id")),
        )

    result = _run_spine(
        rss_brief, investigate_input, run_id, topic_label,
        display_label="Today's story", display_title=selected["throughline"],
        on_pause=_on_pause,
    )
    if result is None:
        return
    draft, review, verification, gate = result

    update_run(run_id,
        trust_gate=gate, draft_text=draft, review_text=review,
        verification_report=verification, status="pending_human",
    )
    log.info("Sending draft for approval (run #%d)...", run_id)
    send_for_approval(run_id, draft, verification, review)
    log.info("=== Cycle complete. Run #%d pending human review. ===", run_id)


# ---------------------------------------------------------------------------
# Source scout (runs weekly, proposes new sources via Telegram)
# ---------------------------------------------------------------------------

def run_story_scout(theme_hint=None):
    """Dig brief via story-scout. Weekly it picks the ripest watchlist theme
    itself; with theme_hint (the owner's /dig command) it targets that theme."""
    log.info("Running story-scout on watchlist%s...",
             f" (targeted: {theme_hint})" if theme_hint else "")
    try:
        watchlist_text = WATCHLIST_YAML.read_text() if WATCHLIST_YAML.exists() else "(no watchlist yet)"
    except Exception:
        watchlist_text = "(watchlist unreadable)"

    if theme_hint:
        prompt = (
            f"Run a TARGETED dig on this specific theme: {theme_hint}\n\n"
            "Use the matching watchlist entry below (kerala_anchor, primary_records, "
            "discipline_note) if one exists. Form a sharp falsifiable question, "
            "identify the primary records to pull, and output a dig brief. Respect "
            "the discipline note exactly — documented facts and contested processes, "
            "never asserted wrongdoing.\n\n"
            f"WATCHLIST:\n{watchlist_text}"
        )
    else:
        prompt = (
            "Run the weekly story scout. Pick the highest-priority theme from the "
            "watchlist below that doesn't already have a story in progress, form a "
            "sharp falsifiable question, identify the primary records to pull, and "
            "output a dig brief.\n\n"
            f"WATCHLIST:\n{watchlist_text}"
        )
    try:
        brief = run_skill("story-scout", prompt)
        log.info("Story scout complete.")

        # Store brief so the "Investigate now" button can queue it
        kv_set("latest_scout_brief", brief[:2000])

        # Extract the theme line for the card headline
        theme_line = ""
        for line in brief.splitlines():
            if line.strip() and not line.startswith("#"):
                theme_line = line.strip()[:160]
                break

        brief_link = _report_link("Story Scout — weekly dig brief", brief)
        keyboard = {
            "inline_keyboard": [[
                {"text": "🔍 Investigate this now", "callback_data": "investigate_scout"},
            ]]
        }
        body = (f"<b>{_esc(theme_line)}</b>\n\n{brief_link}" if theme_line
                else brief_link or _esc(brief[:400]))
        _tg_post(
            TELEGRAM_DRAFT_CHAT_ID,
            f"🕵️ <b>Weekly story scout — new dig brief</b>\n\n{body}"[:_TG_LIMIT],
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as e:
        log.error("Story scout failed: %s", e)


# ---------------------------------------------------------------------------
# Persistent digs — a thread worked over multiple days (docs/command-center.md)
# ---------------------------------------------------------------------------

# next_action_at gap by status: how long before a live dig is auto-advanced again.
_DIG_CADENCE_DAYS = {"scoping": 1, "records-pending": 2, "verifying": 1}


def _dig_history_text(dig, updates):
    """Render a dig + its full log as context for the next story-scout step."""
    lines = [
        f"DIG #{dig['id']}: {dig['title']}",
        f"Question (falsifiable): {dig.get('question') or '(not yet framed)'}",
        f"Kerala anchor: {dig.get('kerala_anchor') or '(none)'}",
        f"Working hypothesis: {dig.get('hypothesis') or '(none)'}",
        f"Status: {dig.get('status')}",
    ]
    if dig.get("owner_note"):
        lines.append(f"Owner's note / angle: {dig['owner_note']}")
    lines.append("\nINVESTIGATION LOG SO FAR (oldest first):")
    if updates:
        for u in updates:
            lines.append(f"\n[{u['created_at']}] ({u['kind']})\n{u['body']}")
    else:
        lines.append("(empty — this is the first step; produce the scoping brief.)")
    return "\n".join(lines)


def run_dig_advance(dig_id):
    """Take one investigative step on a persistent dig.

    Loads the dig and its full log, hands both to story-scout with instructions
    to do the NEXT thing (pull the next primary records, try to disprove, report
    what's newly established / still open), appends the result to the dig log,
    and schedules the next auto-advance. Never publishes — a dig only reaches the
    pipeline via promote_dig(), which still ends at the human gate."""
    dig = get_dig(dig_id)
    if not dig:
        log.warning("Dig advance: no dig #%s", dig_id)
        return
    log.info("Advancing dig #%s: %s", dig_id, dig["title"][:70])
    updates = get_dig_updates(dig_id)
    try:
        watchlist_text = WATCHLIST_YAML.read_text() if WATCHLIST_YAML.exists() else "(no watchlist)"
    except Exception:
        watchlist_text = "(watchlist unreadable)"

    first_step = not updates
    prompt = (
        f"You are continuing a MULTI-DAY dig. {'This is the FIRST step — produce the scoping dig brief.' if first_step else 'Take the NEXT investigative step, building on the log below — do not repeat work already done.'}\n\n"
        "Your job this step:\n"
        "1. Go to the next PRIMARY records the question needs (filings, court/CAG/audit "
        "records, budget/tender/land/environmental docs, official datasets). Use web tools "
        "to actually pull and read what you can now.\n"
        "2. Try to DISPROVE the hypothesis — what's the boring explanation, what would a "
        "fair critic say. A step that only confirms the hunch is not progress.\n"
        "3. Report: what is now DOCUMENTED, what is still OPEN, what to pull next, any RTI "
        "worth filing, and whether this is getting stronger or should be parked/killed.\n"
        "4. End with exactly one line: 'DIG_STATUS: <scoping|records-pending|verifying|ready-to-write|parked|killed>'\n"
        "   Use 'ready-to-write' ONLY when the core is established from records and holds.\n\n"
        "Discipline: documented facts and contested processes, never asserted wrongdoing. "
        "Verify every fact; name the weakest link; downgrade by default.\n\n"
        f"{_dig_history_text(dig, updates)}\n\n"
        f"WATCHLIST (for records/anchor hints):\n{watchlist_text}"
    )
    try:
        result = run_skill("story-scout", prompt, topic=f"dig #{dig_id}: {dig['title'][:50]}")
    except Exception as e:
        log.error("Dig #%s advance failed: %s", dig_id, e)
        return

    # Parse the status line the skill emits.
    new_status = dig["status"]
    m = re.search(r"DIG_STATUS:\s*(scoping|records-pending|verifying|ready-to-write|parked|killed)", result)
    if m:
        new_status = m.group(1)

    kind = "brief" if first_step else "finding"
    add_dig_update(dig_id, result, kind=kind)

    # Schedule the next auto-advance (or stop, if terminal / ready).
    from datetime import timedelta
    patch = {"status": new_status}
    if new_status in _DIG_CADENCE_DAYS:
        nxt = datetime.now(timezone.utc) + timedelta(days=_DIG_CADENCE_DAYS[new_status])
        patch["next_action_at"] = nxt.isoformat()
    else:
        patch["next_action_at"] = None  # ready-to-write / parked / killed → stop auto-advancing
    update_dig(dig_id, **patch)

    # Notify the owner with the step result + one-tap actions.
    report_link = _report_link(f"Dig #{dig_id} — {dig['title'][:60]}", result)
    status_emoji = {"scoping": "🔦", "records-pending": "📂", "verifying": "🔬",
                    "ready-to-write": "✅", "parked": "🅿️", "killed": "❌"}.get(new_status, "🕳️")
    buttons = [[{"text": "⏭️ Advance again", "callback_data": f"digadv_{dig_id}"}]]
    if new_status == "ready-to-write":
        buttons = [[{"text": "📝 Promote to draft", "callback_data": f"digpromote_{dig_id}"}]]
    _tg_post(
        TELEGRAM_DRAFT_CHAT_ID,
        f"{status_emoji} <b>Dig #{dig_id} advanced</b> — now <b>{_esc(new_status)}</b>\n"
        f"<i>{_esc(dig['title'][:100])}</i>\n\n{report_link}"[:_TG_LIMIT],
        reply_markup={"inline_keyboard": buttons},
        parse_mode="HTML",
    )
    log.info("Dig #%s advanced → %s", dig_id, new_status)
    return new_status


def promote_dig(dig_id):
    """Push a dig into the normal pipeline as a topic (source='dig').

    Bundles the dig's accumulated findings so topic-intake → investigate → verify
    → write runs with the record already gathered. The resulting draft still lands
    at the human gate — promotion is not publishing."""
    dig = get_dig(dig_id)
    if not dig:
        return None
    updates = get_dig_updates(dig_id)
    # Prefer the latest substantive findings for the hand-off.
    findings = "\n\n".join(u["body"] for u in updates[-3:]) if updates else ""
    label = (
        f"[DIG] {dig['title']}\n"
        f"Question: {dig.get('question') or ''}\n"
        f"Kerala anchor: {dig.get('kerala_anchor') or ''}\n\n"
        f"Findings gathered so far:\n{findings}"
    )
    queue_topic(label[:2000], source="dig")
    add_dig_update(dig_id, "Promoted to the pipeline as a topic (source='dig'). "
                           "Draft will arrive at the human gate.", kind="promoted")
    update_dig(dig_id, status="ready-to-write", next_action_at=None)
    log.info("Dig #%s promoted to pipeline", dig_id)
    _tg_post(
        TELEGRAM_DRAFT_CHAT_ID,
        f"📝 <b>Dig #{dig_id} promoted to the pipeline.</b>\n"
        f"<i>{_esc(dig['title'][:100])}</i>\n\nThe agent will investigate + write it, "
        "then send the draft here for your approve/kill.",
        parse_mode="HTML",
    )
    return True


# ---------------------------------------------------------------------------
# Chief of staff — proactive follow-up sweep of the backlog (command-center.md)
# ---------------------------------------------------------------------------

def _days_ago(ts):
    """Whole days since an ISO/date value; 0 on any parse failure."""
    if not ts:
        return 0
    try:
        s = str(ts)
        dt = datetime.fromisoformat(s) if "T" in s or " " in s else datetime.fromisoformat(s + "T00:00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0


def _extract_block_array(output, name):
    """Pull the JSON array after a NAME marker, tolerating a missing END_<NAME>
    marker or a truncated tail (the chief-of-staff sometimes runs out of output
    budget mid-array). Salvages complete objects rather than dropping everything."""
    m = re.search(rf"{name}\s*(\[.*?\])\s*END_{name}", output, re.DOTALL)
    raw = m.group(1) if m else None
    if raw is None:
        i = output.find(name)
        if i == -1:
            return []
        start = output.find("[", i)
        if start == -1:
            return []
        depth, end = 0, None
        for j in range(start, len(output)):
            if output[j] == "[":
                depth += 1
            elif output[j] == "]":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        raw = output[start:end] if end else None
        if raw is None:  # truncated array — close it at the last complete object
            last = output.rfind("}", start)
            raw = (output[start:last + 1] + "]") if last != -1 else None
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        last = raw.rfind("}")  # final salvage: keep complete objects only
        if last != -1:
            try:
                return json.loads(raw[:last + 1] + "]")
            except (json.JSONDecodeError, TypeError):
                return []
        return []


def _build_cos_snapshot():
    """Gather the neglected backlog for the chief-of-staff sweep."""
    runs = get_all_runs_summary(limit=80)
    held = [r for r in runs if (r.get("status") in ("held", "hold"))]
    stale_gate = [r for r in runs if r.get("status") == "pending_human" and _days_ago(r.get("date")) >= 2]
    killed = [r for r in runs if r.get("status") in ("killed", "kill")][:10]
    digs = list_digs(include_closed=True)
    dropped_digs = [d for d in digs if d.get("status") in ("parked", "killed")]

    def _run_line(r):
        return (f"- run-{r['id']} [{r.get('status')}] gate={r.get('trust_gate') or '—'} "
                f"age={_days_ago(r.get('date'))}d :: {(r.get('throughline') or 'untitled')[:120]}")

    parts = ["HELD STORIES (paused by the editor):"]
    parts += [_run_line(r) for r in held] or ["  (none)"]
    parts.append("\nAT THE GATE, GOING STALE (>=2 days in pending_human):")
    parts += [_run_line(r) for r in stale_gate] or ["  (none)"]
    parts.append("\nDROPPED / PARKED DIGS:")
    parts += [f"- dig-{d['id']} [{d.get('status')}] :: {(d.get('title') or '')[:120]} — "
              f"{(d.get('question') or '')[:100]}" for d in dropped_digs] or ["  (none)"]
    parts.append("\nRECENTLY KILLED RUNS (revive only if something genuinely changed):")
    parts += [_run_line(r) for r in killed] or ["  (none)"]
    counts = {"held": len(held), "stale_gate": len(stale_gate),
              "dropped_digs": len(dropped_digs), "killed": len(killed)}
    return "\n".join(parts), counts


def run_chief_of_staff():
    """Proactive follow-up sweep: work held/stale/dropped threads, check what moved
    on the open web, recommend recheck/requeue/kill/revive, and open new digs from
    patterns. Recommends and opens threads — never publishes."""
    log.info("Running chief-of-staff backlog sweep...")
    snapshot, counts = _build_cos_snapshot()
    if not any(counts.values()):
        log.info("Chief of staff: backlog empty — nothing to sweep.")
        kv_set("last_cos_at", datetime.now(timezone.utc).isoformat())
        return
    try:
        # Generous budget — the sweep reasons over the whole backlog AND must emit
        # two complete machine blocks at the end; 4096 truncated them mid-array.
        output = run_skill("chief-of-staff", f"BACKLOG SNAPSHOT:\n\n{snapshot}",
                           topic="backlog sweep", max_tokens=8192)
    except Exception as e:
        log.error("Chief of staff skill failed: %s", e)
        return

    # Auto-open the new investigation threads it proposes (a dig never publishes,
    # so opening one is within the follow-up brain's remit).
    opened = 0
    for nd in _extract_block_array(output, "NEW_DIGS"):
        title = (nd.get("title") or "").strip()
        if not title:
            continue
        did = create_dig(
            title=title[:200], question=(nd.get("question") or "").strip(),
            kerala_anchor=(nd.get("kerala_anchor") or "").strip(),
            hypothesis=(nd.get("hypothesis") or "").strip(),
            owner_note="opened by chief-of-staff", priority=2, status="scoping",
        )
        # Make it due soon so the daily auto-advance picks it up.
        update_dig(did, next_action_at=datetime.now(timezone.utc).isoformat())
        add_dig_update(did, "Thread opened by the chief-of-staff sweep from a "
                            "backlog/watchlist pattern. First advance pending.", kind="note")
        opened += 1

    # EXECUTE the recommendations autonomously. The owner granted full authority to
    # work the backlog on its own — the only reserved decision is the publish/review
    # gate, and nothing here publishes: recheck/requeue re-open work, open-dig starts
    # a multi-day investigation, kill clears a dead thread (reversible — draft_text is
    # retained). Capped per sweep so a bad batch can't storm the pipeline.
    _MAX_ACTIONS = 8
    runs_by_id = {r["id"]: r for r in get_all_runs_summary(limit=80)}
    actions_taken = []
    rec_list = _extract_block_array(output, "RECOMMENDATIONS")
    for rec in rec_list[:_MAX_ACTIONS]:
        ref = str(rec.get("ref", "")).strip()
        action = (rec.get("action") or "").strip().lower()
        why = (rec.get("why") or "").strip()
        kind, _, rid = ref.partition("-")
        if not rid.isdigit():
            continue
        rid = int(rid)
        try:
            if kind == "run":
                run = runs_by_id.get(rid, {})
                throughline = (run.get("throughline") or "").strip()
                if action == "recheck":
                    update_run(rid, status="recheck_requested")
                    actions_taken.append(f"🔬 rechecked run #{rid}")
                elif action in ("requeue", "nudge"):
                    update_run(rid, status="pending_human")
                    actions_taken.append(f"📬 requeued run #{rid} to the gate")
                elif action == "kill":
                    update_run(rid, status="killed")
                    actions_taken.append(f"❌ killed run #{rid}")
                elif action == "open-dig":
                    did = create_dig(
                        title=(throughline or f"From run #{rid}")[:200],
                        question=why, owner_note=f"opened by chief-of-staff from run #{rid}",
                        priority=2, status="scoping")
                    update_dig(did, next_action_at=datetime.now(timezone.utc).isoformat())
                    add_dig_update(did, f"Opened by the chief-of-staff from backlog run "
                                        f"#{rid}. Rationale: {why}", kind="note")
                    actions_taken.append(f"🗺️ opened dig #{did} from run #{rid}")
                elif action == "queue-topic":
                    queue_topic(f"[CHIEF] {why or throughline}"[:1000], source="chief-of-staff")
                    actions_taken.append(f"📥 queued a topic from run #{rid}")
            elif kind == "dig":
                if action in ("advance", "recheck", "requeue"):
                    # Make it due now; the auto-advancer takes the next step next tick.
                    update_dig(rid, next_action_at=datetime.now(timezone.utc).isoformat(),
                               status="verifying")
                    actions_taken.append(f"⏭️ queued dig #{rid} to advance")
                elif action == "kill":
                    update_dig(rid, status="killed", next_action_at=None)
                    actions_taken.append(f"❌ killed dig #{rid}")
        except Exception as e:
            log.warning("chief-of-staff could not execute %s on %s: %s", action, ref, e)

    kv_set("latest_cos_brief", output[:6000])
    kv_set("latest_cos_actions", json.dumps(actions_taken))
    kv_set("last_cos_at", datetime.now(timezone.utc).isoformat())

    link = _report_link("Chief of staff — backlog sweep", output)
    acted_lines = "\n".join(f"• {a}" for a in actions_taken) if actions_taken else "• (no backlog actions this sweep)"
    _notify_card(
        "🧑‍💼", f"Chief of staff acted — {len(actions_taken)} action(s), {opened} new dig(s)",
        body=(f"Reviewed held ({counts['held']}), stale-at-gate ({counts['stale_gate']}), "
              f"dropped digs ({counts['dropped_digs']}).\n\n"
              f"<b>Acted autonomously:</b>\n{acted_lines}\n\n"
              f"{opened} new thread(s) opened as digs. Everything still stops at your "
              f"review gate.\n\n{link}"),
    )
    log.info("Chief of staff complete: executed %d action(s), %d new digs.",
             len(actions_taken), opened)


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
        _notify_card("📡", "Source scout: no new proposals this week", body=_md_to_tg_html(output, limit=600))
        return

    try:
        proposals = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        log.error("Source scout: failed to parse proposals JSON: %s", e)
        _notify_card("⚠️", "Source scout output was malformed", body=_md_to_tg_html(output, limit=600))
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
        tier_icon = {1: "🟢", 2: "🟡", 3: "🟠"}.get(p.get("tier", 3), "⚪")
        notes_text = _esc(p.get("notes", "")[:300])
        text = (
            f"📡 <b>New source proposal #{proposal_id}</b>\n\n"
            f"<b>{_esc(p.get('name', 'Unknown'))}</b>\n"
            f"{tier_icon} Tier {p.get('tier', '?')} · {_esc(p.get('platform', ''))} · {_esc(p.get('role', ''))}\n"
            f"Handle: <code>{_esc(p.get('handle', '') or '—')}</code>\n"
            f"Lean: {_esc(p.get('lean', '') or '—')}\n\n"
            + (f"{notes_text}" if notes_text else "")
        )
        keyboard = {
            "inline_keyboard": [[
                {"text": "✓ Add to sources",  "callback_data": f"addsrc_{proposal_id}"},
                {"text": "✗ Skip",            "callback_data": f"skipsrc_{proposal_id}"},
            ]]
        }
        msg_id = _tg_post(TELEGRAM_DRAFT_CHAT_ID, text[:_TG_LIMIT], reply_markup=keyboard,
                          parse_mode="HTML")
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

        # Parse the mandatory FOLLOW_UPS JSON block — structured and unambiguous.
        follow_ups = 0
        m = re.search(r"FOLLOW_UPS\s*(\[.*?\])\s*END_FOLLOW_UPS", output, re.DOTALL)
        if m:
            try:
                fu_list = json.loads(m.group(1))
                for fu in fu_list:
                    brief = fu.get("brief", "").strip()
                    throughline = fu.get("throughline", "").strip()
                    if brief:
                        label = f"[FOLLOW-UP] {throughline}: {brief}" if throughline else f"[FOLLOW-UP] {brief}"
                        from shared.db import queue_topic
                        queue_topic(label[:1000], source="story-tracker")
                        follow_ups += 1
            except (json.JSONDecodeError, TypeError) as e:
                log.warning("story-tracker FOLLOW_UPS JSON parse failed: %s", e)
        else:
            log.info("story-tracker: no FOLLOW_UPS block in output (no new developments)")

        tracker_link = _report_link(f"Story tracker — {len(stories)} stories checked", output)
        if follow_ups:
            _notify_card(
                "🔄", f"Story tracker: {follow_ups} follow-up(s) queued",
                body=(f"Checked {len(stories)} published stories — {follow_ups} developed enough "
                      f"to re-investigate. They're now in the topic queue.\n\n{tracker_link}"),
            )
        else:
            _notify_card(
                "📋", f"Story tracker: {len(stories)} stories checked",
                body=f"No significant new developments this week.\n\n{tracker_link}",
            )

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

        _notify_card(
            "🧭", "Monthly meta-synthesis complete",
            body=f"{len(all_runs)} stories reviewed.",
            report_title="Meta-synthesis report", report_md=output,
        )
        kv_set("last_meta_at", datetime.now(timezone.utc).isoformat())
    except Exception as e:
        log.error("Meta-synthesis failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Daily cost report (sent at 8pm IST / 14:30 UTC)
# ---------------------------------------------------------------------------

# Rates live in shared/costs.py — one table for the report, the dashboard and
# the command center. (This copy had gemini-pro output at $5 instead of $10 and
# billed free NVIDIA Gemma calls at Claude rates.)
from shared.costs import cost_usd as _calc_cost, USD_TO_INR as _USD_TO_INR


def send_cost_report():
    from datetime import date
    data = get_cost_report_data()
    rows = data["by_model"]
    runs_today = data["runs_today"]
    today = date.today().isoformat()

    # Sum costs per-model so Flash vs Pro are priced correctly
    today_usd = month_usd = total_usd = 0.0
    claude_in = claude_out = 0
    gemini_in = gemini_out = 0
    model_lines = []
    for row in rows:
        model = row["model"] or "unknown"
        ti = row["today_in"] or 0;  to = row["today_out"] or 0
        mi = row["month_in"] or 0;  mo = row["month_out"] or 0
        ai = row["total_in"] or 0;  ao = row["total_out"] or 0
        today_usd += _calc_cost(model, ti, to)
        month_usd += _calc_cost(model, mi, mo)
        total_usd += _calc_cost(model, ai, ao)
        if "gemini" in model.lower():
            gemini_in += ti; gemini_out += to
        else:
            claude_in += ti; claude_out += to
        day_cost = _calc_cost(model, ti, to)
        if day_cost > 0 or ti > 0:
            model_lines.append(f"  {model}: {ti:,}→{to:,} tok = ${day_cost:.4f}")

    inr = lambda usd: usd * _USD_TO_INR
    total_in_today = claude_in + gemini_in + claude_out + gemini_out

    notes = "All normal."
    if runs_today and total_in_today and total_in_today / runs_today > 50_000:
        notes = "⚠️ High token use per run today — check for a runaway investigation."
    elif today_usd == 0:
        notes = "No runs today — zero spend."

    # 7-day spend trend — aggregate per day across all models
    try:
        daily_rows = get_daily_costs(days=7)
        by_day = {}
        for r in daily_rows:
            d = str(r["day"])
            by_day[d] = by_day.get(d, 0.0) + _calc_cost(
                r["model"] or "unknown", r["in_tok"] or 0, r["out_tok"] or 0)
        if by_day:
            trend_lines = [f"  {d}: ₹{v*_USD_TO_INR:.0f}" for d, v in sorted(by_day.items())]
            trend_section = "7-day spend:\n" + "\n".join(trend_lines)
        else:
            trend_section = ""
    except Exception as e:
        log.warning("7-day trend failed: %s", e)
        trend_section = ""

    breakdown = "\n".join(model_lines) if model_lines else "  (no usage today)"
    parts = [
        f"Thelivu Cost Report — {today}",
        "",
        f"Today:      ₹{inr(today_usd):.2f} (~${today_usd:.4f})",
        f"This month: ₹{inr(month_usd):.2f} (~${month_usd:.4f})",
        f"All time:   ₹{inr(total_usd):.2f} (~${total_usd:.4f})",
        "",
        f"Today by model:\n{breakdown}",
        "",
        f"Pipeline runs today: {runs_today}",
        f"Notes: {notes}",
    ]
    if trend_section:
        parts += ["", trend_section]
    _notify("\n".join(parts))
    log.info("Cost report sent.")


# ---------------------------------------------------------------------------
# Re-check held stories — owner-triggered (/recheck), fresh re-investigation
# ---------------------------------------------------------------------------

def recheck_run(run_id, note=""):
    """Re-develop one held story from scratch: re-investigate against today's live
    sources, re-verify, and — if it now clears the gate — re-write and bring back a
    FULLER draft for approval. This is how a story 'ripens': held while thin, it
    comes back once the record has actually moved. Triggered only by the owner.

    `note` carries optional OWNER EDITORIAL DIRECTION (e.g. "downgrade claim X to an
    attributed allegation + add the denial; lean on the verified spine"). It flows
    into the brief so every downstream stage — investigate, verify, write — respects
    it. It steers framing/emphasis; it never licenses publishing an unverified claim
    as fact (the trust gate still governs)."""
    from shared.db import get_run
    run = get_run(run_id)
    if not run:
        log.warning("recheck_run: #%s not found", run_id)
        return
    throughline = run.get("throughline") or ""
    note = (note or "").strip()
    log.info("Re-checking held run #%s%s: %s", run_id,
             " (with owner direction)" if note else "", throughline[:60])

    # If the owner's direction includes a link (article or video), fetch its content
    # so the recheck works from the actual source, not just the URL string — same
    # enrichment the Ingest tab uses. The short instruction still drives framing; the
    # fetched text is handed to the investigator as source material.
    note_enriched = note
    if note and ("http://" in note or "https://" in note):
        note_enriched = _enrich_topic_with_link(note)

    direction_line = (f"\nOwner editorial direction (follow this): {note[:600]}" if note else "")
    brief = (
        "STORY_BRIEF\n"
        "Geography: Follow the story — match scope to evidence and impact\n"
        f"Angle: {throughline[:200]}\n"
        "Source: previously-held story, re-checked for development\n"
        "Scope: Re-investigate as reported; expand or narrow on what the evidence now shows"
        f"{direction_line}\n"
        "END_STORY_BRIEF"
    )
    investigate_input = (
        "PREVIOUSLY-HELD STORY — re-investigate from scratch against TODAY'S live "
        "sources and surface anything that has developed since it was held (new "
        "filings, hearings, data, corroborating reports, official responses).\n\n"
        f"Throughline: {throughline}\n\n"
        + (f"OWNER EDITORIAL DIRECTION — apply this to framing, emphasis and how "
           f"contested claims are handled (attribute + include denials rather than "
           f"asserting; downgrade allegations to what the record supports). If it "
           f"includes a source/article below, treat it as a lead to verify "
           f"independently, not as proof. It does NOT override the trust gate:\n"
           f"{note_enriched}\n\n" if note else "")
        + f"Earlier verification notes (for context only — re-verify fresh):\n"
        f"{(run.get('verification_report') or 'N/A')[:1500]}"
    )

    def _on_pause(e):
        # Provider down — leave it held so it can be re-checked again later.
        update_run(run_id, status="held")
        _pause_run(run_id, throughline[:120], e)

    update_run(run_id, status="investigating")
    result = _run_spine(
        brief, investigate_input, run_id, throughline[:120],
        display_label="Re-checked story", display_title=throughline,
        on_pause=_on_pause,
    )
    if result is None:
        return  # killed / held-again / halted / paused — already handled + notified
    draft, review, verification, gate = result
    update_run(run_id, trust_gate=gate, draft_text=draft, review_text=review,
               verification_report=verification, status="pending_human")
    _notify_card("🔄", f"Re-checked story now ready — run #{run_id}",
                 body=f"<b>{_esc(throughline[:160])}</b>\n\nIt developed enough to publish — "
                      "the fuller draft is below for your decision.")
    send_for_approval(run_id, draft, verification, review)


def process_recheck_requests():
    """Pick up runs the owner flagged for recheck (status 'recheck_requested') and
    re-develop them, honouring any owner editorial direction stashed in kv
    ('recheck_note_<id>'). Cheap when there's nothing pending (one status query)."""
    from shared.db import get_runs_by_status
    pending = get_runs_by_status("recheck_requested", limit=5)
    for run in pending:
        note_key = f"recheck_note_{run['id']}"
        note = kv_get(note_key) or ""
        try:
            recheck_run(run["id"], note=note)
        except Exception as e:
            log.error("recheck_run #%s failed: %s", run["id"], e, exc_info=True)
            update_run(run["id"], status="held")  # leave it holdable
        finally:
            if note:
                kv_set(note_key, "")  # consume the direction once used


# Evergreen hashtags on every post — brand/category only, deliberately NOT
# geography. Thelivu covers all sorts of stories; Kerala/India are pursued hard in
# sourcing but never stamped on every post. Geography tags are story-specific (the
# composer adds #Kerala when a piece is Kerala, its own place tags otherwise).
# Keep this lean and relevant; Instagram penalises spammy tag walls.
_BASE_HASHTAGS = ["Thelivu", "FactCheck", "Journalism", "News"]
_MAX_HASHTAGS = 15


def _build_hashtags(story_tags):
    """Combine evergreen brand/geo tags with the story-specific ones the composer
    produced. Normalises (#, no spaces/punctuation), de-dupes case-insensitively,
    caps the count, and returns a single caption-ready line."""
    seen, out = set(), []
    for raw in _BASE_HASHTAGS + list(story_tags or []):
        tag = re.sub(r"[^0-9A-Za-z]", "", str(raw).lstrip("#"))
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append("#" + tag)
        if len(out) >= _MAX_HASHTAGS:
            break
    return " ".join(out)


def _parse_carousel_fields(text):
    """Pull DARK/STAMP/HASHTAGS/SLIDE 1..N out of carousel-composer's output."""
    def field(name, default=""):
        m = re.search(rf"^{name}:\s*(.+)$", text or "", re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else default

    dark = field("DARK", "false").strip().lower() == "true"
    stamp = field("STAMP", "VERIFIED")
    # HASHTAGS: a space/comma-separated list on one line; tolerate leading '#'.
    hashtags = [t for t in re.split(r"[,\s]+", field("HASHTAGS", "")) if t]
    slides = []
    for m in re.finditer(r"^SLIDE\s+(\d+):\s*(.+)$", text or "", re.IGNORECASE | re.MULTILINE):
        slides.append((int(m.group(1)), m.group(2).strip()))
    slides.sort(key=lambda s: s[0])
    return dark, stamp, [text for _, text in slides], hashtags


def process_queued_carousels():
    """Pick up carousels queued by an article approval (carousel_runs status
    'queued'), compose the slide breakdown via Claude (carousel-composer),
    render each slide, send the set to the owner's draft chat as one Telegram
    album plus an Approve/Kill message. Cheap no-op when nothing's queued.
    Mirrors process_recheck_requests."""
    from shared.config import REPO_ROOT, SLIDE_SERVER_BASE_URL
    from shared.db import (
        get_queued_carousel_runs, update_carousel_run, add_carousel_slide,
        clear_carousel_slides, get_run,
    )
    from publishing.slides import render_dossier_slide

    for carousel in get_queued_carousel_runs():
        carousel_id = carousel["id"]
        run = get_run(carousel["run_id"])
        if run is None or not run.get("draft_text"):
            log.error("Carousel #%s: parent run #%s missing draft_text", carousel_id, carousel["run_id"])
            update_carousel_run(carousel_id, status="failed")
            continue

        update_carousel_run(carousel_id, status="composing")
        try:
            composed = run_structured_skill(
                "carousel-composer", run["draft_text"], marker=_M_CAROUSEL, run_id=carousel["run_id"])
            dark, stamp, slide_texts, story_tags = _parse_carousel_fields(composed)
            if not slide_texts:
                raise ValueError("carousel-composer returned no SLIDE lines")

            out_dir = REPO_ROOT / "articles" / "slides"
            out_dir.mkdir(parents=True, exist_ok=True)
            clear_carousel_slides(carousel_id)  # idempotent re-compose (no dup positions)
            n = len(slide_texts)
            image_urls = []
            for i, headline in enumerate(slide_texts, start=1):
                slide_stamp = stamp if i == 1 else f"{i}/{n}"
                # JPEG, not PNG — Instagram's publish step (media_publish) throws a
                # persistent internal error 2207085 on PNG carousels; JPEG is the
                # format IG officially wants and re-encodes to anyway.
                out_path = str(out_dir / f"carousel_{carousel_id}_{i}.jpg")
                render_dossier_slide(headline, stamp=slide_stamp, dark=dark, out=out_path)
                image_url = (
                    f"{SLIDE_SERVER_BASE_URL.rstrip('/')}/carousel_{carousel_id}_{i}.jpg"
                    if SLIDE_SERVER_BASE_URL else ""
                )
                add_carousel_slide(carousel_id, i, headline, image_path=out_path, image_url=image_url)
                image_urls.append((out_path, image_url))

            article_url = carousel.get("article_url") or ""
            caption_bits = [run.get("throughline") or ""]
            if article_url:
                caption_bits.append(f"Full story & sources: {article_url}")
            hashtags = _build_hashtags(story_tags)
            if hashtags:
                caption_bits.append(hashtags)
            caption = "\n\n".join(b for b in caption_bits if b)[:2200]
            # Persist the style so slides can be re-rendered from the DB on demand
            # (the fileserver regenerates a missing PNG — survives redeploys/cleanup).
            update_carousel_run(carousel_id, caption=caption, status="pending_review",
                                dark=dark, stamp=stamp)

            keyboard = {"inline_keyboard": [[
                {"text": "✓ Post carousel to Instagram", "callback_data": f"carouselapprove_{carousel_id}"},
                {"text": "✗ Kill",                        "callback_data": f"carouselkill_{carousel_id}"},
            ]]}
            album_caption = f"🖼 {n}-slide carousel for run #{carousel['run_id']} — approve to post to Instagram."
            msg_id = _tg_post_media_group(
                TELEGRAM_DRAFT_CHAT_ID, [p for p, _ in image_urls], album_caption, keyboard)
            update_carousel_run(carousel_id, tg_msg_id=msg_id)
            log.info("Carousel #%s ready for review (run #%s, %d slides)", carousel_id, carousel["run_id"], n)
        except Exception as e:
            log.error("Carousel composition failed for #%s: %s", carousel_id, e, exc_info=True)
            update_carousel_run(carousel_id, status="failed")
            _notify(f"⚠️ Carousel generation failed for run #{carousel['run_id']} (carousel #{carousel_id}): {e}")


def cleanup_finished_carousels():
    """Delete rendered slide PNGs for carousels that reached a terminal state
    (posted/killed/approved_manual/failed) — Instagram already has its own copy
    once posted, and the file server has no reason to keep serving them. Runs
    every cycle; a no-op when nothing's finished yet. This is the automatic
    counterpart to the one-off manual cleanup done after the first carousel
    test — the pattern going forward instead of a repeated ask."""
    from shared.db import get_unclean_finished_carousels, get_carousel_slides, mark_carousel_cleaned

    for carousel in get_unclean_finished_carousels():
        carousel_id = carousel["id"]
        removed = 0
        for slide in get_carousel_slides(carousel_id):
            path = slide.get("image_path")
            if path and Path(path).is_file():
                try:
                    Path(path).unlink()
                    removed += 1
                except OSError as e:
                    log.warning("Could not delete slide file %s for carousel #%s: %s", path, carousel_id, e)
        mark_carousel_cleaned(carousel_id)
        if removed:
            log.info("Cleaned up %d slide file(s) for carousel #%s (status=%s)", removed, carousel_id, carousel["status"])


def _cost_report_due(now_utc):
    """Return True if it's time to send the daily cost report.
    Time is read from kv_store key 'cost_report_utc' (format HH:MM, default 14:30)."""
    raw = kv_get("cost_report_utc") or "14:30"
    try:
        h, m = (int(x) for x in raw.split(":"))
    except Exception:
        h, m = 14, 30
    return now_utc.hour == h and now_utc.minute >= m
