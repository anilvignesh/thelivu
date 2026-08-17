"""Link ingestion — pull readable text from a pasted URL.

The engine's "paste a link" entry point. Detects YouTube vs. web article and
extracts something the pipeline can work on:
  - YouTube  → handled upstream by the orchestrator's transcript/Gemini path
               (this module only classifies it; see engine.agents.orchestrator).
  - Article  → readable title + body text via requests + lxml (readability-lite),
               with the Indian-ISP retry discipline every network call here needs
               (see docs/HANDOFF.md §5: flaky hosts, connection resets).

Dependency-light on purpose: requests + lxml only (both already vendored). No
bs4/trafilatura. Extraction is heuristic, not perfect — it strips chrome and
keeps the paragraph-dense main content, which is all topic-intake needs to triage
and verify against the open web.
"""

import re
import time
import logging

import requests

log = logging.getLogger("ingestion")

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})")
_IG_RE = re.compile(r"instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_-]+")
_URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def find_url(text):
    """Return the first URL in a blob of text, or None."""
    m = _URL_RE.search(text or "")
    return m.group(0) if m else None


def classify(url):
    """'youtube' | 'instagram' | 'article' for a URL."""
    if _YT_RE.search(url or ""):
        return "youtube"
    if _IG_RE.search(url or ""):
        return "instagram"
    return "article"


def fetch_instagram(url, timeout=30):
    """A single public Instagram post/reel's caption + metadata → {'title',
    'text', 'url', 'video_url'}. `text` is the full caption as posted — for a
    narrated reel that's usually the whole spoken script, same as how a YouTube
    link's transcript gets folded into a topic.

    Deliberately narrow: ONE post a link was pasted for, no login, no cookies,
    no account/profile/hashtag scraping — that stays the declined territory
    (see engine/social_desk.py's module docstring). This is the same class of
    access already used for YouTube (`social_desk.py`'s `_YTDLP`): yt-dlp
    reading Instagram's own public post-embed data, nothing behind a login
    wall. Plain requests+lxml (fetch_article, above) cannot do this — Instagram
    serves an anonymous request a JS shell with no caption in the raw HTML;
    verified empirically 2026-08-17, not assumed.

    `video_url` is a short-lived signed CDN link when Instagram happens to
    expose one combined audio+video stream (uncommon — verified empirically:
    Instagram Reels typically DASH-split into separate video-only and
    audio-only tracks, which `-j` metadata mode lists but does not merge). Most
    of the time this comes back empty even though the post has a video —
    that's not a failure, just this function not doing a real download. If
    watching the actual video (not just its caption) turns out to matter —
    e.g. viral-footage verification, social_desk.py's documented use case —
    that needs an actual yt-dlp download+ffmpeg-merge step, which is a
    different, heavier function than this one.

    Requires yt-dlp (pip package + console script, added to requirements.txt
    alongside this). Raises nothing the caller has to catch specially — same
    graceful-degrade contract as fetch_article: an empty/failed result just
    means the link stays bare for the pipeline to treat as an unverified lead.
    """
    import json
    import subprocess
    import sys
    try:
        # sys.executable -m yt_dlp rather than a bare "yt-dlp" on PATH: the
        # console script's location varies by how/where pip installed it
        # (venv bin, pipx shim, etc.) — the running interpreter is always
        # right, and `-m` is how the pip package guarantees it's importable.
        proc = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--no-warnings", "-j", url],
            capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            log.warning("yt-dlp failed for %s: %s", url, proc.stderr[:300])
            return {"title": "", "text": "", "url": url, "video_url": ""}
        data = json.loads(proc.stdout.splitlines()[0])
    except Exception as e:
        log.warning("Instagram fetch failed for %s: %s", url, e)
        return {"title": "", "text": "", "url": url, "video_url": ""}

    # Prefer a combined (has_audio+has_video) format's direct URL over the
    # bare `url` field, which on Instagram is often just the DASH audio track.
    video_url = ""
    for f in reversed(data.get("formats") or []):
        if f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none"):
            video_url = f.get("url", "")
            break
    video_url = video_url or data.get("url", "")

    return {
        "title": data.get("title") or data.get("description", "")[:80],
        "text": data.get("description") or "",
        "url": url,
        "video_url": video_url,
    }


def youtube_id(url):
    m = _YT_RE.search(url or "")
    return m.group(1) if m else None


def _get(url, tries=6):
    """GET with backoff — Indian ISPs reset connections to many hosts (HANDOFF §5)."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=25)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 — retry any transport/HTTP error
            last = e
            wait = min(2 ** i, 20)
            log.warning("fetch %s failed (try %d/%d): %s — retrying in %ds",
                        url, i + 1, tries, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"could not fetch {url} after {tries} tries: {last}")


# Tags that never hold article body text — dropped before extraction.
_STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer",
               "aside", "form", "figure", "figcaption", "iframe", "svg")


def fetch_article(url):
    """Fetch a web article → {'title', 'text', 'url'}.

    Heuristic readability: parse with lxml, drop chrome tags, then take the
    block (article/main/body) with the most paragraph text. Truncates the body
    so it stays a lead for triage, not a reproduction of the source.
    """
    from lxml import html as lxml_html

    r = _get(url)
    doc = lxml_html.fromstring(r.content)

    # Title: <title>, or the first <h1>.
    title = ""
    t = doc.find(".//title")
    if t is not None and t.text:
        title = t.text.strip()
    if not title:
        h1 = doc.find(".//h1")
        if h1 is not None:
            title = (h1.text_content() or "").strip()

    for tag in _STRIP_TAGS:
        for el in doc.iter(tag):
            el.drop_tree()

    # Prefer semantic containers; fall back to the whole document.
    candidates = doc.xpath("//article") or doc.xpath("//main") or [doc]
    best_text, best_len = "", 0
    for node in candidates:
        paras = [p.text_content().strip() for p in node.xpath(".//p")]
        paras = [p for p in paras if len(p) > 40]  # drop nav/caption fragments
        text = "\n\n".join(paras)
        if len(text) > best_len:
            best_text, best_len = text, len(text)

    # Last resort: all paragraph text on the page.
    if best_len < 200:
        paras = [p.text_content().strip() for p in doc.xpath("//p")]
        best_text = "\n\n".join(p for p in paras if len(p) > 40)

    best_text = re.sub(r"\n{3,}", "\n\n", best_text).strip()
    if len(best_text) > 8000:
        best_text = best_text[:8000] + "\n\n[…truncated]"

    return {"title": title, "text": best_text, "url": url}
