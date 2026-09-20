"""Finding the endpoint a page calls, when its documents are not in the markup.

The plan (docs/plans/09-investigation-framework.md §2) names three shapes a
source comes in. Two are solved: an HTML index of PDF links is `fetch_index`,
and a JSON API we already know about is `jsonapi`. The third is the one that
cost a day by hand:

    a JS shell whose documents are not in the markup

Lok Sabha's questions come from `sansad.in/api_ls/...`. Rajya Sabha's come from
`rsdoc.nic.in/Question/Search_Questions` — same institution, same website,
unrelated host. No amount of pattern-guessing gets from one to the other. Both
were found by loading the page and watching what it called.

**So why is this not a browser.** Because the honest version of "watch the
network" is Playwright plus a Chromium download, and the digger runs on a 945MB
E2.1.Micro under a 256MB cap that already stalls on a 258-page PDF. A component
that cannot run where it is deployed is not a component.

What works without one: the endpoint a page calls is almost always *written
down* in the page, or in the bundle the page loads. Not rendered — written. So
this mines the text for endpoint-shaped strings, probes each one, and keeps the
ones that answer with typed rows. That found the sansad endpoint from its own
markup when tested against it.

Where that is not enough, `browser_watch()` uses Playwright IF it is installed,
and says so plainly when it is not. It never becomes a silent no-op: a scan
that quietly skipped its only capable tier would report "no API here" about a
page whose API it never looked for, which is the precise failure this whole
module exists to stop being invisible.

Both tiers obey robots.txt. An API is a different door into the same building,
not a way around a refusal.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from engine.digger import fetch, robots

log = logging.getLogger("digger.apiscan")

# How many mined candidates are worth probing. Each probe is a request to a
# government server; a page's bundle can mention fifty path-shaped strings and
# most are routes, not endpoints.
MAX_PROBES = 12
# A bundle worth mining. Above this it is a framework, not the site's own code.
MAX_BUNDLE_BYTES = 2_000_000
# Below this an "index" is navigation chrome, the shape that made the RBI
# listing look like a source for weeks (see targets.py).
MIN_ROWS = 3
# Raw-body ceiling. Generous for a bundle, still a bound.
MAX_BYTES = 4_000_000


class _RawFetchError(RuntimeError):
    pass


def _get_raw(url, timeout=30):
    """(body, content_type, final_url) as SERVED — not as extracted.

    `fetch.fetch()` is the wrong tool here and it is worth saying why, because
    reaching for it is the obvious mistake: it returns *extracted text*, and
    extraction strips `<script>`. The endpoint we are hunting is written inside
    a script tag almost every time. Mining fetch()'s output would look like it
    worked and quietly find nothing on exactly the pages this module exists for.

    Everything else about fetch() is still honoured — robots, the shared
    throttle, the same user agent — because being a different reader is no
    excuse for being a ruder one.
    """
    if robots.allowed(url) is False:
        raise _RawFetchError("robots.txt disallows this crawler")
    try:
        robots.check(url)
    except robots.RobotsDenied as e:
        raise _RawFetchError(str(e)) from e
    fetch._throttle(url)
    req = urllib.request.Request(url, headers={"User-Agent": fetch.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES + 1)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            final = resp.geturl()
    except urllib.error.HTTPError as e:
        raise _RawFetchError(f"HTTP {e.code}") from e
    except Exception as e:                                      # noqa: BLE001
        raise _RawFetchError(f"{type(e).__name__}: {e}") from e
    if len(raw) > MAX_BYTES:
        raw = raw[:MAX_BYTES]
    return raw.decode("utf-8", "replace"), ctype, final

# Endpoint-shaped strings, in the order they are worth trusting. A path written
# next to fetch(/axios/ajax is a call; a bare path in a bundle might be a route.
_PATTERNS = (
    r"""fetch\(\s*['"`]([^'"`]{4,200})['"`]""",
    r"""axios\.[a-z]+\(\s*['"`]([^'"`]{4,200})['"`]""",
    r"""\$\.(?:get|post|ajax)\(\s*['"`]([^'"`]{4,200})['"`]""",
    r"""["'](?:url|endpoint|apiUrl|baseURL|api_url|action)["']\s*:\s*['"`]([^'"`]{4,200})['"`]""",
    r"""data-(?:api|url|endpoint)\s*=\s*['"]([^'"]{4,200})['"]""",
    r"""['"`]((?:https?://[^'"`\s]+)?/(?:api|services?|rest|data|json)[^'"`\s]{2,160})['"`]""",
    r"""['"`]([^'"`\s]{2,120}(?:Search|Get|Fetch|List)[A-Za-z_]{2,60}(?:\?[^'"`\s]{0,80})?)['"`]""",
)

# Never probed. Analytics, fonts, maps and social widgets are on every
# government page and none of them serve records.
_JUNK = re.compile(
    r"(google|gstatic|googleapis|facebook|twitter|youtube|linkedin|doubleclick|"
    r"cloudflare|jquery|bootstrap|fontawesome|gtag|analytics|recaptcha|"
    r"\.(?:css|png|jpe?g|gif|svg|woff2?|ttf|ico|map)(?:$|\?))", re.I)


class ApiscanUnavailable(RuntimeError):
    """The browser tier was asked for and is not installed. Raised rather than
    returning empty, because "we looked and found nothing" and "we could not
    look" must never arrive at a caller as the same answer."""


def mine(text, base_url):
    """Endpoint-shaped strings in a page or bundle, best first, deduplicated."""
    seen, out = set(), []
    for pat in _PATTERNS:
        for m in re.finditer(pat, text or ""):
            raw = (m.group(1) or "").strip()
            if not raw or raw.startswith(("data:", "mailto:", "tel:", "#", "javascript:")):
                continue
            if _JUNK.search(raw):
                continue
            url = urljoin(base_url, raw)
            if not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append(url)
    return out


def bundles(html, base_url):
    """Same-origin script URLs worth mining. A CDN's copy of React is not."""
    host = _host(base_url)
    out = []
    for m in re.finditer(r"""<script[^>]+src\s*=\s*['"]([^'"]+)['"]""", html or "", re.I):
        url = urljoin(base_url, m.group(1))
        if _JUNK.search(url):
            continue
        # Same registrable-ish host only. rsdoc.nic.in's bundle is not on
        # sansad.in, but a third-party CDN's bundle never contains OUR endpoint.
        if _host(url) and _host(url).split(".")[-2:] == host.split(".")[-2:]:
            out.append(url)
    return out


def probe(url, timeout=30):
    """Ask one candidate whether it serves typed rows. Never raises.

    Returns an evidence dict. `rows` is what makes this worth keeping: an
    endpoint that answers 200 with an HTML error page is not an endpoint, and
    telling those apart by status code alone is how a dead source gets trusted.
    """
    out = {"url": url, "ok": False, "robots_ok": None, "format": None,
           "rows": 0, "bytes": 0, "error": None}
    try:
        out["robots_ok"] = robots.allowed(url)
    except Exception as e:                                      # noqa: BLE001
        log.debug("robots check failed for %s: %s", url, e)
    if out["robots_ok"] is False:
        out["error"] = "robots.txt disallows this crawler"
        return out
    try:
        body, ctype, _final = _get_raw(url, timeout=timeout)
    except _RawFetchError as e:
        out["error"] = str(e)[:300]
        return out

    out["bytes"] = len(body)
    kind = "json" if "json" in ctype else (
        "xml" if "xml" in ctype else (
            "csv" if "csv" in ctype else None))
    if kind is None:
        kind = _sniff(body)
    out["format"] = kind
    if kind == "json":
        out["rows"] = _json_rows(body)
    elif kind == "xml":
        out["rows"] = len(re.findall(r"<(item|entry|record|row|Question)\b", body, re.I))
    elif kind == "csv":
        out["rows"] = max(0, body.count("\n") - 1)
    else:
        out["error"] = "not a typed response (looks like a page, not records)"
        return out
    out["ok"] = out["rows"] >= MIN_ROWS
    if not out["ok"] and not out["error"]:
        out["error"] = f"answered {kind} but only {out['rows']} row(s)"
    return out


def discover(index_url, max_probes=MAX_PROBES, deep=True):
    """Mine `index_url` (and its own bundles) for endpoints, probe, rank.

    Returns {'endpoints': [evidence...], 'probed': n, 'mined': n, 'error': ...}.
    Endpoints are ranked by rows served, because that is the only signal here
    that is about content rather than about a URL looking plausible.
    """
    out = {"index_url": index_url, "mined": 0, "probed": 0,
           "endpoints": [], "error": None, "browser": None}
    try:
        html, _ctype, _final = _get_raw(index_url)
    except _RawFetchError as e:
        out["error"] = str(e)[:300]
        return out

    cands = mine(html, index_url)
    if deep:
        for b in bundles(html, index_url)[:4]:
            try:
                body, _ct, _fu = _get_raw(b)
            except _RawFetchError as e:
                log.debug("bundle %s unreadable: %s", b, e)
                continue
            if len(body) <= MAX_BUNDLE_BYTES:
                cands.extend(mine(body, index_url))

    seen, ordered = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    out["mined"] = len(ordered)

    for url in ordered[:max_probes]:
        ev = probe(url)
        out["probed"] += 1
        if ev["ok"]:
            out["endpoints"].append(ev)
    out["endpoints"].sort(key=lambda e: -e["rows"])
    return out


def browser_watch(index_url, wait_ms=6000):
    """Load the page in a real browser and report the endpoints it calls.

    This is the tier that would have found `rsdoc.nic.in/Question/
    Search_Questions` from `sansad.in` without anyone watching by hand.

    Raises ApiscanUnavailable when Playwright is not installed — which is the
    normal state on the digger box and a deliberate one. Install it where a
    scout sweep actually runs:  pip install playwright && playwright install
    chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ApiscanUnavailable(
            "playwright is not installed; static mining only. "
            "pip install playwright && playwright install chromium") from e

    if robots.allowed(index_url) is False:
        raise ApiscanUnavailable("robots.txt disallows this crawler")

    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=fetch.USER_AGENT)
            page.on("response", lambda r: calls.append(
                (r.url, (r.headers or {}).get("content-type", ""))))
            page.goto(index_url, wait_until="networkidle", timeout=wait_ms * 5)
            page.wait_for_timeout(wait_ms)
        finally:
            browser.close()

    out = []
    for url, ctype in calls:
        if _JUNK.search(url) or url == index_url:
            continue
        if not any(k in (ctype or "").lower() for k in ("json", "xml", "csv")):
            continue
        out.append(url)
    return list(dict.fromkeys(out))


def describe(result):
    """One-line summary of a discover() result, for a log or a proposal."""
    if result.get("error"):
        return f"FAIL  {result['index_url']}: {result['error']}"
    if not result["endpoints"]:
        return (f"NONE  {result['index_url']}: mined {result['mined']}, "
                f"probed {result['probed']}, none served rows")
    best = result["endpoints"][0]
    return (f"API   {best['url']} — {best['rows']} {best['format']} rows "
            f"(of {result['probed']} probed)")


def _sniff(body):
    s = (body or "").lstrip()[:400]
    if s.startswith(("{", "[")):
        return "json"
    if s.startswith("<?xml") or re.match(r"<(rss|feed|\w+:\w+)\b", s, re.I):
        return "xml"
    if "," in s and "\n" in s and "<" not in s.split("\n")[0]:
        return "csv"
    return None


def _json_rows(body):
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        # The rows are usually one level down, under whatever the site calls
        # them: records, data, result, questions, rows.
        best = 0
        for v in data.values():
            if isinstance(v, list):
                best = max(best, len(v))
            elif isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, list):
                        best = max(best, len(vv))
        return best or (1 if data else 0)
    return 0


def _host(url):
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
