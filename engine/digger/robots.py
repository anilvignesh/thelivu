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
_CACHE_TTL = 3600
_FETCH_TIMEOUT = 15


class RobotsDenied(RuntimeError):
    pass


def _robots_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "/robots.txt", "", "", ""))


def _load(robots_url):
    """Fetch and parse one robots.txt. Returns (parser, denied_outright)."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    req = urllib.request.Request(
        robots_url, headers={"User-Agent": f"{USER_AGENT} (+https://thelivu.com)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            body = resp.read(500_000).decode("utf-8", errors="replace")
        rp.parse(body.splitlines())
        return rp, False
    except urllib.error.HTTPError as e:
        # RFC 9309: 4xx is "unavailable" -> no rules -> allowed. 5xx is
        # "unreachable" -> the server is struggling -> stay off it.
        return None, 500 <= e.code < 600
    except Exception:
        # Network failure. Same reasoning as 5xx: if we cannot even reach
        # robots.txt, we are in no position to start crawling the site.
        return None, True


def _parser_for(url):
    robots_url = _robots_url(url)
    hit = _CACHE.get(robots_url)
    now = time.time()
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1], hit[2]
    rp, denied = _load(robots_url)
    _CACHE[robots_url] = (now, rp, denied)
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
