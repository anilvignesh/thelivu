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

MAX_BYTES = 2_000_000        # 2MB ceiling per document
MAX_TEXT_CHARS = 40_000      # what we're willing to hand a model
TIMEOUT = 45

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

    PDFs are reported but not parsed — most CAG/MOSPI primary sources are PDFs,
    and adding a PDF stack to this box is a separate decision with a real memory
    cost. Until then a PDF target is a known gap, surfaced honestly rather than
    silently yielding empty text that looks like "nothing found".
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(max_bytes + 1)
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(f"fetch failed for {url}: {e}") from e

    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]

    if "pdf" in content_type or final_url.lower().endswith(".pdf"):
        raise FetchError(
            f"PDF not parsed (known gap, see docs/plans/07-tier0-digger.md): {final_url}"
        )

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
