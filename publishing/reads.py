"""Counting who reads the articles, without learning who they are.

The engine has measured its own production in obsessive detail since day one —
cost per skill, tokens per cycle, gate verdicts, cache hit rates — and its
readership not at all. Every piece published since the Telegraph switch has been
read an unknown number of times, including possibly zero. This is the smallest
honest thing that fixes that.

Three constraints shaped all of it (docs/reach-analytics.md §3):

**Privacy, because this is a journalism project.** No third party, no cookie, no
JavaScript beacon, no IP or user-agent stored. A reader is a
`sha256(ip + ua + today's salt)`, and the salt is a random value regenerated
every UTC day and never written down. So "how many different people read this
today" is answerable and "did this person come back on Thursday" is
**unanswerable by construction**, which is a stronger promise than a policy.

**Bots are counted, not dropped.** A large share of `/a/` traffic is Telegram's
link-unfurler, `facebookexternalhit` and search crawlers. Counting those as
readers would inflate the numbers in the flattering direction, which is the
worst way for a verification-first project to be wrong. They are classified and
kept, so the ratio is visible rather than assumed.

**Analytics must never slow down or break the page.** The fileserver is a
BaseHTTPRequestHandler and the DB is Railway Postgres at 0.25-1s per round trip.
An inline INSERT would put that in front of every article read. So: a bounded
queue and one background writer. If the queue is full the read is dropped rather
than blocking a reader, and a restart loses whatever is still in it — these
counts are a good measure, never an exact one, and nothing downstream should
present them as exact.
"""
import hashlib
import logging
import os
import queue
import re
import threading
from datetime import datetime, timezone

log = logging.getLogger("reads")

# Bounded on purpose. Unbounded would turn a DB outage into a memory leak in the
# process that serves the public site; past this depth the honest move is to
# lose analytics rather than degrade the thing being measured.
MAX_QUEUE = 2000

# How many rows one wake-up drains. Each batch is one round trip, and the writer
# is never the bottleneck at our traffic — this exists so a burst (a post going
# out to the channel) does not become a few hundred sequential inserts.
BATCH = 50
IDLE_SECONDS = 5.0

_q = queue.Queue(maxsize=MAX_QUEUE)
_writer = None
_lock = threading.Lock()

# Substrings that mark a non-human fetch, lowercased. Deliberately broad: the
# cost of misfiling a crawler as a reader is a number that flatters us, and the
# cost of the reverse is a number that does not. When unsure, not a reader.
_BOT_MARKERS = (
    "bot", "crawl", "spider", "slurp", "preview", "fetcher", "monitor",
    "facebookexternalhit", "telegrambot", "whatsapp", "curl", "wget",
    "python-requests", "httpx", "okhttp", "go-http-client", "java/",
    "headlesschrome", "lighthouse", "pingdom", "uptime", "scraper",
)

_salt_day = None
_salt = None


def _daily_salt():
    """A random salt, regenerated each UTC day and never persisted.

    This is the whole privacy design in four lines. Yesterday's salt is gone the
    moment the day turns, so yesterday's hashes cannot be recomputed from a new
    request — even by us, even with the raw IP in hand.
    """
    global _salt_day, _salt
    today = datetime.now(timezone.utc).date()
    if _salt_day != today:
        _salt_day, _salt = today, os.urandom(16)
    return _salt


def is_bot(user_agent):
    ua = (user_agent or "").lower()
    if not ua:
        # No UA at all is a script, not a browser. Every real browser sends one.
        return True
    return any(m in ua for m in _BOT_MARKERS)


def visitor_hash(ip, user_agent):
    h = hashlib.sha256()
    h.update(_daily_salt())
    h.update((ip or "").encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update((user_agent or "").encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def referrer_host(referrer):
    """Host only. A full referrer can carry a search query — that is content
    about the reader, and we have no business keeping it."""
    if not referrer:
        return None
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)", referrer.strip())
    host = (m.group(1) if m else referrer.strip().split("/")[0]).lower()
    host = host.split("@")[-1].split(":")[0]
    return host[:120] or None


def record(slug, *, run_id=None, ip=None, user_agent=None, referrer=None):
    """Queue one read. Never raises, never blocks — see the module docstring."""
    try:
        _ensure_writer()
        _q.put_nowait((slug[:300], run_id, is_bot(user_agent),
                       visitor_hash(ip, user_agent), referrer_host(referrer),
                       datetime.now(timezone.utc)))
    except queue.Full:
        log.warning("read queue full — dropping a read for %s", slug[:60])
    except Exception as e:
        log.warning("could not queue a read for %s: %s", slug[:60], e)


def _ensure_writer():
    global _writer
    if _writer and _writer.is_alive():
        return
    with _lock:
        if _writer and _writer.is_alive():
            return
        _writer = threading.Thread(target=_run_writer, name="page-reads",
                                   daemon=True)
        _writer.start()


def _drain(limit=BATCH):
    rows = []
    while len(rows) < limit:
        try:
            rows.append(_q.get_nowait())
        except queue.Empty:
            break
    return rows


def _run_writer():
    while True:
        try:
            first = _q.get(timeout=IDLE_SECONDS)
        except queue.Empty:
            continue
        rows = [first] + _drain(BATCH - 1)
        try:
            _insert(rows)
        except Exception as e:
            # Deliberately not requeued. A failing DB plus a retry loop is how an
            # analytics writer turns into a busy loop against a database the
            # actual publishing path also needs.
            log.warning("dropped %d read(s): %s", len(rows), e)


def _insert(rows):
    from shared.db import _conn, _is_postgres

    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.executemany(
            f"INSERT INTO page_reads "
            f"(slug, run_id, is_bot, visitor_hash, referrer_host, read_at) "
            f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def flush(timeout=10.0):
    """Block until the queue drains. For tests and shutdown, not the hot path."""
    _ensure_writer()
    deadline = datetime.now(timezone.utc).timestamp() + timeout
    while not _q.empty() and datetime.now(timezone.utc).timestamp() < deadline:
        threading.Event().wait(0.05)
    threading.Event().wait(0.2)
