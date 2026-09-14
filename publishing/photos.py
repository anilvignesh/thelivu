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

import json
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


# Words that carry no identifying weight in a Commons filename, so their
# presence must not count as the title corroborating anything.
# NO PLACE NAMES HERE. "india" was on this list for one draft and it is the
# single word separating the Comptroller and Auditor General of INDIA from the
# Auditor General of PAKISTAN — dropping it as generic is how the wrong country
# gets on screen. Only genuinely descriptive words belong.
_WEAK = {"the", "of", "and", "in", "on", "at", "a", "an", "file", "jpg", "jpeg",
         "png", "building", "office", "view", "inside", "outside", "new", "old",
         "photo", "image", "shri", "smt", "ms", "mr"}


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


def portrait(name, timeout=TIMEOUT):
    """The image from the ARTICLE ABOUT a subject. Returns a candidate or None.

    This exists because `search()` cannot establish subject and no amount of
    filtering fixes that. Measured 2026-09-14, searching Commons for the
    Comptroller and Auditor General of India returns a correctly licensed
    photograph of the Auditor General of PAKISTAN — and its caption names both
    officials, so a filename test keeps it. Relevance ranking is not an
    assertion about who is in the picture.

    An article's lead image is a different kind of claim. Editors chose it AS a
    depiction of that subject, and a name with no article returns nothing rather
    than the closest match. That is the difference between "this file mentions
    the Finance Minister" and "this is the Finance Minister".

    It still does not establish that the picture is CURRENT, or taken at the
    event the script describes. A correct portrait of the right minister from
    six years ago is a different claim from a photograph of them at that budget
    session, and only a person can tell those apart — so this makes a photo
    PROPOSABLE and gate 1 still decides.

    Needs a NAME. "Finance Minister" has no article; "K. N. Balagopal" does.
    That is a constraint on the script, not a limitation here — see
    engine/skills/long-form-script/SKILL.md.
    """
    params = {"action": "query", "format": "json",
              "prop": "pageimages|pageterms|pageprops", "piprop": "original",
              "redirects": 1, "titles": name}
    try:
        req = urllib.request.Request(
            WIKIPEDIA_API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:                                  # noqa: BLE001
        log.info("portrait lookup failed for %r: %s", name, e)
        return None

    pages = (data.get("query") or {}).get("pages") or {}
    for page in (pages.values() if isinstance(pages, dict) else pages):
        if "missing" in page:
            continue
        src = (page.get("original") or {}).get("source")
        if not src:
            continue
        # Is this article about a THING or about a CONCEPT? "Finance Minister"
        # has an article — the generic one about the office — and its lead image
        # is a Library of Congress mural. Public domain, correctly licensed, and
        # a photograph of nobody. Asking Wikidata what the subject IS separates
        # "K. N. Balagopal, Indian politician" from "finance minister, a
        # government position", which no title or licence check can do.
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if not _is_a_specific_thing(qid, timeout=timeout):
            log.info("%r is a concept, not a subject — refusing its lead image",
                     name)
            return None
        filename = urllib.parse.unquote(src.split("/")[-1].split("?")[0])
        # An SVG lead image is a logo or a coat of arms, not a photograph. Fine
        # for an institution, wrong for "show me the minister".
        if filename.lower().endswith(".svg"):
            log.info("%r leads with %s — a logo, not a photograph", name, filename)
            return None
        meta = _file_metadata(filename, timeout=timeout) or {}
        licence = meta.get("licence", "")
        ok, why = usable(licence)
        if not ok:
            log.info("portrait of %r is %s — %s", name, licence or "unlicensed", why)
            return None
        return {
            "title": page.get("title") or name,
            "url": src,
            "filename": filename,
            "licence": licence,
            "author": meta.get("author", ""),
            "credit": meta.get("credit", ""),
            "date": meta.get("date", ""),
            # Says HOW we believe this is the right subject, so a reviewer can
            # weigh it. A lead image is a stronger claim than a text hit.
            "subject_basis": f"lead image of the Wikipedia article '{page.get('title')}'",
        }
    return None


# Wikidata classes a portrait may legitimately depict. Q5 is a human; the rest
# are things that physically exist and can be photographed. A government POST,
# a policy or an event type is none of these, and that is the distinction.
_DEPICTABLE = {
    "Q5",          # human
    "Q43229",      # organization
    "Q41176",      # building
    "Q3947",       # house
    "Q515",        # city
    "Q486972",     # human settlement
    "Q56061",      # administrative territorial entity
    "Q327333",     # government agency
    "Q2085381",    # ... publisher/institution
}


def _is_a_specific_thing(qid, timeout=TIMEOUT):
    """Does Wikidata say this subject is something that can be photographed?

    Unknown is NOT permission. A lookup that fails, or an entity with no P31 we
    recognise, returns False — the cost of refusing a good photo is one missing
    frame, and the cost of accepting a bad one is a false claim on screen.
    """
    if not qid:
        return False
    try:
        req = urllib.request.Request(
            f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:                                  # noqa: BLE001
        log.info("wikidata lookup failed for %s: %s", qid, e)
        return False

    ent = (body.get("entities") or {}).get(qid) or {}
    for claim in (ent.get("claims") or {}).get("P31") or []:
        val = (((claim.get("mainsnak") or {}).get("datavalue") or {})
               .get("value") or {})
        if val.get("id") in _DEPICTABLE:
            return True
    return False


WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# How long a role stays resolvable without anyone checking. A ministry changes
# hands; a cached answer from last year is a wrong face, not a stale one.
# Who held an office ON A GIVEN DATE. Not "now" — see officeholder().
OFFICEHOLDER_QUERY = """
SELECT ?person ?personLabel ?start ?end WHERE {
  ?office rdfs:label %s@en .
  ?person p:P39 ?st .
  ?st ps:P39 ?office .
  OPTIONAL { ?st pq:P580 ?start }
  OPTIONAL { ?st pq:P582 ?end }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

def officeholder(office, as_of, timeout=TIMEOUT):
    """Who held `office` ON THE DATE `as_of` (YYYY-MM-DD). (name, start, end) or None.

    `as_of` IS REQUIRED, AND THAT IS THE WHOLE POINT. The first version of this
    asked "who holds it now", which is the wrong question for accountability
    journalism and dangerous in a specific way.

    Long-form #1 audits Kerala's FY 2023-24. Those arrears accrued under Chief
    Minister Pinarayi Vijayan with K. N. Balagopal at Finance. Kerala changed
    government on 18 May 2026; the Chief Minister is now V. D. Satheesan, who
    also holds Finance. "The current Finance Minister" would therefore have put
    Satheesan's face beside 30,308 crore of failures that predate him by years.
    That is not a stale photograph. It is a false accusation.

    So the caller must say WHICH PERIOD the story covers, and this returns who
    was answerable then.

    WIKIDATA GOES STALE AND NO RULE HERE FIXES THAT. Asked on 2026-09-14 who
    holds the Chief Ministership of Kerala, it offers:

        Pinarayi Vijayan   start 2016-05-25   no end date   (left office in May)
        V. D. Satheesan    no start date      no end date   (the actual CM)

    An earlier version required a start date, on the reasoning that an undated
    statement is unreliable. That rule selected the FORMER Chief Minister and
    rejected the sitting one — it produced exactly the error it was written to
    prevent. Undated statements are now kept and reported as unverified rather
    than silently dropped, and a result whose term does not cover `as_of` is
    refused outright.

    For WHO HOLDS AN OFFICE TODAY, do not use this. Use the government's own
    council-of-ministers page; it is authoritative and Wikidata is not.
    """
    literal = json.dumps(office)
    try:
        url = WIKIDATA_SPARQL + "?" + urllib.parse.urlencode(
            {"query": OFFICEHOLDER_QUERY % literal, "format": "json"})
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:                                  # noqa: BLE001
        log.info("officeholder lookup failed for %r: %s", office, e)
        return None

    hits, undated = [], []
    for row in (body.get("results") or {}).get("bindings") or []:
        name = row["personLabel"]["value"]
        start = (row.get("start") or {}).get("value", "")[:10]
        end = (row.get("end") or {}).get("value", "")[:10]
        # A STATEMENT WITH NO START DATE PLACES NOBODY IN TIME. Treating it as
        # "covers all time" is not conservative, it is useless: V. D. Satheesan's
        # undated Kerala record then matched every query from 1957 onward and
        # made every single one ambiguous. Undated statements are set aside and
        # reported, not counted.
        if not start:
            undated.append(name)
            continue
        if start > as_of:
            continue
        if end and end < as_of:
            continue
        hits.append((name, start, end))

    if not hits:
        log.info("wikidata names nobody holding %r on %s%s", office, as_of,
                 (" (undated records exist for %s)" % ", ".join(undated[:3]))
                 if undated else "")
        return None
    if len(hits) > 1:
        # Ambiguity is refused, never resolved — guessing between two
        # politicians is the error this module exists to avoid.
        log.info("%r on %s is ambiguous (%s) — refusing to choose",
                 office, as_of, ", ".join(h[0] for h in hits[:3]))
        return None

    name, start, end = hits[0]
    if not end and undated:
        # An open-ended term plus an undated rival is the exact shape of a
        # change of government Wikidata has not caught up with. It is how
        # Pinarayi Vijayan was returned as Kerala's sitting Chief Minister four
        # months after V. D. Satheesan replaced him.
        log.warning("%r: %s has no recorded end and %s is listed undated — "
                    "Wikidata may not have caught a change of government. "
                    "Check the government's own council-of-ministers page.",
                    office, name, ", ".join(undated[:2]))
    return name, start, end


def propose(subject, as_of=None, timeout=TIMEOUT):
    """Photo candidates for a subject, each carrying HOW we think it is right.

    Three routes, strongest first, because they fail in different ways and the
    reviewer needs to know which one produced what is in front of them:

      named person   portrait() on a name. The lead image of that person's
                     article — editors chose it AS a depiction. Strongest.
      named office   officeholder() resolves the post AS OF the date the story
                     covers, then the above. Requires `as_of`; without it this
                     route is skipped entirely, because "the current minister"
                     is the wrong question for a story about a past period.
      text search    Commons relevance. WEAKEST, and the one that returned a
                     correctly-licensed photograph of the Auditor General of
                     PAKISTAN for a search about India's CAG.

    Nothing here decides. Every candidate goes to gate 1 with its basis and its
    date, and a person says yes — because the question a reviewer has to answer
    is whether this is the right minister on the right day, and no API knows
    that. The machine establishes what is permitted; a person establishes what
    is true.
    """
    out = []
    direct = portrait(subject, timeout=timeout)
    if direct:
        out.append(direct)

    if as_of:
        holder = officeholder(subject, as_of, timeout=timeout)
        if holder:
            name, start, end = holder
            got = portrait(name, timeout=timeout)
            if got:
                term = f"{start or 'an unrecorded date'} to {end or 'no recorded end'}"
                got["subject_basis"] = (
                    f"Wikidata: {name} held '{subject}' on {as_of} (term: {term}). "
                    f"CONFIRM against the government's own list — Wikidata lags "
                    f"a change of government.")
                out.append(got)

    for cand in search(subject, limit=6):
        ok, _why = usable(cand.get("licence", ""))
        if ok and subject_match(cand, subject):
            cand["subject_basis"] = (
                "Commons text search — RANKING ONLY, confirm the subject")
            out.append(cand)

    # One shape for the caller. portrait() and search() build different dicts,
    # and a gate-1 card that has to branch on which route produced a candidate
    # will eventually print the wrong field for one of them.
    seen, uniq = set(), []
    for c in out:
        key = c.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append({
            "title": c.get("title", ""),
            "url": key,
            "filename": c.get("filename") or urllib.parse.unquote(
                key.split("/")[-1].split("?")[0]),
            "licence": c.get("licence", ""),
            "author": c.get("author", ""),
            "credit": c.get("credit", ""),
            "date": c.get("date", ""),
            "subject_basis": c.get("subject_basis", "unstated"),
        })
    return uniq


def _file_metadata(filename, timeout=TIMEOUT):
    """Licence and author for one Commons file, from its extmetadata."""
    try:
        body = _get({"action": "query", "format": "json", "prop": "imageinfo",
                     "iiprop": "extmetadata|url", "titles": "File:" + filename})
    except Exception as e:                                  # noqa: BLE001
        log.info("metadata lookup failed for %s: %s", filename, e)
        return None
    # `pages` is a dict keyed by page id in the classic API and a LIST under
    # formatversion=2, which _get() asks for. Handle both rather than depending
    # on which one a shared helper requests today.
    pages = (body.get("query") or {}).get("pages") or {}
    for page in (pages.values() if isinstance(pages, dict) else pages):
        for info in page.get("imageinfo") or []:
            em = info.get("extmetadata") or {}
            g = lambda k: _plain((em.get(k) or {}).get("value", "") or "")  # noqa: E731
            return {"licence": g("LicenseShortName") or g("UsageTerms"),
                    "author": g("Artist"), "credit": g("Credit"),
                    "date": g("DateTimeOriginal")}
    return None


def subject_match(candidate, query):
    """Does the FILE'S OWN TITLE corroborate that this is what we searched for?

    Commons relevance ranking is not an assertion about subject, and trusting it
    produces exactly the failure this module's docstring warns about. Measured
    on 2026-09-14, against searches for a real Kerala audit story:

        "Kerala Secretariat"          -> Dalava.jpg
                                         an 18th-century Travancore official
        "Comptroller and Auditor
         General of India building"   -> The Auditor General of PAKISTAN

    Both correctly licensed, both a false claim if put on screen. Both are
    rejected by requiring the distinctive words of the query to appear in the
    title, which "Pinarayi Vijayan" -> Pinarayi-Vijayan-Eriya.jpg passes and
    neither of those does.

    This is a test for CORROBORATION, not for truth. A photograph of the right
    minister on the wrong day is still wrong, and no filename can tell you that
    — which is why a match here makes a photo proposable, and a person at gate 1
    still decides whether it goes in.
    """
    terms = [t for t in re.findall(r"[A-Za-z]{3,}", (query or "").lower())
             if t not in _WEAK]
    if not terms:
        return False
    title = re.sub(r"[^a-z0-9]+", " ", (candidate.get("title") or "").lower())
    words = set(title.split())
    hit = sum(1 for t in terms if t in words)
    # Every distinctive word, or both of the two when that is all there is. A
    # partial match is how "Auditor General of India" became "Auditor General of
    # Pakistan" — the words that agreed were the ones that identify nothing.
    return hit == len(terms)


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
