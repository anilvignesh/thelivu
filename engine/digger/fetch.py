"""Document fetching — the grounding step.

Everything downstream reads ONLY what this module returns. If a finding cannot
be traced to bytes fetched here, it is model recall, which is precisely what
Tier 0 must never emit.

Size and time caps are not politeness, they are survival: this runs on a 945MB
burstable VM where an unbounded read is enough to put the box into a swap
death-spiral (see brain/1GB VM Memory Traps in the vault).
"""

import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

MAX_BYTES = 2_000_000        # 2MB ceiling per HTML document
MAX_TEXT_CHARS = 40_000      # what we're willing to hand a model
TIMEOUT = 45

# PDFs get their own, larger ceiling: CAG/MOSPI primary sources are routinely
# several MB, and refusing them would exclude the highest-value records on the
# beat. Still bounded — an unbounded read is how this box dies.
MAX_PDF_BYTES = 15_000_000
# Page and time caps matter more than the byte cap for a 900-page audit report.
MAX_PDF_PAGES = 40
PDF_PARSE_TIMEOUT = 60

USER_AGENT = (
    "Mozilla/5.0 (compatible; ThelivuDigger/1.0; +https://thelivu.com) "
    "python-urllib"
)

_DROP_TAGS = {"script", "style", "noscript", "svg", "head"}


class _TextExtractor(HTMLParser):
    """Deliberately stdlib-only. The VM has a tight memory budget and this needs
    to survive on malformed government HTML, where a strict parser is a
    liability — HTMLParser is lenient by design."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in _DROP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self):
        return "\n".join(self.parts)


def html_to_text(html):
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:
        # A parse blow-up should degrade to "no text", never kill the cycle.
        return ""
    out = p.text()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


class FetchError(RuntimeError):
    pass


def fetch(url, timeout=TIMEOUT, max_bytes=MAX_BYTES):
    """Return {url, final_url, text, fetched_at, content_type, truncated}.

    PDFs are parsed via liteparse (see pdf_to_text). A PDF with no text layer,
    or a host without liteparse installed, raises FetchError rather than
    returning empty text that would read as "nothing found".
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            # Decide the ceiling AFTER seeing the response: a PDF is allowed more
            # than an HTML page, and the Content-Type is the only reliable signal
            # (plenty of these URLs do not end in .pdf).
            cap = max_bytes
            if "pdf" in content_type or resp.geturl().lower().endswith(".pdf"):
                cap = max(max_bytes, MAX_PDF_BYTES)
            raw = resp.read(cap + 1)
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(f"fetch failed for {url}: {e}") from e

    truncated = len(raw) > cap
    raw = raw[:cap]

    if "pdf" in content_type or final_url.lower().endswith(".pdf"):
        text = pdf_to_text(raw)
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
            truncated = True
        return {
            "url": url,
            "final_url": final_url,
            "text": text,
            "content_type": content_type or "application/pdf",
            "truncated": truncated,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", content_type)
    if m:
        charset = m.group(1)
    html = raw.decode(charset, errors="replace")

    text = html_to_text(html) if "html" in content_type or "<" in html[:200] else html
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        truncated = True

    if not text.strip():
        raise FetchError(f"no extractable text at {final_url}")

    return {
        "url": url,
        "final_url": final_url,
        "text": text,
        "content_type": content_type,
        "truncated": truncated,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# Index pages -> document URLs
#
# A listing page is NOT a document. The RBI press-release index, for one, is
# ~12k characters of pure navigation chrome with the actual releases loaded by
# JS — a model reading that page correctly finds nothing (verified 2026-09-10).
# So the loop reads an index only to pick a document, then fetches THAT.
# ---------------------------------------------------------------------------

_ITEM_RE = re.compile(r"<item[^>]*>(.*?)</item>", re.S | re.I)
_ENTRY_RE = re.compile(r"<entry[^>]*>(.*?)</entry>", re.S | re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S | re.I)
_LINK_RE = re.compile(r"<link[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", re.S | re.I)
_ATOM_LINK_RE = re.compile(r"<link[^>]*href=[\"']([^\"']+)[\"']", re.I)


def parse_feed(xml):
    """RSS/Atom -> [{title, url}]. Deliberately regex, not an XML parser:
    government feeds are frequently malformed enough that a strict parser
    refuses them outright, and a lenient scrape is what actually survives."""
    out = []
    blocks = _ITEM_RE.findall(xml) or _ENTRY_RE.findall(xml)
    for b in blocks:
        tm = _TITLE_RE.search(b)
        lm = _LINK_RE.search(b)
        url = (lm.group(1).strip() if lm else "")
        if not url:
            am = _ATOM_LINK_RE.search(b)
            url = am.group(1).strip() if am else ""
        title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""
        if url.startswith("http"):
            out.append({"title": title, "url": url})
    return out


_HREF_RE = re.compile(r"<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.S | re.I)


def extract_links(html, base_url, pattern=None):
    """Absolute document links from an HTML index, optionally filtered."""
    from urllib.parse import urljoin
    rx = re.compile(pattern, re.I) if pattern else None
    seen, out = set(), []
    for href, label in _HREF_RE.findall(html):
        url = urljoin(base_url, href.strip())
        if not url.startswith("http") or url in seen:
            continue
        if rx and not rx.search(url):
            continue
        seen.add(url)
        out.append({"title": re.sub(r"<[^>]+>", "", label).strip()[:200], "url": url})
    return out


def fetch_index(url, pattern=None, timeout=TIMEOUT):
    """Fetch an index and return candidate document links.

    Handles a feed or an HTML listing without the caller caring which — several
    of these sources have quietly switched format before.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(MAX_BYTES)
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} for index {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(f"index fetch failed for {url}: {e}") from e

    body = raw.decode("utf-8", errors="replace")
    items = []
    if "xml" in content_type or "rss" in content_type or "<rss" in body[:400] or "<feed" in body[:400]:
        items = parse_feed(body)
    if not items:
        items = extract_links(body, final_url, pattern)
    if not items:
        raise FetchError(f"no document links found at index {final_url}")
    return items

# ---------------------------------------------------------------------------
# PDF text extraction (liteparse)
#
# Most CAG/MOSPI primary records are PDFs, so refusing them excluded the best
# sources on the beat. liteparse is a 13.8MB manylinux wheel with NO runtime
# dependencies — Rust + PDFium, ~2-5ms/page. Measured 2026-09-10 on a real
# 2.8MB / 8-page CAG circular: 0.06s, 35MB peak RSS, 24k chars.
#
# Settings are chosen for a 945MB box, not for maximum fidelity:
#   ocr_enabled=False  — Tesseract is the memory-hungry path, and a scanned PDF
#                        yielding little text is an honest miss, not a reason to
#                        burn the box's whole memory budget on OCR.
#   num_workers=1      — this is a burstable 1/8-OCPU shape; parallel page
#                        workers buy nothing and cost memory.
#   max_pages/timeout  — a 900-page audit report must not become an unbounded job.
#
# The import is lazy and optional: without liteparse installed, a PDF target
# reports the same honest "not parsed" miss it did before, so tests and the
# laptop do not need the dependency.
# ---------------------------------------------------------------------------

def _new_parser():
    """A fresh parser per call, closed explicitly.

    NOT a module-level singleton. liteparse runs a worker pool with daemon
    threads, and letting the object reach __del__ at interpreter shutdown
    aborts the process with a core dump:

        Fatal Python error: _enter_buffered_busy: could not acquire lock
        for <_io.BufferedReader> at interpreter shutdown

    (reproduced 2026-09-10 on liteparse 2.14.4). A long-running service that
    core-dumps on exit is not acceptable, and the systemd unit would see every
    stop as a failure. Creating and closing per call sidesteps shutdown-time GC
    entirely, and costs little: the whole parse of a 2.8MB / 8-page CAG PDF,
    pool startup included, measured 0.06s.
    """
    import liteparse
    return liteparse.LiteParse(
        ocr_enabled=False,
        max_pages=MAX_PDF_PAGES,
        num_workers=1,
        pool_size=1,
        parse_timeout=PDF_PARSE_TIMEOUT,
        quiet=True,
    )


def pdf_to_text(data):
    """PDF bytes -> text. Raises FetchError on anything that isn't usable."""
    try:
        lp = _new_parser()
    except ImportError as e:
        raise FetchError(
            "PDF not parsed: liteparse is not installed on this host "
            "(pip install liteparse; see ops/oracle-vm/deploy-digger.sh)"
        ) from e
    except Exception as e:
        raise FetchError(f"PDF parser unavailable: {type(e).__name__}: {e}") from e

    try:
        result = lp.parse(data)
        # `.text` is the whole document; `.pages[].text` is the per-page
        # fallback. NOT `.markdown` — that stays empty unless output_format is
        # set to markdown, which cost an hour on 2026-09-10 by looking exactly
        # like "this PDF has no text layer".
        text = (getattr(result, "text", None) or "").strip()
        if not text:
            pages = getattr(result, "pages", None) or []
            text = "\n\n".join(
                (getattr(p, "text", None) or "") for p in pages[:MAX_PDF_PAGES]
            ).strip()
    except Exception as e:
        raise FetchError(f"PDF parse failed: {type(e).__name__}: {e}") from e
    finally:
        try:
            lp.close()
        except Exception:
            pass

    if not text:
        # Almost always a scanned/image-only PDF with no text layer. Say so:
        # an empty extraction that reads as "nothing found" is worse than a miss.
        raise FetchError(
            "PDF has no extractable text layer (likely scanned; OCR is disabled "
            "on this host by design)"
        )
    return text
