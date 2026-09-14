"""Reading a page that is not a page.

Anil, 2026-09-14: *"How can we read js rendered ones? Can you write something
custom to solve this?"*

sansad.in is the case that forced this. `fetch_index` finds nine links on the
Lok Sabha questions page and none of them is a document, so the target has
produced zero candidates in its entire history — not because the questions are
missing, but because they are not IN the HTML. The page is a Next.js shell and
the questions arrive afterwards over XHR.

**The obvious answer is a headless browser and it is the wrong one here.**
Chromium wants roughly 300MB of RSS; the digger runs under a 256MB cap on a
945MB box that also hosts freellmapi and sshd, and that box has already been
taken down once by a memory spike. Rendering JavaScript to read a list of
government documents is also an enormous amount of machinery to recover data the
site is already serving as JSON.

**So: use a browser ONCE, to find the API. Then never again.**

That is exactly how sansad's endpoint was found — load the page with devtools
recording, read the XHR list, and there it is among eighty requests:

    /api_ls/question/qetFilteredQuestionsAns?loksabhaNo=18&sessionNumber=8&...

(their spelling, not ours — `qet`, not `get`). It answers plain urllib with no
key, no cookie and no referer check, and it returns 4,500 questions for a single
session, each with its subject, its ministry, the member who asked it, the full
question and answer text, AND the PDF path. An index page would have given us
ten links.

The discovery is manual and that is fine: it is a few minutes per source, once,
and what it produces is a permanent, structured, robots-respecting reader. What
is NOT fine is guessing an endpoint into existence — every reader here is one
that was observed working.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from engine.digger import robots

log = logging.getLogger("digger")

TIMEOUT = 45
USER_AGENT = (
    "Mozilla/5.0 (compatible; ThelivuDigger/1.0; +https://thelivu.com) "
    "python-urllib"
)


class ApiError(RuntimeError):
    pass


def get_json(url, timeout=TIMEOUT):
    """Fetch and decode one JSON endpoint. Robots is checked, same as any fetch.

    An API is not a loophole around robots.txt. It is a different door into the
    same building, and a site that has asked not to be crawled has asked about
    both.
    """
    try:
        robots.check(url)
    except robots.RobotsDenied as e:
        raise ApiError(str(e)) from e
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(f"{url[:80]}: {e}") from e
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        raise ApiError(f"{url[:80]}: not JSON ({e})") from e


# --------------------------------------------------------------------------
# sansad.in — Lok Sabha questions and answers
# --------------------------------------------------------------------------

SANSAD_QUESTIONS = "https://sansad.in/api_ls/question/qetFilteredQuestionsAns"
SANSAD_SESSIONS = "https://sansad.in/api_ls/business/getAllLoksabhaAndSession"


def sansad_sessions():
    """[(loksabha_no, session_no)], newest first. [] if the shape moved.

    Asked rather than hardcoded, because a hardcoded session number silently
    stops finding new questions the day a session ends — the request keeps
    succeeding and returns an archive.
    """
    try:
        body = get_json(SANSAD_SESSIONS + "?locale=en")
    except ApiError as e:
        log.info("sansad session list unavailable: %s", e)
        return []
    # NESTED, not flat: the endpoint returns one row per Lok Sabha, each holding
    # its own list of sessions. A first version read it as a flat list of
    # {loksabhaNo, sessionNo} and quietly returned nothing at all — which would
    # have pinned the reader to whatever session was hardcoded that week.
    rows = body if isinstance(body, list) else (body.get("data") or [])
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        lok = r.get("loksabha") or r.get("loksabhaNo") or r.get("lokNo")
        if not lok:
            continue
        for ses in r.get("sessions") or []:
            n = (ses or {}).get("sessionNo") if isinstance(ses, dict) else ses
            if n:
                out.append((int(lok), int(n)))
    return sorted(set(out), reverse=True)


def sansad_questions(loksabha_no, session_no, page_size=40, page=1):
    """One page of questions. [{subject, ministry, member, date, url, text}].

    `url` is the PDF of the question and its answer. Note the path shape:
    /getFile/lsapps/loksabhaquestions/... — the API hands back the CURRENT one,
    which is the shape routing.PATH_REWRITES exists to repair when a URL is
    found anywhere else. Reading the API means never needing that repair.
    """
    q = urllib.parse.urlencode({"loksabhaNo": loksabha_no,
                                "sessionNumber": session_no,
                                "pageNo": page, "pageSize": page_size,
                                "locale": "en"})
    body = get_json(f"{SANSAD_QUESTIONS}?{q}")
    if isinstance(body, list):
        body = body[0] if body else {}
    rows = (body or {}).get("listOfQuestions") or []

    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        url = (r.get("questionsFilePath") or "").strip()
        if not url:
            continue
        members = r.get("member") or []
        out.append({
            "url": url.split("?")[0],
            "subject": (r.get("subjects") or "").strip(),
            "ministry": (r.get("ministry") or "").strip(),
            "member": ", ".join(members) if isinstance(members, list) else str(members),
            "date": (r.get("date") or "").strip(),
            "type": (r.get("type") or "").strip(),
            # The API carries the text itself, so a question can be READ without
            # fetching the PDF at all. The PDF still matters — it is what goes on
            # screen as evidence — but the lead can be judged before spending a
            # download on it.
            "question": (r.get("questionText") or "").strip(),
            "answer": (r.get("answerText") or "").strip(),
        })
    return out
