"""The single publish path — used by BOTH the Telegram bot and the dashboard.

There used to be two: the bot's full flow (self-hosted article page + slug + bio
link + linked carousel) and the dashboard's simpler plain-text post. They drifted,
and a dashboard approve produced a linkless post with no article page. This is the
one implementation both call, so they can never drift again (see docs/HANDOFF.md
§5.3 — "every past title bug came from a second, slightly-different implementation").

`publish_run(run_id)` does exactly what the bot's approve did:
  prepare → self-hosted /a/<slug> page + HTML teaser to the channel + bio link +
  mark published + queue the Instagram carousel with the article URL.
If the article-page path fails, it falls back to a chunked plain-text post so an
approval never hard-fails. It does NOT run an LLM over the approved draft.

It never decides *whether* to publish — the human gate (the approve tap/click) is
the caller's job. This just executes an approved publish.
"""

import time
import logging

import requests

from shared.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, CONTACT_HANDLE, SLIDE_SERVER_BASE_URL,
)
from shared.db import (
    get_run, set_run_slug, add_bio_link, save_publication, update_run,
    queue_carousel_run,
)

log = logging.getLogger("publish")

_TG_LIMIT = 4096
_TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _chunks(text):
    out, cur = [], ""
    for para in text.split("\n\n"):
        cand = (cur + "\n\n" + para).strip() if cur else para
        if len(cand) <= _TG_LIMIT:
            cur = cand
        else:
            if cur:
                out.append(cur)
            while len(para) > _TG_LIMIT:
                out.append(para[:_TG_LIMIT]); para = para[_TG_LIMIT:]
            cur = para
    if cur:
        out.append(cur)
    return out


def _post_html(html_text):
    r = requests.post(
        f"{_TG_API}/sendMessage",
        json={"chat_id": TELEGRAM_CHANNEL_ID, "text": html_text,
              "parse_mode": "HTML", "disable_web_page_preview": False},
        timeout=30,
    )
    r.raise_for_status()
    return [r.json()["result"]["message_id"]]


def _post_plain(prepared_text):
    ids = []
    for chunk in _chunks(prepared_text):
        r = requests.post(
            f"{_TG_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHANNEL_ID, "text": chunk},
            timeout=30,
        )
        r.raise_for_status()
        ids.append(r.json()["result"]["message_id"])
        time.sleep(0.5)
    return ids


def publish_run(run_id):
    """Publish an already-approved run. Returns a result dict:
       {ok, how, msg_ids, article_url, slug, error}. Never raises for the normal
       failure modes — a publish is best-effort with a plain-text fallback."""
    from publishing.parser import prepare_for_publish, parse_article
    from publishing.articlepage import make_slug
    from publishing.telegram import build_teaser

    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": f"run #{run_id} not found"}
    draft = run.get("draft_text") or ""
    if not draft:
        return {"ok": False, "error": f"run #{run_id} has no draft text"}

    prepared = prepare_for_publish(draft, CONTACT_HANDLE)
    how, article_url, slug = "teaser", "", None

    try:
        if not SLIDE_SERVER_BASE_URL:
            raise RuntimeError("SLIDE_SERVER_BASE_URL not set — no domain to host the article")
        article = parse_article(prepared)
        slug = make_slug(run_id, article.title)
        set_run_slug(run_id, slug)
        article_url = f"{SLIDE_SERVER_BASE_URL}/a/{slug}"
        msg_ids = _post_html(build_teaser(article, article_url, CONTACT_HANDLE))
        log.info("Published run #%d at %s", run_id, article_url)
        try:
            add_bio_link(article.title, f"/a/{slug}")  # deduped; relative URL
        except Exception as e:
            log.warning("Bio page update failed for run #%d: %s", run_id, e)
    except Exception as e:
        log.warning("Article-page path failed for run #%d (%s) — plain-text fallback", run_id, e)
        how = "plain-text"
        try:
            msg_ids = _post_plain(prepared)
        except Exception as e2:
            log.error("Publish failed for run #%d: %s", run_id, e2)
            return {"ok": False, "error": str(e2)}

    save_publication(run_id, msg_ids, "Confirmed")
    update_run(run_id, status="published")

    # Queue the Instagram carousel; the orchestrator composes/renders it next tick.
    try:
        queue_carousel_run(run_id, article_url=article_url)
    except Exception as e:
        log.error("Failed to queue carousel for run #%d: %s", run_id, e)

    return {"ok": True, "how": how, "msg_ids": msg_ids,
            "article_url": article_url, "slug": slug, "error": None}
