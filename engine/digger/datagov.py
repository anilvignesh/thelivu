"""data.gov.in — structured government data through the sanctioned door.

The Open Government Data platform answers `api.data.gov.in` with HTTP 400 to an
unkeyed request, not 403: it is talking to us and objecting to the parameters.
Registering for a key is the *intended* access path, and one key obtained once
makes ~287,000 resources queryable forever after. Its HTML catalog 403s our
fetcher, so for a long time this looked like a closed source. It was not; we
were knocking on the wrong door.

Why this matters more than another scraper: these are **tables, not prose**. A
scraped page gives a model text to read and possibly misread. A resource here
gives typed rows, which can be counted, normalised and compared without a model
touching them at all. The first use proved the point — the claim that Kerala is
the country's worst state for highway failures rested on an unnormalised
incident count, and two resources here (projects vs delayed projects, damaged NH
length by state) put it 23rd of 26 on delay rate and 15th of 30 on damage. That
correction came from arithmetic on primary rows, not from a better prompt.

Endpoints, established by probing 2026-09-10:

  * `/lists` — the discovery endpoint. 287,810 resources, `filters[title]=`
    narrows it, `sort[updated_date]=desc` finds what is fresh. NOT `/catalog`,
    `/search` or `/resources`, all of which 404.
  * `/resource/<index_name>` — the rows.

`filters[title]` matches loosely and appears to OR its terms: "national highway
penalty" returns 2,843 because it matches "national" alone. Two or three
distinctive words together ("highway structural", 79 results) is what actually
narrows it.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.data.gov.in"
USER_AGENT = "ThelivuDigger (+https://thelivu.com)"
TIMEOUT = 30
KEY_VAR = "DATA_GOV_IN_API_KEY"


class DataGovError(RuntimeError):
    pass


def api_key():
    key = os.environ.get(KEY_VAR, "")
    if not key:
        raise DataGovError(
            f"{KEY_VAR} is not set. Register once at data.gov.in — the key is "
            "the platform's intended access path, and without it the HTML "
            "catalog is the only route and it refuses automated clients."
        )
    return key


def _get(path, **params):
    params.update({"api-key": api_key(), "format": "json"})
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 400:
            raise DataGovError("HTTP 400 — the API rejected the parameters; "
                               "usually a bad or missing key") from e
        raise DataGovError(f"HTTP {e.code} from {path}") from e
    except Exception as e:
        raise DataGovError(f"{type(e).__name__}: {e}") from e


def search(title, limit=20, newest_first=True):
    """Find resources whose title matches. Returns [{id, title, updated, source}].

    Use two or three distinctive words together. `filters[title]` ORs its terms,
    so a single common word ("national") matches thousands and tells you
    nothing.
    """
    params = {"limit": limit, "filters[title]": title}
    if newest_first:
        params["sort[updated_date]"] = "desc"
    body = _get("lists", **params)
    return [{
        "id": r.get("index_name"),
        "title": (r.get("title") or "").strip(),
        "updated": (r.get("updated_date") or "")[:10],
        "source": r.get("source") or "",
        "org_type": r.get("org_type") or "",
    } for r in (body.get("records") or []) if r.get("index_name")]


def resource(resource_id, limit=200, offset=0):
    """The rows of one resource, as dicts."""
    body = _get(f"resource/{resource_id}", limit=limit, offset=offset)
    return body.get("records") or []


def resource_all(resource_id, page=500, cap=5000):
    """Every row, paged. `cap` exists because this runs on a 945MB box and an
    unbounded fetch is how that box dies."""
    out, offset = [], 0
    while len(out) < cap:
        chunk = resource(resource_id, limit=page, offset=offset)
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    return out[:cap]


def to_number(value):
    """Government tables carry numbers as strings, with commas, and use '0',
    '-' and 'NA' interchangeably for nothing. Returns None for genuinely absent
    values rather than 0 — a state with no data is not a state with a zero, and
    averaging those together is how a table lies."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "NA", "N/A", "na", "nil", "Nil"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def rate_table(records, key_field, numerator, denominator, min_denominator=1):
    """(key, numerator, denominator, rate%) sorted by rate, descending.

    The single most useful operation on this data, and the one the story needed:
    a raw count ranks by size, a rate ranks by performance, and conflating them
    is the error that put Kerala top of a list it is near the bottom of.

    Rows with a missing or too-small denominator are EXCLUDED, not zeroed — a
    state with two projects and one delay is not the worst performer in India.
    """
    out = []
    for r in records:
        k = (r.get(key_field) or "").strip()
        n, d = to_number(r.get(numerator)), to_number(r.get(denominator))
        if not k or n is None or d is None or d < min_denominator or d == 0:
            continue
        out.append((k, n, d, n / d * 100.0))
    return sorted(out, key=lambda x: -x[3])
