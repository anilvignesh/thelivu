"""robots.txt compliance for the Tier-0 fetcher.

Not optional, and more so once the scout starts proposing sources nobody has
looked at by hand. An unattended process fetching government sites hourly is a
crawler, and a crawler that ignores robots.txt is misbehaving regardless of
whether anyone notices. RBI already answers automated requests with a CAPTCHA
(see fetch._reject_if_bot_wall) — that is what a publisher does when asking
politely has stopped working.

Failure policy follows RFC 9309 §2.3.1:

  * 4xx on robots.txt  -> "unavailable", no rules published, access ALLOWED.
  * 5xx / network error -> "unreachable", the server is in trouble, DISALLOWED
    until it recovers, because hammering a struggling site is the specific harm
    robots.txt exists to prevent.

An earlier version here treated 401/403 as a deliberate gate and refused. That
was stricter than the standard and wrong in practice: data.gov.in answers
robots.txt with 403 to a non-browser client while being India's Open Government
Data platform, whose whole purpose is public distribution. A WAF fingerprinting
the client is not the publisher stating a policy.

The real protection against a site that genuinely refuses is not this module but
fetch._reject_if_bot_wall — a CAPTCHA in the response body is an unambiguous
"no", and it is checked on every fetch.
"""

import logging
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse, urlunparse

# The digger identifies itself honestly. A crawler that hides behind a browser
# UA cannot be excluded by a publisher who wants to exclude it, which defeats
# the point of reading robots.txt at all.
USER_AGENT = "ThelivuDigger"

_CACHE = {}
log = logging.getLogger("digger.robots")

_CACHE_TTL = 3600
# A TRANSIENT denial is cached for a minute, not an hour.
#
# Found 2026-09-23: cag-rajasthan came back from a whole backfill with zero
# documents and three failures. It was not refusing us — cag.gov.in serves no
# robots.txt at all (404 on ten consecutive fetches), which per RFC 9309 §2.3.1
# means allowed. But when that request fails at the NETWORK level instead of
# returning 404, `_load` fell to its generic except, reported denied, and
# `_parser_for` cached that under the HOST's robots.txt key for an hour. One
# flake therefore blanked every target on cag.gov.in — reproduced offline
# against rajasthan, kerala and gujarat at once, and live across two processes
# minutes apart.
#
# The policy is unchanged and is not the bug: if we cannot reach robots.txt we
# are in no position to crawl. Treating one dropped packet as an hour-long
# refusal is the bug, and it is indistinguishable at the call site from a site
# that really did say no.
_TRANSIENT_TTL = 60
# One retry before concluding the network is the answer.
_RETRIES = 1
_RETRY_PAUSE = 1.5
_FETCH_TIMEOUT = 15


class RobotsDenied(RuntimeError):
    pass


def _robots_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "/robots.txt", "", "", ""))


def _load(robots_url):
    """Fetch and parse one robots.txt.

    Returns (parser, denied_outright, transient) — `transient` says whether a
    denial is the site's answer or merely today's weather, so the caller can
    decide how long to believe it.
    """
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    req = urllib.request.Request(
        robots_url, headers={"User-Agent": f"{USER_AGENT} (+https://thelivu.com)"}
    )
    last = None
    for attempt in range(_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                body = resp.read(500_000).decode("utf-8", errors="replace")
            rp.parse(body.splitlines())
            return rp, False, False
        except urllib.error.HTTPError as e:
            # RFC 9309: 4xx is "unavailable" -> no rules -> allowed. 5xx is
            # "unreachable" -> the server is struggling -> stay off it, and that
            # IS the server talking, so it is not transient.
            return None, 500 <= e.code < 600, False
        except Exception as e:                              # noqa: BLE001
            last = e
            if attempt < _RETRIES:
                time.sleep(_RETRY_PAUSE)
    # Network failure, twice. Same reasoning as 5xx — if we cannot even reach
    # robots.txt we are in no position to start crawling — but flagged
    # transient, so one bad minute does not cost an hour of the whole host.
    log.debug("robots.txt unreachable at %s: %s", robots_url, last)
    return None, True, True


def _parser_for(url):
    robots_url = _robots_url(url)
    hit = _CACHE.get(robots_url)
    now = time.time()
    if hit:
        ttl = _TRANSIENT_TTL if (len(hit) > 3 and hit[3]) else _CACHE_TTL
        if now - hit[0] < ttl:
            return hit[1], hit[2]
    rp, denied, transient = _load(robots_url)
    _CACHE[robots_url] = (now, rp, denied, transient)
    return rp, denied


def allowed(url, user_agent=USER_AGENT):
    """True if robots.txt permits fetching `url`."""
    try:
        rp, denied = _parser_for(url)
    except Exception:
        return True
    if denied:
        return False
    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def check(url, user_agent=USER_AGENT):
    """Raise RobotsDenied if the URL is disallowed. Call before fetching."""
    if not allowed(url, user_agent):
        raise RobotsDenied(
            f"robots.txt disallows {user_agent} at {url}. This source has asked "
            "not to be crawled; that is a decision to respect, not route around."
        )


def crawl_delay(url, user_agent=USER_AGENT, default=0.0):
    """Publisher-requested delay between requests, if any."""
    try:
        rp, _ = _parser_for(url)
        if rp is None:
            return default
        d = rp.crawl_delay(user_agent)
        return float(d) if d else default
    except Exception:
        return default


def reset_cache():
    _CACHE.clear()
