"""Social desk — Thelivu's eyes on social media, the safe way.

Gives the engine/agents read access to social + web WITHOUT the risky account-scraping
(no Twitter/Reddit/Instagram cookie-scraping, no ToS/suspension exposure). Uses only
zero-config, well-known tools we control:
  - YouTube (search, channel latest, transcript)  -> yt-dlp
  - Any web page, clean text                       -> Jina Reader (r.jina.ai, public)
  - RSS/Atom                                        -> feedparser

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
    """Latest items from an RSS/Atom feed. Returns [{title, link, published, summary}]."""
    import feedparser
    d = feedparser.parse(feed_url)
    out = []
    for e in d.entries[:n]:
        out.append({
            "title": e.get("title", ""),
            "link": e.get("link", ""),
            "published": e.get("published", e.get("updated", "")),
            "summary": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:400],
        })
    return out


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="Thelivu social desk (safe: YouTube/web/RSS)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("yt-search"); s.add_argument("query"); s.add_argument("-n", type=int, default=5)
    c = sub.add_parser("yt-channel"); c.add_argument("channel"); c.add_argument("-n", type=int, default=5)
    t = sub.add_parser("yt-transcript"); t.add_argument("video")
    w = sub.add_parser("web"); w.add_argument("url")
    r = sub.add_parser("rss"); r.add_argument("feed"); r.add_argument("-n", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "yt-search":
        print(json.dumps(youtube_search(a.query, a.n), indent=2))
    elif a.cmd == "yt-channel":
        print(json.dumps(channel_latest(a.channel, a.n), indent=2))
    elif a.cmd == "yt-transcript":
        print(youtube_transcript(a.video)[:4000])
    elif a.cmd == "web":
        print(web_read(a.url)[:4000])
    elif a.cmd == "rss":
        print(json.dumps(rss_latest(a.feed, a.n), indent=2))
