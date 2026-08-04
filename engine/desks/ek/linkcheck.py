"""Mechanical check that every URL a belief piece cites actually resolves.

Why this is code and not a prompt instruction: the first Everyone Knows piece
(run #136, banana republic) cited six sources, and THREE returned 404 — including
the university article carrying the piece's load-bearing mechanism. The
search-grounded record-builder had produced plausible, correctly-shaped URLs for
real-sounding articles that are not at those addresses. No amount of "only cite
URLs you retrieved" fixes that reliably; asking the network does.

This matters more here than anywhere else in the system. The desk's whole promise
is that the reader can go and check. A dead citation is not a cosmetic flaw, it
is the promise failing.

Status handling, and why it is not just `== 200`:

  200/3xx      live
  401/403/429  BLOCKED — bot protection, not absence. Merriam-Webster and
               Dictionary.com both 403 a scripted request while being perfectly
               real pages. Treating these as dead would strip the best sources.
  404/410      DEAD. This is the one we are hunting.
  5xx/timeout  UNKNOWN — the site is broken right now, which is not the
               citation's fault. Reported, never fatal.
"""
import concurrent.futures
import re

import requests

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

LIVE, BLOCKED, DEAD, UNKNOWN = "live", "blocked", "dead", "unknown"


def extract_urls(text):
    """Every distinct URL in the text, in order, with trailing punctuation trimmed."""
    seen, out = set(), []
    for raw in _URL_RE.findall(text or ""):
        u = raw.rstrip(".,;:)]}”\"'")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def check_url(url, timeout=20):
    """(status, http_code_or_error). GET, not HEAD — too many sites 405 a HEAD."""
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True,
                         headers={"User-Agent": _UA}, stream=True)
        code = r.status_code
        r.close()
    except requests.RequestException as e:
        return UNKNOWN, type(e).__name__
    if code < 400:
        return LIVE, code
    if code in (401, 403, 429):
        return BLOCKED, code
    if code in (404, 410):
        return DEAD, code
    return UNKNOWN, code


def check_text(text, max_workers=6):
    """Check every URL in `text`. Returns (results, dead) where results is a list
    of (url, status, code) and `dead` is just the dead ones.

    Parallel because a piece cites 5-10 sources and they are independent; serial
    checking of a slow site would dominate the pipeline's wall time.
    """
    urls = extract_urls(text)
    if not urls:
        return [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        statuses = list(ex.map(check_url, urls))
    results = [(u, s, c) for u, (s, c) in zip(urls, statuses)]
    return results, [r for r in results if r[1] == DEAD]


def report(results):
    """Human-readable block for the review notes / the command centre."""
    if not results:
        # Not a pass. A piece citing no URLs at all is LESS checkable than one
        # with a dead link, and it slips through a dead-link test trivially —
        # which is exactly what run #138 did after the record-builder was told it
        # could omit URLs it had not retrieved.
        return ("**No URLs cited at all.** Every source must be identifiable well "
                "enough for a reader to find it; a piece with no addresses needs a "
                "human to confirm the sources are real and specific.")
    order = {DEAD: 0, UNKNOWN: 1, BLOCKED: 2, LIVE: 3}
    lines = ["| status | code | url |", "|---|---|---|"]
    for u, s, c in sorted(results, key=lambda r: order.get(r[1], 9)):
        lines.append(f"| {s.upper()} | {c} | {u} |")
    dead = sum(1 for _, s, _ in results if s == DEAD)
    head = (f"**{dead} of {len(results)} cited URLs are dead.**" if dead
            else f"All {len(results)} cited URLs resolve (or are bot-blocked but real).")
    return head + "\n\n" + "\n".join(lines)

# ── Are the sources checkable at all? ────────────────────────────────────────
# The URL check above answers "does this address resolve". This answers the
# question underneath it, which is the one the desk actually promises: can a
# reader go and find what this rests on?
#
# The two are not the same, and conflating them cost a good piece. Run #147 cited
# Guha's `India After Gandhi` (Macmillan, 2007), Nanda's `The Nehrus` (1962),
# Gopal's `Jawaharlal Nehru` (Harvard, 1975) and a dated Economic Times
# fact-check — every one findable in seconds — and was held purely for having no
# URL, because the search-grounded builder surfaces no addresses on some topics.
# Meanwhile run #146 offered "Biographical records of Feroze Gandhi — minimum
# three independent sources per record", which has no URL either and names
# nothing at all. Holding both for the same reason treated a named book as though
# it were a category.
#
# So the rule is: every source entry must NAME A WORK — carry a URL, a quoted
# title, or an italicised title. A category with a source count bolted on is the
# shape of a citation with the citation removed, and it is what this catches.
# (Owner's ruling, 2026-08-04.)

_SOURCES_RE = re.compile(r"^##+[ 	]*sources[ 	]*$(.*?)(?=^##+[ 	]|\Z)",
                         re.IGNORECASE | re.MULTILINE | re.DOTALL)
# A numbered or bulleted entry in that block.
_ENTRY_RE = re.compile(r"^[ 	]*(?:\d+[.)]|[-*•])[ 	]+(.+?)(?=^[ 	]*(?:\d+[.)]|[-*•])[ 	]|\Z)",
                       re.MULTILINE | re.DOTALL)
# What makes an entry name something: an address, a quoted title, or an
# italicised title. Deliberately structural — it cannot judge whether the work is
# any good, only whether one was named.
_TITLE_RE = re.compile(r"https?://|[\"“][^\"”]{4,}[\"”]|\*[^*\n]{4,}\*|_[^_\n]{4,}_")


def source_entries(text):
    """The numbered entries of the piece's Sources block, or [] if it has none."""
    m = _SOURCES_RE.search(text or "")
    if not m:
        return []
    body = m.group(1)
    entries = [e.strip() for e in _ENTRY_RE.findall(body)]
    if entries:
        return entries
    # A sources block written as prose lines rather than a list.
    return [l.strip() for l in body.splitlines() if l.strip()]


def unnamed_sources(text):
    """Source entries that name no findable work. Empty list = every source is
    checkable, whether or not any of them carries a URL."""
    return [e for e in source_entries(text) if not _TITLE_RE.search(e)]
