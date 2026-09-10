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

`verified` records whether the index was confirmed to yield real document links
on 2026-09-10. Unverified targets stay in the rotation deliberately — a cycle
that fails is logged and slept off, and government sources change format often
enough that today's working URL is not a permanent fact.
"""

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
        "verified": True,   # 20 items; NOTE: served in Hindi regardless of Lang
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
        "link_pattern": r"/audit-report/|/ag[0-9]?/",
        "verified": False,
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
        "verified": False,
        "brief": (
            "Official statistical releases — GDP/GSDP growth figures, revisions "
            "to previously published estimates, and the exact period each "
            "figure covers."
        ),
    },
]

BY_KEY = {t["key"]: t for t in TARGETS}


def next_target(last_key=None):
    """Round-robin. Rotating beats 'run everything every cycle' on a box this
    small, and beats 'one daily pass' for coverage."""
    if not TARGETS:
        return None
    if last_key is None or last_key not in BY_KEY:
        return TARGETS[0]
    idx = next(i for i, t in enumerate(TARGETS) if t["key"] == last_key)
    return TARGETS[(idx + 1) % len(TARGETS)]
