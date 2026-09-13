"""Keep the document, not just the link.

Until 2026-09-13 a published Thelivu figure was backed by a URL and a short
verbatim quote. The document itself was fetched, read, and dropped. That is a
real exposure for an operation whose whole claim is that it runs on facts: if a
figure is challenged six months after publication and the source 404s, we have
an assertion and nothing behind it.

It is not hypothetical. sansad.in silently moved
/getFile/loksabhaquestions/ to /getFile/lsapps/loksabhaquestions/ and the old
URLs started returning 500 (see engine/digger/routing.py). We recovered because
somebody wrote a rewrite rule, not because we held the file. CAG reorganises
regularly. Government PDFs are not permanent and nobody promised they would be.

THE CAPTURE HAPPENS AT READ TIME. This is the entire design constraint. A
puller that re-downloads later is not an archive — by the time a URL rots, the
re-download fails too, and the only moment we are certain to hold the bytes is
the moment we read them. So the digger spools every document it fetches to its
own disk (26GB free) and the laptop drains that spool into permanent storage
(383GB free). The 945MB VM never has to hold the collection, only the last few
hours of it.

Content-addressed by sha256, for two reasons that matter more than the space
saved by dedup: the same document fetched from two URLs is stored once, and the
hash recorded next to a published claim is a check anyone can run against the
file we say we read.

Stdlib only, deliberately — this module is imported by engine/digger/fetch.py,
which runs on a box with psycopg2 and liteparse and nothing else.
"""

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("archive")

# Don't spool a document larger than this. Nothing in the public record we read
# is near it; a 200MB response is a mistake, and the digger's disk is shared
# with the OS.
MAX_SPOOL_BYTES = 64 * 1024 * 1024

# Stop spooling when the spool grows past this. The laptop drains it; if the
# laptop has been off for a week the digger must degrade to today's behaviour
# (read and drop) rather than filling the disk of a box that also runs
# freellmapi and sshd. Losing an archive copy is bad. Wedging the VM is worse —
# that already happened once, on 2026-09-10, via a docker pull.
MAX_SPOOL_BYTES_TOTAL = 4 * 1024 * 1024 * 1024

USER_AGENT = "ThelivuArchive/1.0 (+https://thelivu.in)"

_EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/json": ".json",
    "text/csv": ".csv",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/plain": ".txt",
}


def digest(data):
    """sha256 of the raw bytes, as hex."""
    return hashlib.sha256(data).hexdigest()


def extension_for(content_type):
    base = (content_type or "").split(";")[0].strip().lower()
    return _EXTENSIONS.get(base, ".bin")


# --------------------------------------------------------------------------
# Spool — the digger side. Write-only, drained by the laptop.
# --------------------------------------------------------------------------

def spool_dir():
    """Where the digger parks documents until the laptop collects them.

    STATE_DIRECTORY is set by systemd's StateDirectory= (/var/lib/thelivu). It
    is used in preference to anything hand-rolled because systemd creates it
    with the right owner AND the right SELinux label, which on this Enforcing
    box is the difference between a working service and a bare "Permission
    denied" (2026-09-10).
    """
    env = os.environ.get("THELIVU_SPOOL") or os.environ.get("STATE_DIRECTORY")
    base = Path(env) if env else Path.home() / ".thelivu"
    return base / "spool"


def spool_size():
    d = spool_dir()
    if not d.is_dir():
        return 0
    return sum(f.stat().st_size for f in d.iterdir() if f.is_file())


def spool(data, url, final_url=None, content_type=None, fetched_at=None,
          ocr_used=False):
    """Park one fetched document. Returns its sha256, or None if not spooled.

    NEVER RAISES. Archiving is a second thing we do with a permitted fetch, not
    a precondition for reading it — a full disk or a bad path must not turn a
    working dig into a failed cycle. Every miss is logged, because an archive
    that quietly stops archiving is worse than no archive at all.
    """
    try:
        sha = digest(data)
        if len(data) > MAX_SPOOL_BYTES:
            log.warning("not archiving %s: %.1fMB exceeds the %dMB spool limit",
                        url[:80], len(data) / 1e6, MAX_SPOOL_BYTES // (1024 * 1024))
            return sha

        d = spool_dir()
        d.mkdir(parents=True, exist_ok=True)
        blob = d / f"{sha}{extension_for(content_type)}"
        if blob.exists():
            return sha           # same document, already waiting to be collected

        if spool_size() > MAX_SPOOL_BYTES_TOTAL:
            log.warning("spool is over %dGB and not being drained — not archiving %s",
                        MAX_SPOOL_BYTES_TOTAL // (1024 ** 3), url[:80])
            return sha

        # Write to a temp name and rename: the laptop drains this directory
        # concurrently, and a half-written file whose name is a hash of its
        # finished contents is precisely the corruption content-addressing is
        # supposed to make impossible.
        tmp = blob.with_suffix(blob.suffix + ".part")
        tmp.write_bytes(data)
        meta = {
            "sha256": sha,
            "url": url,
            "final_url": final_url or url,
            "content_type": content_type,
            "byte_size": len(data),
            "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
            "ocr_used": bool(ocr_used),
            "filename": blob.name,
        }
        blob.with_suffix(blob.suffix + ".json").write_text(
            json.dumps(meta, indent=2))
        tmp.rename(blob)
        return sha
    except Exception as e:                                  # noqa: BLE001
        log.warning("could not archive %s: %s", (url or "?")[:80], e)
        return None


def spooled():
    """Every complete document waiting to be collected, as (blob, meta) pairs."""
    d = spool_dir()
    if not d.is_dir():
        return []
    out = []
    for blob in sorted(d.iterdir()):
        if blob.suffix in (".json", ".part"):
            continue
        side = blob.with_suffix(blob.suffix + ".json")
        if not side.exists():
            continue
        try:
            out.append((blob, json.loads(side.read_text())))
        except (OSError, ValueError) as e:
            log.warning("skipping malformed spool entry %s: %s", blob.name, e)
    return out


def drop_spooled(blob):
    """Remove a document from the spool once it is safely stored elsewhere."""
    for p in (blob, blob.with_suffix(blob.suffix + ".json")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------
# Archive — the laptop side. Permanent.
# --------------------------------------------------------------------------

def archive_dir():
    return Path(os.environ.get("THELIVU_ARCHIVE",
                               os.path.expanduser("~/thelivu-archive")))


def path_for(sha, content_type=None, ext=None):
    """Two-level fan-out on the hash prefix.

    Not cosmetic: this will hold tens of thousands of files and a single flat
    directory makes `ls` and every backup tool progressively slower.
    """
    return archive_dir() / sha[:2] / sha[2:4] / f"{sha}{ext or extension_for(content_type)}"


def store(data, meta):
    """Put one document into permanent storage. Returns its path.

    Verifies the hash before writing. A document whose bytes do not match the
    name it arrived under is not stored: the point of the archive is that the
    file can be checked against the claim, and a copy we cannot vouch for
    undermines that rather than supporting it.
    """
    sha = digest(data)
    if meta.get("sha256") and meta["sha256"] != sha:
        raise ValueError(
            f"hash mismatch: spooled as {meta['sha256'][:12]}, "
            f"bytes are {sha[:12]} — refusing to store")
    dest = path_for(sha, meta.get("content_type"),
                    ext=os.path.splitext(meta.get("filename", ""))[1] or None)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.rename(dest)
    side = dest.with_suffix(dest.suffix + ".json")
    if not side.exists():
        side.write_text(json.dumps({**meta, "sha256": sha,
                                    "stored_at": datetime.now(timezone.utc).isoformat()},
                                   indent=2))
    return dest


def held(sha, content_type=None, ext=None):
    return path_for(sha, content_type, ext).exists()


# --------------------------------------------------------------------------
# Wayback — the copy we do not host.
# --------------------------------------------------------------------------

def wayback_save(url, timeout=30):
    """Ask the Internet Archive to snapshot a URL. Returns the snapshot URL or None.

    Our own copy proves what we read. This proves it to someone who does not
    trust us — an independently hosted, timestamped capture, citable in the
    description and outliving Thelivu. It is the same thing ICIJ and Bellingcat
    lean on, and it costs one HTTP call.

    Never raises. The save endpoint is slow, rate-limited, and frequently times
    out while still completing the capture server-side, so a failure here means
    "no URL to cite yet", not "no snapshot".
    """
    try:
        req = urllib.request.Request(
            "https://web.archive.org/save/" + url,
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
            if "/web/" in final:
                return final
            loc = resp.headers.get("Content-Location")
            if loc:
                return "https://web.archive.org" + loc
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, OSError, ValueError) as e:
        log.info("wayback save deferred for %s: %s", url[:80], e)
    return None


def wayback_lookup(url, timeout=15):
    """The most recent existing snapshot, if there is one. Returns a URL or None.

    Tried before asking for a new capture: many government documents are
    already in the Archive, and a snapshot from before we touched the page is
    better evidence than one we triggered ourselves.
    """
    try:
        api = ("https://archive.org/wayback/available?url="
               + urllib.parse.quote(url, safe=""))
        req = urllib.request.Request(api, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        snap = (body.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            return snap["url"]
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, OSError, ValueError) as e:
        log.info("wayback lookup failed for %s: %s", url[:80], e)
    return None


import urllib.parse  # noqa: E402  (used by wayback_lookup)
