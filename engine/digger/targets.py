"""Watch targets for the Tier-0 loop.

These mirror categories already specified in engine/skills/beat-monitor/SKILL.md
— this tier does not invent a new beat, it reads the same records more often and
more systematically. beat-monitor runs once a day and hopes one pass covers
thirteen categories; this rotates through them.

Each target names an **index** (a feed or a listing page). The loop reads the
index only to choose a document, then fetches that document and extracts from
it. That indirection is not incidental: verified 2026-09-10, the RBI
press-release listing is ~12k characters of navigation chrome with the actual
releases loaded by JS, so a model reading the *listing* correctly finds nothing.
A listing page is not a document.

PDFs are first-class here: most CAG/MOSPI primary records are PDFs, and they are
parsed via liteparse (see fetch.pdf_to_text). A PDF with no text layer, or one
PDFium rejects outright, is reported as an honest miss rather than as empty text.

`verified` records whether the index was confirmed to yield real document links
on 2026-09-10. Unverified targets stay in the rotation deliberately — a cycle
that fails is logged and slept off, and government sources change format often
enough that today's working URL is not a permanent fact.
"""

# Dataset targets: a data.gov.in resource watched by arithmetic rather than
# read by a model. No model call, so no hallucination surface — see
# engine/digger/dataset_watch.py. `kind` distinguishes them from index targets.
DATASET_TARGETS = [
    {
        "key": "nh-projects-delayed",
        "kind": "dataset",
        "name": "MoRTH — NH projects and delayed projects, by state",
        "resource_id": "239bb06d-9598-45e2-bef9-4322908b3fad",
        "verified": True,
        "enabled": True,
    },
    # All verified 2026-09-11 by running dataset_watch.examine() over the live
    # rows: the column pair is comparable, the median is plausible, and the
    # anomalies it reports are outliers against the table's own distribution.
    {
        "key": "state-budget-vs-actual",
        "kind": "dataset",
        "name": "State/UT sanctioned budget vs actual expenditure",
        "resource_id": "9b4965b9-effe-430b-9915-d20adfa17627",
        "verified": True,   # median 10%; flags Bihar 33%, Puducherry 31%
        "enabled": True,
    },
    {
        "key": "scheme-funds-released-vs-spent",
        "kind": "dataset",
        "name": "State/UT funds released vs expenditure incurred on sanctioned projects",
        "resource_id": "eb76fa2b-53ec-4bff-a191-20795e5584e5",
        "verified": True,   # median 0% — most states spend what they get, so an
                            # outlier here is stark: Gujarat 894 released, 21 spent
        "enabled": True,
    },
    {
        "key": "jail-staff-vacancy",
        "kind": "dataset",
        "name": "State/UT sanctioned vs actual strength of total jail staff",
        "resource_id": "330a7b3f-8872-474f-aa47-caaa969f0eb9",
        "verified": True,   # median 31%; flags Jharkhand at 62%
        "enabled": True,
    },
    {
        "key": "civil-police-vacancy",
        "kind": "dataset",
        "name": "State/UT sanctioned vs actual strength of civil police",
        "resource_id": "29a72c62-58e3-4116-8b98-b66d6ea4709c",
        "verified": True,   # median 19%; flags Haryana 68%, Lakshadweep 73%
        "enabled": True,
    },
]

TARGETS = [
    {
        "key": "sebi-enforcement",
        "name": "SEBI enforcement / recovery orders",
        "index_url": "https://www.sebi.gov.in/sebirss.xml",
        "link_pattern": r"/enforcement/|/orders/",
        "verified": True,   # 30 English items with real document links
        "brief": (
            "Enforcement, adjudication or recovery action: the entity or person "
            "named, the violation found, and any penalty amount, recovery "
            "certificate number or restriction stated in the document."
        ),
    },
    {
        "key": "pib-releases",
        "name": "PIB press releases",
        "index_url": "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "link_pattern": r"PressRelease",
        # DISABLED 2026-09-10. PIB's WAF returns 403 to urllib from the VM while
        # curl on the same box gets 200 — so it is fingerprinting the client, not
        # blocking the IP, and browser-like Accept headers did not change it.
        # Chasing that is not worth it for the least valuable target on the list
        # (press releases are promotional; the audit and enforcement records are
        # where the stories are). Re-enable if a working client is found.
        "enabled": False,
        "verified": False,
        "brief": (
            "Any specific allocation, disbursal, completion or beneficiary "
            "figure stated in the release — the kind of claim that can later be "
            "checked against an audit or a primary statistical release. The "
            "document may be in Hindi; extract figures exactly as written."
        ),
    },
    {
        "key": "cag-reports",
        "name": "CAG audit reports index",
        "index_url": "https://cag.gov.in/en/audit-report",
        "link_pattern": r"\.pdf$|/audit-report/|/ag[0-9]?/",
        "verified": True,   # yields real PDF links; PDFs now parsed via liteparse
        "brief": (
            "Audit findings: the department or scheme audited, the period "
            "covered, and any rupee figure, unresolved objection or compliance "
            "failure stated in the document."
        ),
    },
    {
        "key": "cag-local-bodies",
        "name": "CAG local-body audit reports (nationwide OGD catalog)",
        "index_url": "https://www.data.gov.in/catalog/cag-local-bodies-audit-reports",
        "link_pattern": r"/resource/|/catalog/",
        # DISABLED 2026-09-11. data.gov.in's HTML catalog returns 403 to our
        # fetcher, and it failed every rotation for a day. The API key we now
        # hold opens api.data.gov.in, but a search of the 287k-resource catalog
        # found no structured equivalent of the CAG local-body audits — the
        # nearest hits are Local Government Directory listings, which are
        # administrative registers, not audits. Re-enable if a resource id for
        # the audits themselves turns up.
        "enabled": False,
        "verified": False,
        "brief": (
            "Audit findings on municipal or local-body finances: unspent or "
            "diverted funds, unresolved audit objections, or irregularities "
            "with a rupee figure and a named corporation or municipality."
        ),
    },
    {
        "key": "mospi-releases",
        "name": "MOSPI / NSO statistical releases",
        "index_url": "https://www.mospi.gov.in/press-release",
        "link_pattern": r"/press-release|/sites/default/files",
        # DISABLED 2026-09-11. Every MOSPI listing path tried yields zero
        # document links — the pages are JS-rendered and there is no feed. It
        # failed every rotation. MOSPI's macro data is better reached as
        # datasets anyway (see DATASET_TARGETS); this target was the wrong shape
        # for the source.
        "enabled": False,
        "verified": False,
        "brief": (
            "Official statistical releases — GDP/GSDP growth figures, revisions "
            "to previously published estimates, and the exact period each "
            "figure covers."
        ),
    },
]

BY_KEY = {t["key"]: t for t in TARGETS}


def db_targets():
    """Scout-proposed sources a HUMAN has activated (status='active').

    Proposals never reach here on their own — see engine/digger/discover.py.
    A DB failure returns the built-in list rather than an empty rotation: the
    digger losing its Postgres connection should degrade to the known-good
    sources, not stop investigating.
    """
    try:
        from shared import db
        rows = db.digger_targets(status="active")
    except Exception:
        return []
    out = []
    for r in rows:
        if not r.get("index_url") or not r.get("brief"):
            continue
        out.append({
            "key": r["key"],
            "name": r.get("name") or r["key"],
            "index_url": r["index_url"],
            "link_pattern": r.get("link_pattern"),
            "brief": r["brief"],
            "verified": bool(r.get("fetch_ok")),
            "source": "db",
        })
    return out


def active_targets():
    """Targets in the rotation: built-in index targets, dataset targets, plus
    anything a human has activated. A target may be disabled outright when it is
    known-broken (see PIB) rather than left to burn a cycle every few hours."""
    builtin = [t for t in TARGETS if t.get("enabled", True)]
    datasets = [t for t in DATASET_TARGETS if t.get("enabled", True)]
    known = {t["key"] for t in builtin + datasets}
    return builtin + datasets + [t for t in db_targets() if t["key"] not in known]


def by_key(key):
    for t in active_targets():
        if t["key"] == key:
            return t
    return BY_KEY.get(key)


def next_target(last_key=None):
    """Round-robin over the active targets. Rotating beats 'run everything every
    cycle' on a box this small, and beats 'one daily pass' for coverage."""
    active = active_targets()
    if not active:
        return None
    keys = [t["key"] for t in active]
    if last_key is None or last_key not in keys:
        return active[0]
    return active[(keys.index(last_key) + 1) % len(active)]
