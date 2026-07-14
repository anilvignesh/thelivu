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
import threading
from pathlib import Path

log = logging.getLogger("fileserver")


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
                self.end_headers()
                self.wfile.write(page)
                return
            # Bare filename only, inside slides_dir — no path traversal, no
            # directory listing, nothing else on disk is reachable.
            if "/" in name or ".." in name or not name.endswith(".png"):
                self.send_response(404)
                self.end_headers()
                return
            path = slides_dir / name
            if not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

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
