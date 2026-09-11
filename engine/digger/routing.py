"""Getting to a record without bypassing anyone.

An investigation that ends "ask Anil to open it in a browser" is not autonomous
— it just moves the work. But the answer is never to defeat the block: a
publisher who has said no has said no, and a newsroom caught circumventing that
hands every future subject an easy way to dismiss it.

The way out is that "blocked" is four different situations wearing one word,
and three of them have a legitimate door:

1. **robots.txt disallows this host, but a permitted host serves the same
   record.** `rajyasabha.nic.in` and `eparlib.sansad.in` disallow us; `sansad.in`
   serves the same parliamentary questions and permits us. Going to the
   permitted host is not circumvention — it is asking the party that said yes.

   Note *how*, because the obvious method does not work: rewriting the host in
   a URL 404s, since these are different repositories with different path
   schemes (measured 2026-09-10). What works is **search-then-fetch** — search
   engines have already indexed the permitted host's PDFs, so a search returns
   the exact `sansad.in` URL and the fetcher takes it from there. That is how
   Unstarred Question 843 was obtained, with no human step.

2. **An official API exists.** data.gov.in answers `api.data.gov.in` with
   HTTP 400, not 403 — it is talking to us and objecting to the parameters,
   because it wants a registered key. Registering is the *intended* access
   path, the opposite of a bypass. One key, once, then autonomous forever.

3. **JS-rendered with no stated policy.** The page publishes no rule against
   us; it is simply built as an application. Where its own public JSON endpoint
   can be found, that endpoint is the same public data by the same permission.

4. **A WAF fingerprinting the client**, or a CAPTCHA. This is the one with no
   door, and we do not build one. It is recorded as unobtainable-by-us and
   handed to Tier 1's grounded search (which reaches the content through
   indexes the publisher does permit) or to an RTI.

The residual human dependency is therefore one-time setup and acts that are
legally a person's to perform — not a fetch per story.
"""

import os
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# 1. Permitted hosts serving the same record
# ---------------------------------------------------------------------------
#
# VERIFIED mappings only. An unverified rewrite is worse than none: it turns a
# clear "this host disallows us" into a confusing 404 from a host that never had
# the document, and the real reason disappears.
#
# Tested 2026-09-10 and REMOVED because they do not resolve: eparlib.sansad.in
# and cms.rajyasabha.nic.in are DSpace-style repositories serving
# /bitstream/<id>/<n>/<file>.pdf, while sansad.in serves the same questions
# under /getFile/lsapps/loksabhaquestions/annex/<session>/<QNO>_<hash>.pdf. The
# documents are the same; the path schemes are not, and the hash cannot be
# derived. Host rewriting cannot bridge that.
#
# The autonomous path for parliamentary records is therefore SEARCH-THEN-FETCH,
# not path rewriting: a search engine has already indexed the permitted host's
# PDFs, so searching yields the exact sansad.in URL and our fetcher takes it
# from there. That is how Unstarred Question 843 was obtained on 2026-09-10 —
# no human step, and no request to a host that declined us.
#
# Add an entry here only after confirming the rewritten URL actually returns
# the document.
HOST_ALTERNATES = {}


# The SAME host, a different path. Distinct from HOST_ALTERNATES and worth its
# own mechanism: search engines have indexed sansad.in's question PDFs under
# `/getFile/loksabhaquestions/...`, and every one of those URLs now answers
# HTTP 500. The live path carries an `lsapps` segment —
# `/getFile/lsapps/loksabhaquestions/...` — and the same filename and hash
# resolve there immediately.
#
# Measured 2026-09-11 across four sessions (183, 185, 187, 188) and both
# starred and unstarred answers: 500 without the segment, 200 with it, every
# time. This matters more than one broken link, because search-then-fetch (see
# the module docstring) is THE autonomous route to parliamentary records — and
# a 500 reads like "the record is gone" rather than "you asked the old path",
# so without this the whole door looks shut.
PATH_REWRITES = {
    "sansad.in": [("/getFile/loksabhaquestions/", "/getFile/lsapps/loksabhaquestions/")],
}


def path_variants(url):
    """Other paths on the SAME host that may serve this document."""
    p = urlparse(url)
    out = []
    for old, new in PATH_REWRITES.get(p.netloc.lower(), []):
        if old in p.path and new not in p.path:
            out.append(urlunparse((p.scheme, p.netloc, p.path.replace(old, new),
                                   p.params, p.query, "")))
    return out


def alternates(url):
    """Permitted hosts that may serve the same document."""
    host = urlparse(url).netloc.lower()
    out = []
    for alt in HOST_ALTERNATES.get(host, []):
        p = urlparse(url)
        out.append(urlunparse((p.scheme, alt, p.path, p.params, p.query, "")))
    return out


# ---------------------------------------------------------------------------
# 2. Official APIs
# ---------------------------------------------------------------------------
#
# Keys come from the environment, never the repo. A source with no key
# configured is simply not available through this door — it is not an error,
# and it must not read as "the data does not exist".

API_KEYS = {
    # https://data.gov.in — free registration, one key, used forever after.
    "data.gov.in": "DATA_GOV_IN_API_KEY",
}


def api_key_for(url):
    var = API_KEYS.get(urlparse(url).netloc.lower().replace("api.", ""))
    return os.environ.get(var, "") if var else ""


def with_api_key(url):
    """Append the registered key if we hold one. Returns (url, have_key)."""
    key = api_key_for(url)
    if not key:
        return url, False
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}api-key={key}&format=json", True


def missing_api_keys():
    """Sources that would open with a key we do not have.

    Surfaced deliberately: this is the entire remaining human dependency for
    these hosts, it is a few minutes once, and it should be visible rather than
    quietly degrading into 'that source never returns anything'.
    """
    return sorted(host for host, var in API_KEYS.items() if not os.environ.get(var))


# ---------------------------------------------------------------------------
# 3/4. What to do when there is no door
# ---------------------------------------------------------------------------

HANDOFF_TIER1 = ("Tier 1 grounded search — the content is reachable through "
                 "indexes the publisher permits, even where our fetcher is not")
HANDOFF_RTI = ("an RTI request — the record is not published at all, and asking "
               "for it is the designed route, not a workaround")
HANDOFF_API = ("register for the source's official API key — the intended "
               "access path; one-time setup, then autonomous")


def handoff_for(reason):
    """What could still obtain a record we could not reach.

    Pairs with shared.evidence.Stop: a non-conclusive stop must carry what
    would still get the evidence, or it is an abandonment rather than a
    handoff.
    """
    return {
        "robots": ("search for the same record on a permitted host, then fetch "
                   "that URL — host rewriting does not work across repositories"),
        "api_key": HANDOFF_API,
        "js": HANDOFF_TIER1,
        "waf": HANDOFF_TIER1,
        "captcha": HANDOFF_TIER1,
        "unpublished": HANDOFF_RTI,
    }.get(reason, HANDOFF_TIER1)


def classify(error_text):
    """Best-effort reason from a FetchError, so the right door gets tried."""
    e = (error_text or "").lower()
    if "robots.txt disallows" in e:
        return "robots"
    if "bot detection" in e:
        return "captcha"
    if "http 403" in e:
        return "waf"
    if "no document links" in e or "no extractable text" in e:
        return "js"
    if "http 400" in e:
        return "api_key"
    return "waf"
