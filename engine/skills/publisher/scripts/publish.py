#!/usr/bin/env python3
"""
publisher — reference implementation.

Posts a HUMAN-APPROVED article to the Thelivu Telegram channel.

The human gate is enforced here in code: this script asks for an interactive
confirmation that you cannot flag away. That is deliberate. If you wire this
into an unattended routine and strip the prompt, you have removed the one thing
the entire engine was built to protect. Don't.

This is a STARTING POINT. It posts plain-text chunks (simple and reliable). For
nicely-rendered long-form, publish to Telegraph (telegra.ph) and post the link
instead — see the note at the bottom.

Dependencies:
  pip install requests
Environment:
  export TELEGRAM_BOT_TOKEN=...     # from BotFather, kept apart from model keys
  export TELEGRAM_CHANNEL=@thelivu  # bot must be an admin with post permission
Usage:
  python publish.py --draft path/to/approved.md --confidence Confirmed
"""

import os
import sys
import json
import time
import argparse
import datetime as dt
import requests

TG_LIMIT = 4096
LOG_PATH = "published_log.jsonl"

FOOTER = ("\n\n—\nSources above. Drafted with AI assistance, reviewed by a human "
          "editor before publishing. Spotted an error? We correct openly — "
          "[contact].")


def load_draft(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def attach_furniture(text: str, confidence: str) -> str:
    """Append confidence label and the standing footer if absent. Substance is
    never touched — this only adds the required furniture."""
    label = f"\n\nConfidence — facts: {confidence}. Framing is the writer's view."
    if "Confidence —" not in text:
        text += label
    if "Drafted with AI assistance" not in text:
        text += FOOTER
    return text


def split_for_telegram(text: str) -> list[str]:
    """Split on paragraph boundaries so no chunk exceeds Telegram's limit."""
    chunks, current = [], ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= TG_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # a single oversized paragraph: hard-wrap it
            while len(para) > TG_LIMIT:
                chunks.append(para[:TG_LIMIT])
                para = para[TG_LIMIT:]
            current = para
    if current:
        chunks.append(current)
    return chunks


def confirm_human_gate(title: str, n_chunks: int) -> bool:
    """The human gate. No bypass flag — on purpose."""
    print("\n" + "=" * 60)
    print(f"  ABOUT TO PUBLISH: {title}")
    print(f"  {n_chunks} message(s) to {os.environ.get('TELEGRAM_CHANNEL', '?')}")
    print("=" * 60)
    print("This goes live to subscribers. Have YOU reviewed and approved it?")
    answer = input('Type the word PUBLISH to confirm, anything else to abort: ')
    return answer.strip() == "PUBLISH"


def post_chunk(token: str, channel: str, text: str) -> int:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": channel, "text": text, "disable_web_page_preview": False},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")
    return data["result"]["message_id"]


def log_publication(title: str, msg_ids: list[int], confidence: str):
    record = {
        "title": title,
        "channel": os.environ.get("TELEGRAM_CHANNEL"),
        "message_ids": msg_ids,
        "confidence": confidence,
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Logged to {LOG_PATH}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True, help="path to the APPROVED draft")
    ap.add_argument("--confidence", required=True,
                    choices=["Confirmed", "Developing", "Contested"])
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel = os.environ.get("TELEGRAM_CHANNEL")
    if not token or not channel:
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL first.")

    text = attach_furniture(load_draft(args.draft), args.confidence)
    title = text.lstrip("# ").splitlines()[0][:80]
    chunks = split_for_telegram(text)

    if not confirm_human_gate(title, len(chunks)):
        sys.exit("Aborted. Nothing was published.")

    msg_ids = []
    for chunk in chunks:
        msg_ids.append(post_chunk(token, channel, chunk))
        time.sleep(1)  # be gentle with rate limits
    print(f"Published {len(msg_ids)} message(s).")
    log_publication(title, msg_ids, args.confidence)


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# Upgrade note: for clean long-form rendering, publish the article to Telegraph
# (telegra.ph) via its createPage API and post the returned URL to the channel.
# Telegram renders Telegraph links as Instant View, so subscribers get a proper
# article page instead of split messages. Worth doing once the basics work.
# ---------------------------------------------------------------------------
