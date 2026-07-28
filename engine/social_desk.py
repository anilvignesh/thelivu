"""Social desk — Thelivu's eyes on social media, the safe way.

Gives the engine/agents read access to social + web WITHOUT the risky account-scraping
(no Twitter/Reddit/Instagram cookie-scraping, no ToS/suspension exposure). Uses only
zero-config, well-known tools we control:
  - YouTube (search, channel latest, transcript)  -> yt-dlp
  - Any web page, clean text                       -> Jina Reader (r.jina.ai, public)
  - RSS/Atom                                        -> feedparser
  - X/Twitter timelines, READ-ONLY                 -> Nitter RSS (no account, no cookies)

WHY NITTER AND NOT A SCRAPER (2026-07-28): we missed the Bareilly assault story —
a saffron activist filmed slapping two students on their way to the CJP protest —
because it broke on X and we had no way to read X. The considered alternative
(agent-reach) installs ~9 unpinned upstream tools and stores authenticated X
cookies on the same box as the Instagram publishing token and prod Postgres URL.
Nitter needs no account, no cookies and no install: it is a public RSS bridge, so
it fits the existing rss path and adds zero supply-chain surface. Public instances
come and go, hence the fallback list.

CHARTER DISCIPLINE (do not bypass): social is a LEAD surface. A credible, identified
fact-checker/journalist (see engine/sources.yaml social candidates) can SURFACE a lead
and, per its tier, CORROBORATE — but a load-bearing fact still gets checked against the
primary record. Anonymous/viral social is lead-generation only. This module fetches;
the trust gate still decides.
"""
import subprocess
import tempfile
import re
import os
from pathlib import Path

import requests

_YTDLP = os.path.expanduser("~/.local/bin/yt-dlp")
if not os.path.exists(_YTDLP):
    _YTDLP = "yt-dlp"  # fall back to PATH
_JINA = "https://r.jina.ai/"
_TIMEOUT = 90


def youtube_search(query, n=5):
    """Search YouTube. Returns [{title, uploader, url, id}]. Titles/metadata only —
    no video is downloaded."""
    out = subprocess.run(
        [_YTDLP, "--no-warnings", "--flat-playlist",
         "--print", "%(id)s\t%(title)s\t%(uploader)s", f"ytsearch{n}:{query}"],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 1 and parts[0]:
            vid = parts[0]
            rows.append({
                "id": vid,
                "title": parts[1] if len(parts) > 1 else "",
                "uploader": parts[2] if len(parts) > 2 else "",
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
    return rows


def channel_latest(channel, n=5):
    """Latest uploads from a channel. `channel` is a handle (@handle), channel URL,
    or channel id. Returns [{title, url, id}]."""
    if channel.startswith("@"):
        url = f"https://www.youtube.com/{channel}/videos"
    elif channel.startswith("http"):
        url = channel.rstrip("/") + "/videos" if "/videos" not in channel else channel
    else:
        url = f"https://www.youtube.com/channel/{channel}/videos"
    out = subprocess.run(
        [_YTDLP, "--no-warnings", "--flat-playlist", "--playlist-end", str(n),
         "--print", "%(id)s\t%(title)s", url],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0]:
            rows.append({"id": parts[0], "title": parts[1] if len(parts) > 1 else "",
                         "url": f"https://www.youtube.com/watch?v={parts[0]}"})
    return rows


def _parse_vtt(text):
    """VTT -> plain transcript text (strip timestamps, cue tags, dedupe repeats)."""
    lines, seen_last = [], None
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or "-->" in ln or ln.isdigit():
            continue
        if ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)          # strip <c> timing tags
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln and ln != seen_last:               # auto-subs repeat lines a lot
            lines.append(ln); seen_last = ln
    return " ".join(lines)


def youtube_transcript(video, lang="en"):
    """Auto-caption transcript for a video (id or url). Returns plain text or ''."""
    url = video if video.startswith("http") else f"https://www.youtube.com/watch?v={video}"
    with tempfile.TemporaryDirectory(prefix="ytsub_") as tmp:
        subprocess.run(
            [_YTDLP, "--no-warnings", "--skip-download", "--write-auto-subs",
             "--sub-lang", f"{lang}.*", "--sub-format", "vtt",
             "-o", f"{tmp}/%(id)s.%(ext)s", url],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        vtts = list(Path(tmp).glob("*.vtt"))
        if not vtts:
            return ""
        return _parse_vtt(vtts[0].read_text(encoding="utf-8", errors="ignore"))


def web_read(url):
    """Clean, readable text of any web page via Jina Reader (public, no key). Good for
    pages that block our normal fetcher. Returns markdown-ish text."""
    r = requests.get(_JINA + url, timeout=_TIMEOUT,
                     headers={"User-Agent": "Thelivu-social-desk"})
    r.raise_for_status()
    return r.text


def rss_latest(feed_url, n=10):
    """Latest items from an RSS/Atom feed. Returns [{title, link, published, summary}].

    Raises on a feed that parsed to nothing. A silently-empty feed is how a sweep
    concludes "quiet day" when the truth is "broken input" — that happened on
    2026-07-28 with thenewsminute.com/feed, which serves a single item.
    """
    import feedparser
    d = feedparser.parse(feed_url)
    if not d.entries:
        why = getattr(d, "bozo_exception", None) or f"status={getattr(d, 'status', '?')}"
        raise ValueError(f"feed returned no entries: {feed_url} ({why})")
    out = []
    for e in d.entries[:n]:
        out.append({
            "title": e.get("title", ""),
            "link": e.get("link", ""),
            "published": e.get("published", e.get("updated", "")),
            "summary": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:400],
        })
    return out


# Some bridges answer 200 with their error text wrapped as a feed ENTRY (xcancel
# returns "RSS reader not yet whitelisted!"). That parses as a perfectly valid
# item and would enter a sweep as if it were a post, so match and reject it.
_BRIDGE_ERROR = re.compile(
    r"not yet whitelist|rate limit|instance has been blocked|error|captcha|"
    r"please send an email", re.I)


def _looks_like_bridge_error(items):
    if len(items) > 2:
        return False
    return any(_BRIDGE_ERROR.search(i.get("title", "")) for i in items)


# Public Nitter bridges, tried in order. They rot — when they all fail, that is a
# real finding (X went dark on us), not something to paper over.
NITTER_INSTANCES = [
    os.environ.get("NITTER_INSTANCE", "").rstrip("/") or None,
    "https://nitter.net",
    "https://xcancel.com",
    "https://nitter.poast.org",
]


def x_timeline(handle, n=15):
    """Recent public posts from an X account, read-only, via a Nitter RSS bridge.

    `handle` may be '@scroll_in' or 'scroll_in'. Returns the rss_latest shape plus
    'instance'. Tries each bridge until one yields entries; raises if all fail —
    losing X visibility silently is exactly the failure this exists to prevent.
    """
    h = handle.lstrip("@").strip()
    errors = []
    for base in NITTER_INSTANCES:
        if not base:
            continue
        feed = f"{base}/{h}/rss"
        try:
            items = rss_latest(feed, n)
        except Exception as e:
            errors.append(f"{base}: {str(e)[:90]}")
            continue
        if _looks_like_bridge_error(items):
            errors.append(f"{base}: bridge error page ({items[0].get('title','')[:50]})")
            continue
        for it in items:
            it["instance"] = base
        return items
    raise RuntimeError(f"no Nitter bridge served @{h} — tried: {'; '.join(errors)}")


def x_search(query, n=15):
    """Search public X posts via a Nitter bridge's search RSS.

    ⚠️ As of 2026-07-28 NO public bridge serves search: nitter.net and poast
    return empty, xcancel demands whitelisting. Kept because it costs nothing and
    a self-hosted instance (NITTER_INSTANCE) does support it. **Monitor named
    handles with x_timeline instead** — that works today. Raises rather than
    returning [] so a caller can't read "no bridge" as "nothing was posted".
    """
    from urllib.parse import quote
    errors = []
    for base in NITTER_INSTANCES:
        if not base:
            continue
        feed = f"{base}/search/rss?f=tweets&q={quote(query)}"
        try:
            items = rss_latest(feed, n)
        except Exception as e:
            errors.append(f"{base}: {str(e)[:90]}")
            continue
        if _looks_like_bridge_error(items):
            errors.append(f"{base}: bridge error page ({items[0].get('title','')[:50]})")
            continue
        for it in items:
            it["instance"] = base
        return items
    raise RuntimeError(f"no Nitter bridge served search {query!r} — tried: {'; '.join(errors)}")


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="Thelivu social desk (safe: YouTube/web/RSS)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("yt-search"); s.add_argument("query"); s.add_argument("-n", type=int, default=5)
    c = sub.add_parser("yt-channel"); c.add_argument("channel"); c.add_argument("-n", type=int, default=5)
    t = sub.add_parser("yt-transcript"); t.add_argument("video")
    w = sub.add_parser("web"); w.add_argument("url"); w.add_argument("-c", type=int, default=4000)
    r = sub.add_parser("rss"); r.add_argument("feed"); r.add_argument("-n", type=int, default=10)
    x = sub.add_parser("x"); x.add_argument("handle"); x.add_argument("-n", type=int, default=15)
    xs = sub.add_parser("x-search"); xs.add_argument("query"); xs.add_argument("-n", type=int, default=15)
    a = ap.parse_args()
    if a.cmd == "yt-search":
        print(json.dumps(youtube_search(a.query, a.n), indent=2))
    elif a.cmd == "yt-channel":
        print(json.dumps(channel_latest(a.channel, a.n), indent=2))
    elif a.cmd == "yt-transcript":
        print(youtube_transcript(a.video)[:4000])
    elif a.cmd == "web":
        # -c 0 for the whole page; the old hard 4000-char cut silently truncated
        # article bodies mid-sentence.
        text = web_read(a.url)
        print(text if a.c <= 0 else text[:a.c])
    elif a.cmd == "rss":
        print(json.dumps(rss_latest(a.feed, a.n), indent=2))
    elif a.cmd == "x":
        print(json.dumps(x_timeline(a.handle, a.n), indent=2))
    elif a.cmd == "x-search":
        print(json.dumps(x_search(a.query, a.n), indent=2))
