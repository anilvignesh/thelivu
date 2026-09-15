"""One way to reach Anil on Telegram.

There were five, and they had drifted apart in ways that matter:

    run.py                      truncates at 4096, timeout 10, plain
    publishing/reel_worker.py   truncates at 4096, timeout 30, parse_mode HTML
    dashboard.py                CHUNKS, timeout 15, plain            (x2 funcs)
    command_center/api/runs.py  truncates, timeout 15, plain

So a long message was silently cut in four places and delivered whole in
one, and a message containing a '<' rendered differently depending on which
function happened to send it. None of that was decided; it accumulated.

Chunking is kept as the correct behaviour. A health digest or a review card
that runs past 4096 characters is exactly the message you do not want to
lose the end of — and the end is where the action usually is.

Never raises. A notification that fails must not take down the thing it was
reporting on; that is how a failure gets hidden by its own alert.
"""

import logging
import os

log = logging.getLogger("notify")

LIMIT = 4000          # under Telegram's 4096 so a chunk marker still fits
TIMEOUT = 20


def _config():
    return (os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            os.environ.get("TELEGRAM_DRAFT_CHAT_ID", ""))


def chunks(text, limit=LIMIT):
    """Split on line boundaries where possible, so a message never tears
    mid-sentence. A single line longer than the limit is cut, because at that
    point there is nothing better to do."""
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                out.append(cur); cur = ""
            out.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) > limit:
            out.append(cur); cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def send(text, html=False, chat_id=None, timeout=TIMEOUT):
    """Send to the draft chat, in as many parts as it takes. True if all landed.

    `html` only where a caller deliberately formats — the default is plain,
    because an unescaped '<' in a document quote is far more likely than
    intentional markup.
    """
    token, chat = _config()
    chat = chat_id or chat
    if not token or not chat:
        log.debug("telegram not configured — message dropped")
        return False

    import requests

    ok = True
    for part in chunks(text):
        body = {"chat_id": str(chat), "text": part}
        if html:
            body["parse_mode"] = "HTML"
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=body, timeout=timeout)
            if r.status_code != 200:
                log.warning("telegram send failed: %s %s",
                            r.status_code, r.text[:160])
                ok = False
        except Exception as e:                              # noqa: BLE001
            log.warning("telegram send failed: %s", e)
            ok = False
    return ok
