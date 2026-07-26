"""Minimal public web server: rendered slide images + the bio page.

Runs inside the thelivu-agent process on a background thread, serving
articles/slides/*.png plus the "link in bio" page (/ and /bio — see
publishing/biopage.py) over plain HTTP. Exists so Instagram's Graph API
(which needs a fetchable image_url) can pull the rendered slide straight from
our own infrastructure — no third-party image host, no bot token embedded in
a URL handed to Meta. The bot service that handles the approve tap runs as a
separate Railway service with its own filesystem, so it needs a URL, not a
local path — see process_queued_carousels() in engine/agents/orchestrator.py.
"""
import http.server
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger("fileserver")

# carousel_<carouselId>_<position>.(png|jpg) — the on-demand-renderable slides.
_SLIDE_RE = re.compile(r"^carousel_(\d+)_(\d+)\.(?:png|jpg)$")


def _make_handler(slides_dir):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.lstrip("/").split("?")[0]
            # The bio page lives at the root so the Instagram bio can point at
            # the bare base URL. Rendered per request — the bot process writes
            # bio_links and this process reads them, so there's nothing to cache.
            if name in ("", "bio"):
                try:
                    from publishing.biopage import render
                    from shared.config import CHANNEL_PUBLIC_URL
                    from shared.db import list_bio_links
                    page = render(list_bio_links(), CHANNEL_PUBLIC_URL).encode("utf-8")
                except Exception as e:
                    log.error("Bio page render failed: %s", e)
                    self.send_response(500)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                # The page changes with every publish; without this, in-app
                # browsers (Instagram especially) show stale copies for hours.
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(page)
                return
            # Self-hosted article pages: /a/<run_id>-<kebab-headline>. Rendered
            # per request from the approved draft in the DB — the human gate
            # holds because anything not status='published' 404s.
            if name.startswith("a/"):
                try:
                    from publishing.articlepage import render_article, render_not_found
                    from publishing.parser import parse_article, prepare_for_publish
                    from shared.config import CONTACT_HANDLE
                    from shared.db import get_run_by_slug
                    run = get_run_by_slug(name[2:])
                    if run and run.get("status") == "published" and run.get("draft_text"):
                        article = parse_article(prepare_for_publish(run["draft_text"], CONTACT_HANDLE))
                        page, code = render_article(article, run.get("updated_at")).encode("utf-8"), 200
                    else:
                        page, code = render_not_found().encode("utf-8"), 404
                except Exception as e:
                    log.error("Article page render failed for %r: %s", name, e)
                    self.send_response(500)
                    self.end_headers()
                    return
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                # Corrections must show immediately — we correct openly, and a
                # cached wrong version defeats that.
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(page)
                return
            # Reel MP4s: /reel/<id>.mp4 — served from the DB (Piper/ffmpeg run on
            # Anil's laptop, so Railway can't regenerate them; the bytes live in the
            # reels table). Range + HEAD supported because Instagram's video
            # ingestion probes with them.
            m = re.match(r"^reel/(\d+)\.mp4$", name)
            if m:
                from shared.db import get_reel_bytes
                data = get_reel_bytes(int(m.group(1)))
                if data is None:
                    self.send_response(404); self.end_headers(); return
                self._serve_bytes(data, "video/mp4")
                return

            # Bare filename only, inside slides_dir — no path traversal, no
            # directory listing, nothing else on disk is reachable. Serve PNG
            # (legacy) and JPG (Instagram prefers JPEG — see below).
            if "/" in name or ".." in name or not (name.endswith(".png") or name.endswith(".jpg")):
                self.send_response(404)
                self.end_headers()
                return
            path = slides_dir / name
            # ?fresh=1 forces a re-render even when a cached file exists — the
            # command center uses it after an owner edits a slide headline, so
            # the file Meta fetches at post time matches the DB, not a stale
            # pre-edit render. Idempotent (renders only what's in the DB).
            force_fresh = "fresh=1" in (self.path.split("?", 1)[1] if "?" in self.path else "")
            if force_fresh or not path.is_file():
                # On-demand render: regenerate the slide from the DB so rendered
                # PNGs never have to survive a redeploy or the cleanup sweep — same
                # self-hosting philosophy as the /a/<slug> article pages. Rendered
                # once here, then cached on disk for subsequent fetches.
                m = _SLIDE_RE.match(name)
                if m:
                    try:
                        from shared.db import get_slide_render_data
                        from publishing.slides import render_dossier_slide
                        cid, pos = int(m.group(1)), int(m.group(2))
                        d = get_slide_render_data(cid, pos)
                        if d:
                            slide_stamp = d["stamp"] if pos == 1 else f"{pos}/{d['total']}"
                            # out path keeps the requested extension → PIL saves PNG
                            # or JPEG accordingly (Image.save infers from extension).
                            render_dossier_slide(d["headline"], stamp=slide_stamp,
                                                 dark=d["dark"], out=str(path))
                            log.info("On-demand rendered %s", name)
                    except Exception as e:
                        log.error("On-demand slide render failed for %r: %s", name, e)
                if not path.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg" if name.endswith(".jpg") else "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_bytes(self, data, content_type):
            """Serve an in-memory blob with HTTP Range support (Instagram's video
            fetcher issues ranged GETs). Full 200 when no Range header."""
            total = len(data)
            rng = self.headers.get("Range")
            if rng:
                m = re.match(r"bytes=(\d*)-(\d*)", rng)
                if m:
                    start = int(m.group(1)) if m.group(1) else 0
                    end = int(m.group(2)) if m.group(2) else total - 1
                    end = min(end, total - 1)
                    if start > end or start >= total:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{total}")
                        self.end_headers()
                        return
                    chunk = data[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.end_headers()
                    self.wfile.write(chunk)
                    return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(total))
            self.end_headers()
            self.wfile.write(data)

        def do_HEAD(self):
            name = self.path.lstrip("/").split("?")[0]
            m = re.match(r"^reel/(\d+)\.mp4$", name)
            if m:
                from shared.db import get_reel_bytes
                data = get_reel_bytes(int(m.group(1)))
                if data is None:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass  # keep Railway deploy logs to what the app itself logs

    return Handler


def start(slides_dir: Path, port: int):
    """Start the file server on a daemon thread. Returns the server instance."""
    slides_dir.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), _make_handler(slides_dir))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Slide file server listening on :%d, serving %s", port, slides_dir)
    return server
