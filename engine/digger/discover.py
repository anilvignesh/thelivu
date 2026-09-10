"""Validating candidate record-sources before they reach the rotation.

`source-scout` already nominates sources and stops there, on the reasoning that
a bad story gets caught at the verification gate but a bad *source*, once
trusted, quietly shapes every story that flows through it. That rule applies
harder here: this tier reads whatever a source serves, unattended, hourly.

So a proposal is never activated by machine. What this module does is gather the
evidence a person needs to decide:

  * does robots.txt permit us,
  * does the index actually fetch,
  * does it yield document links (an index that yields none is a dead end,
    which is exactly how the RBI listing looked before we understood it),
  * does a sample document parse, and in what format,
  * is there a bot wall behind it.

A candidate that fails is still recorded, with the reason. "We tried this and it
refuses us" is worth keeping — otherwise the next scout run proposes it again.
"""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from engine.digger import fetch, robots

log = logging.getLogger("digger.discover")

MIN_DOC_LINKS = 3


def slugify(url, name=None):
    """A stable key for a target. Host-based, because that is what actually
    identifies a source; the path may be paginated or reorganised."""
    base = (name or urlparse(url).netloc or url).lower()
    base = re.sub(r"^www\.", "", base)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:60] or "source"


def validate(index_url, link_pattern=None, brief=None, fetch_sample=True):
    """Probe a candidate index. Returns an evidence dict; never raises."""
    out = {
        "index_url": index_url,
        "robots_ok": None,
        "fetch_ok": False,
        "doc_links": 0,
        "sample_url": None,
        "doc_format": None,
        "validation_error": None,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
    }

    # 1. Permission first. Probing a source that has asked us not to would be
    #    the same discourtesy as crawling it.
    try:
        out["robots_ok"] = robots.allowed(index_url)
    except Exception as e:
        out["robots_ok"] = None
        log.warning("robots check failed for %s: %s", index_url, e)
    if out["robots_ok"] is False:
        out["validation_error"] = "robots.txt disallows this crawler"
        return out

    # 2. Does the index yield documents?
    try:
        items = fetch.fetch_index(index_url, link_pattern)
        out["fetch_ok"] = True
        out["doc_links"] = len(items)
    except fetch.FetchError as e:
        out["validation_error"] = str(e)[:400]
        return out
    except Exception as e:
        out["validation_error"] = f"{type(e).__name__}: {e}"[:400]
        return out

    if out["doc_links"] < MIN_DOC_LINKS:
        out["validation_error"] = (
            f"index yielded only {out['doc_links']} document link(s); "
            "likely a JS-rendered listing or the wrong URL"
        )
        return out

    # 3. Can we actually read one of its documents? An index full of links we
    #    cannot parse is not a usable source, and finding that out now is much
    #    cheaper than discovering it in production every hour.
    if fetch_sample:
        for item in items[:3]:
            try:
                doc = fetch.fetch(item["url"])
            except fetch.FetchError as e:
                out["validation_error"] = str(e)[:400]
                continue
            out["sample_url"] = doc["final_url"]
            out["doc_format"] = fetch._looks_like(
                doc["text"], doc["content_type"], doc["final_url"]
            ) if doc["content_type"] else "unknown"
            if "pdf" in (doc["content_type"] or ""):
                out["doc_format"] = "pdf"
            out["validation_error"] = None
            out["ok"] = True
            break
        else:
            return out
    else:
        out["ok"] = True

    return out


def propose(index_url, name, brief, link_pattern=None, key=None,
            proposed_by="scout", persist=True):
    """Validate a candidate and record it as `proposed` (never active)."""
    from shared import db

    ev = validate(index_url, link_pattern, brief)
    key = key or slugify(index_url, name)
    if persist:
        db.propose_digger_target(
            key=key, name=name, index_url=index_url, brief=brief,
            link_pattern=link_pattern, proposed_by=proposed_by,
            robots_ok=ev["robots_ok"], fetch_ok=ev["fetch_ok"],
            doc_links=ev["doc_links"], sample_url=ev["sample_url"],
            doc_format=ev["doc_format"],
            validation_error=ev["validation_error"],
            validated_at=ev["validated_at"],
        )
    ev["key"] = key
    return ev


def describe(ev):
    """One-line human summary of a validation result."""
    if ev.get("ok"):
        return (f"OK    {ev['key']:24s} {ev['doc_links']:3d} links, "
                f"sample parses as {ev.get('doc_format')}")
    reason = ev.get("validation_error") or "unknown"
    return f"FAIL  {ev.get('key', '?'):24s} {reason[:90]}"
