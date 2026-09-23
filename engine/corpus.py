"""Read the whole document, and keep it.

Anil, 2026-09-14, on why our output reads like everyone else's: *"the what we
find is on par with a normal news agency. Both the investigation and the final
output."* He was right, and the reason turned out to be measurable rather than
editorial.

Kerala's 2024 audit report is 258 pages and 561,598 characters. The digger read
40,000 of them — **7.1%** — and kept a 125-character excerpt afterwards. So every
finding came out of the executive summary of a report whose headline findings
the auditor had already published, and no two documents could ever be compared
because neither was retained. "₹30,308 crore uncollected" is on page 11. It is
supposed to be easy to find; the CAG put it there.

The findings nobody else has are in the annexures — pages 40 to 258 — and in
what happens when you put ten years of one state, or one year of twenty-nine
states, beside each other. Neither is reachable from 7% of one PDF.

**WHY THIS IS NOT IN THE DIGGER.** That box is a 945MB E2.1.Micro under a 256MB
cap, and it stalls parsing a 258-page PDF (measured 2026-09-14 — the process sat
at 8MB RSS and 0% CPU and never returned). The digger stays a DETECTOR: find
documents, archive the bytes, take a bounded first pass. Reading in full happens
on a machine with memory, which is also where an attended pass would run.

Anil, on paying for it: *"use the free models for it, or even do that in the
attended mode"* and *"since this is the initial setup"*. So this separates the
one-time backfill from the steady state. The backfill may be slow and may be
watched; the steady state must not need either.
"""

import logging
import re
import time

log = logging.getLogger("corpus")

# A 258-page report parses on a laptop in seconds and needs no cap. The bound is
# here only to refuse something pathological — a 5,000-page scanned appendix
# would take the whole backfill window on one file.
MAX_PAGES = 600
# Pause between documents. These are government servers being asked for a lot of
# PDFs in a row by one client, which is a thing to do politely whether or not
# robots.txt sets a delay.
POLITE_SECONDS = 1.5


def parse_full(pdf_bytes, max_pages=MAX_PAGES):
    """(text, page_count) for a whole PDF. Raises on an unusable file."""
    import liteparse

    lp = liteparse.LiteParse(quiet=True, num_workers=1, pool_size=1,
                             max_pages=max_pages, parse_timeout=600)
    try:
        result = lp.parse(pdf_bytes)
        pages = list(getattr(result, "pages", None) or [])
        text = "\n".join((getattr(p, "text", None) or "") for p in pages)
        return text, len(pages)
    finally:
        try:
            lp.close()
        except Exception:
            pass


def year_of(url, text=""):
    """The document's year, from its filename or its opening lines.

    Needed because the corpus is only worth building if documents can be put in
    order — "the fifth consecutive year" is the whole point, and it cannot be
    asked of an unsorted pile.
    """
    name = url.rsplit("/", 1)[-1]
    # A CAG filename carries the report year; the long hash after it also
    # contains digits, so take the FIRST plausible year in the human part.
    for m in re.finditer(r"(19|20)\d{2}", name):
        y = int(m.group(0))
        if 1990 <= y <= 2035:
            return str(y)
    head = (text or "")[:4000]
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", head)
             if 1990 <= int(y) <= 2035]
    return str(max(years)) if years else None


# What makes a document worth keeping. Measured against a real CAG index on
# 2026-09-14: \.pdf$ on the Kerala AG page returns sixteen files, and the first
# six are an internship scheme, two staff-programme decks, an SOP on legal
# assistance to retired officials, and a brochure called "Global Footprints".
# The audit reports are further down. "Read everything" is worthless if
# everything includes HR policy.
#
# Filtered on CONTENT, not filename, because a filename convention is a
# guess about one publisher and this has to hold for the next twenty-eight
# offices and whatever gets added after them.
_AUDIT_LANGUAGE = (
    "audit", "auditor", "objection", "utilisation certificate", "irregular",
    "outstanding", "expenditure", "sanction", "grant", "misappropriat",
    "non-compliance", "shortfall", "excess", "recovery",
)
# A figure with a scale word beside it. An audit report states money; an
# internship brochure does not.
_MONEY = re.compile(r"(?:₹|Rs\.?)\s*[\d,]+(?:\.\d+)?|\b\d[\d,]*\.?\d*\s*(?:crore|lakh)\b",
                    re.IGNORECASE)


def worth_keeping(text, pages):
    """Is this a record with findings in it, or an office document? (bool, why).

    Deliberately generous. The cost of keeping a dull document is a row; the
    cost of dropping a real one is a finding nobody ever makes. So this refuses
    only what is clearly not a record at all.
    """
    body = (text or "").lower()
    if len(body) < 5_000:
        return False, "too short to carry findings"
    hits = sum(1 for w in _AUDIT_LANGUAGE if w in body)
    money = len(_MONEY.findall(text or ""))
    if hits < 4:
        return False, f"no audit vocabulary ({hits} term(s))"
    if money < 10:
        return False, f"states almost no money ({money} figure(s))"
    return True, f"{hits} audit terms, {money} money figures, {pages} pages"


def read_index(index_url, link_pattern, source_key, limit=None,
               skip_held=True, progress=None):
    """Fetch every document at an index, read it in full, store the text.

    Returns {read, skipped, failed}, plus `error` when the INDEX itself could
    not be read. RESUMABLE: a document already in the corpus is skipped by hash,
    so an interrupted backfill costs only the document it was on. It will be
    interrupted — 477 documents over government links is not a run that
    completes first time.

    `error` exists because "failed: 1" is not an answer. cag-rajasthan sat at
    zero documents for days behind exactly that number: the index was refused
    three times, the reason went only to a logger the one-office-per-process
    backfill driver never captured, and what survived was a count that reads
    identically whether the source is empty, broken, or refusing us. Invariant
    4 — silence is reported — is about this.
    """
    from engine.digger import fetch
    from shared import archive, db

    try:
        items = fetch.fetch_index(index_url, link_pattern)
    except Exception as e:                                  # noqa: BLE001
        log.warning("%s: index unreadable — %s: %s",
                    source_key, type(e).__name__, e)
        return {"read": 0, "skipped": 0, "failed": 1,
                "error": f"{type(e).__name__}: {e}"}

    if limit:
        items = items[:limit]
    out = {"read": 0, "skipped": 0, "failed": 0}

    for n, item in enumerate(items, 1):
        url = item["url"]
        try:
            raw = _fetch_bytes(url)
        except Exception as e:                              # noqa: BLE001
            log.info("%s: could not fetch %s (%s)", source_key, url[:70], e)
            out["failed"] += 1
            continue

        sha = archive.digest(raw)
        if skip_held and db.have_document(sha):
            out["skipped"] += 1
            continue

        try:
            text, pages = parse_full(raw)
        except Exception as e:                              # noqa: BLE001
            log.info("%s: could not parse %s (%s)", source_key, url[:70],
                     str(e)[:80])
            out["failed"] += 1
            continue

        keep, why = worth_keeping(text, pages)
        if not keep:
            log.info("%s: skipping %s — %s", source_key,
                     url.rsplit("/", 1)[-1][:46], why)
            out["skipped"] += 1
            time.sleep(POLITE_SECONDS)
            continue

        if len(text.strip()) < 500:
            # A scan with no text layer. The digger's OCR path handles those one
            # at a time; a 258-page OCR at 8s a page is a different job and does
            # not belong inside a backfill loop.
            log.info("%s: %s has no text layer (%d chars) — left for OCR",
                     source_key, url.rsplit("/", 1)[-1][:50], len(text))
            out["failed"] += 1
            continue

        db.store_document(sha, url, text, title=item.get("title") or None,
                          source_key=source_key, published=year_of(url, text),
                          pages=pages)
        out["read"] += 1
        if progress:
            progress(n, len(items), url, pages, len(text))
        log.info("%s: %s — %d pages, %d chars", source_key,
                 url.rsplit("/", 1)[-1][:50], pages, len(text))
        time.sleep(POLITE_SECONDS)

    return out


def _fetch_bytes(url, timeout=180):
    """The raw PDF. Robots is checked; a refusal is a refusal here too."""
    import urllib.request

    from engine.digger import robots

    robots.check(url)
    req = urllib.request.Request(
        url, headers={"User-Agent": "ThelivuDigger/1.0 (+https://thelivu.com)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(40_000_000)


def backfill(targets=None, limit_per_target=None, progress=None):
    """Read every document behind every configured index. Returns totals.

    The one-time pass Anil authorised with "since this is the initial setup".
    Steady state is a different job: the digger already notices new documents
    every cycle, and only what it has not seen needs reading.
    """
    from engine.digger import targets as tmod

    if targets is None:
        targets = [t for t in tmod.active_targets()
                   if t.get("index_url") and not t.get("kind") == "dataset"]
    totals = {"read": 0, "skipped": 0, "failed": 0}
    for t in targets:
        got = read_index(t["index_url"], t.get("link_pattern"), t["key"],
                         limit=limit_per_target, progress=progress)
        for k in totals:
            totals[k] += got[k]
        # An office that read nothing has to say why, in the same line that
        # reports the count. A bare "0 read, 1 failed" is the shape of an
        # answer without being one.
        if got.get("error"):
            log.warning("%s: %d read, %d already held, %d failed — %s",
                        t["key"], got["read"], got["skipped"], got["failed"],
                        got["error"])
        else:
            log.info("%s: %d read, %d already held, %d failed",
                     t["key"], got["read"], got["skipped"], got["failed"])
    return totals
