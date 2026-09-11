"""Finding real photographs we are actually allowed to publish.

Anil, 2026-09-11: *"can we use images from google? like find related images and
show them? or will that be a risk... if we can properly and safely execute it,
it would be great."*

**Google Images is not a source.** It is an index of other people's copyrighted
photographs, and it returns them without a licence, without an author, and
without any assertion about what the picture shows. Taking one because it
appeared in a search is the same act as taking a news clip because it was on
Twitter — see BRAND.md. The risk is not theoretical: a photograph is the easiest
thing in the world for its owner to find later.

What IS safe is a search restricted to repositories that publish a **licence and
an author as structured data**, so the permission arrives with the file rather
than being assumed. That is a real capability and this is it.

  Wikimedia Commons   public API, no key. Every file carries machine-readable
                      `extmetadata`: LicenseShortName, UsageTerms, Artist,
                      Credit, DateTimeOriginal. The licences are CC-BY, CC-BY-SA,
                      CC0 or public domain — all of which attribution satisfies.

Two things this deliberately does NOT do.

It does not decide whether the picture shows what the script says it shows. A
correctly licensed photograph of the wrong flyover is still a false claim, and
no search API can tell you it is the wrong flyover. Candidates go to gate 1 with
their captions and the human confirms. That is the same split as everywhere else
here: the machine establishes what is permitted, a person establishes what is
true.

And it does not silently accept a licence it does not recognise. Commons hosts
some fair-use and restricted files; `usable()` names the licences that
attribution settles and refuses the rest rather than guessing.
"""

import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger("photos")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "ThelivuDigger (+https://thelivu.com)"
TIMEOUT = 30

# Licences where crediting the author IS the permission. Anything not on this
# list is refused rather than guessed at — Commons also hosts fair-use and
# non-commercial files, and "probably fine" is not a licence.
OPEN_LICENCES = (
    "cc0", "cc-zero", "public domain", "pd-", "cc by", "cc-by",
    "cc by-sa", "cc-by-sa", "godl", "ogl",
)
# Explicitly refused even though they look open. NonCommercial and NoDerivatives
# both bite: the channel carries ads, and every frame here is cropped or
# composited onto the house ground.
REFUSED = ("nc", "noncommercial", "nd", "noderiv")


def usable(licence):
    """(ok, why). Attribution settles the listed licences and nothing else."""
    lic = (licence or "").strip().lower()
    if not lic:
        return False, "no licence stated"
    tokens = re.split(r"[^a-z0-9]+", lic)
    if any(t in REFUSED for t in tokens):
        return False, (f"{licence} carries a NonCommercial or NoDerivatives "
                       f"term — the channel carries ads and every frame is "
                       f"composited, so both are breached")
    if any(tok in lic for tok in OPEN_LICENCES):
        return True, ""
    return False, f"{licence} is not a licence attribution alone settles"


def _get(params):
    params = {**params, "format": "json", "formatversion": "2"}
    url = f"{COMMONS_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    import json
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def search(query, limit=8, min_width=900):
    """Licensed photographs matching `query`. Returns a list of candidates.

    Each is {title, url, thumb, licence, author, credit, date, description,
    width, height} — everything a human needs to judge it and everything the
    renderer needs to attribute it. Unusable licences are dropped here, with the
    reason logged, so a caller never has to remember to check.

    `min_width` exists because a 400px file upscaled to a 1920-wide frame looks
    like a mistake. Commons has plenty that are big enough.
    """
    try:
        body = _get({
            "action": "query", "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": "6", "gsrlimit": str(max(limit * 3, 12)),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": "1600",
        })
    except Exception as e:
        log.warning("Commons search failed for %r: %s", query, e)
        return []

    out = []
    for page in (body.get("query", {}) or {}).get("pages", []) or []:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}

        def field(key):
            return _plain((meta.get(key) or {}).get("value", ""))

        licence = field("LicenseShortName") or field("UsageTerms")
        ok, why = usable(licence)
        if not ok:
            log.info("skipping %s: %s", page.get("title"), why)
            continue
        if (info.get("width") or 0) < min_width:
            continue
        out.append({
            "title": page.get("title", ""),
            "url": info.get("thumburl") or info.get("url"),
            "page": info.get("descriptionurl", ""),
            "licence": licence,
            "author": field("Artist") or field("Credit") or "Wikimedia Commons",
            "date": field("DateTimeOriginal")[:10],
            "description": field("ImageDescription"),
            "width": info.get("width"),
            "height": info.get("height"),
        })
        if len(out) >= limit:
            break
    return out


def attribution(candidate):
    """The credit line that must appear on screen. Not optional — it is the
    licence condition, which is the only reason we may use the file at all."""
    bits = [candidate.get("author") or "", candidate.get("licence") or ""]
    if candidate.get("date"):
        bits.insert(0, candidate["date"])
    return " · ".join(b for b in bits if b) + " · Wikimedia Commons"


def as_photo_line(candidate, shows):
    """Format a candidate as the CHAPTER n PHOTO: line a script would carry.

    `shows` is the human's claim about what the picture depicts, and it is the
    part no API can supply — see the module docstring.
    """
    return (f"{shows} | {candidate['url']} | {candidate['licence']}, "
            f"{candidate['author']} | {candidate.get('date') or ''}").rstrip(" |")
