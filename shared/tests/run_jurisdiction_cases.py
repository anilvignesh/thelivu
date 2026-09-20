"""The jurisdiction file — the country-agnostic split.

    python -m shared.tests.run_jurisdiction_cases

No network, no database. Reads `jurisdictions/india.yaml` as shipped.

What this is FOR: on 2026-09-20 the 29 audit-office URLs moved out of
`engine/digger/targets.py` and into that YAML, so the framework could take a
second country as a second file rather than a fork. A config that silently
drops a state is strictly worse than the hardcoded list it replaced — the
rotation shrinks, every cross-state comparison quietly loses a peer, and
nothing reports it. So the golden list below is the list as it was on the day
of the move, pinned. If a state disappears from the YAML, this fails.
"""
import sys

GOLDEN_CAG_TARGETS = [
    ('cag-aizawl', 'https://cag.gov.in/ag/aizawl/en/audit-report'),
    ('cag-andhra-pradesh', 'https://cag.gov.in/ag/andhra-pradesh/en/audit-report'),
    ('cag-assam', 'https://cag.gov.in/ag/assam/en/audit-report'),
    ('cag-bihar', 'https://cag.gov.in/ag/bihar/en/audit-report'),
    ('cag-chhattisgarh', 'https://cag.gov.in/ag/chhattisgarh/en/audit-report'),
    ('cag-goa', 'https://cag.gov.in/ag/goa/en/audit-report'),
    ('cag-gujarat', 'https://cag.gov.in/ag1/gujarat/en/audit-report'),
    ('cag-haryana', 'https://cag.gov.in/ag/haryana/en/audit-report'),
    ('cag-himachal-pradesh', 'https://cag.gov.in/ag/himachal-pradesh/en/audit-report'),
    ('cag-jammu-kashmir', 'https://cag.gov.in/ag/jammu-kashmir/en/audit-report'),
    ('cag-jharkhand', 'https://cag.gov.in/ag/jharkhand/en/audit-report'),
    ('cag-karnataka', 'https://cag.gov.in/ag1/karnataka/en/audit-report'),
    ('cag-kerala', 'https://cag.gov.in/ag1/kerala/en/audit-report'),
    ('cag-madhya-pradesh', 'https://cag.gov.in/ag1/madhya-pradesh/en/audit-report'),
    ('cag-manipur', 'https://cag.gov.in/ag/manipur/en/audit-report'),
    ('cag-meghalaya', 'https://cag.gov.in/ag/meghalaya/en/audit-report'),
    ('cag-nagaland', 'https://cag.gov.in/ag/nagaland/en/audit-report'),
    ('cag-nagpur', 'https://cag.gov.in/ag/nagpur/en/audit-report'),
    ('cag-new-delhi', 'https://cag.gov.in/ag/new-delhi/en/audit-report'),
    ('cag-odisha', 'https://cag.gov.in/ag1/odisha/en/audit-report'),
    ('cag-punjab', 'https://cag.gov.in/ag/punjab/en/audit-report'),
    ('cag-rajasthan', 'https://cag.gov.in/ag1/rajasthan/en/audit-report'),
    ('cag-sikkim', 'https://cag.gov.in/ag/sikkim/en/audit-report'),
    ('cag-tamil-nadu', 'https://cag.gov.in/ag1/tamil-nadu/en/audit-report'),
    ('cag-telangana', 'https://cag.gov.in/ag/telangana/en/audit-report'),
    ('cag-tripura', 'https://cag.gov.in/ag/tripura/en/audit-report'),
    ('cag-uttar-pradesh', 'https://cag.gov.in/ag1/uttar-pradesh/en/audit-report'),
    ('cag-uttarakhand', 'https://cag.gov.in/ag/uttarakhand/en/audit-report'),
    ('cag-west-bengal', 'https://cag.gov.in/ag1/west-bengal/en/audit-report'),
]

from shared import jurisdiction as juris          # noqa: E402
from engine.digger import targets                 # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def main():
    print("jurisdiction")
    j = juris.load("india")

    # 1. The offices survived the move, exactly.
    have = sorted((t["key"], t["index_url"]) for t in targets.CAG_STATE_TARGETS)
    check("29 audit offices still built", len(have) == len(GOLDEN_CAG_TARGETS),
          f"{len(have)} vs {len(GOLDEN_CAG_TARGETS)}")
    missing = set(GOLDEN_CAG_TARGETS) - set(have)
    added = set(have) - set(GOLDEN_CAG_TARGETS)
    check("no office lost in the move to config", not missing, str(sorted(missing))[:200])
    check("no office invented", not added, str(sorted(added))[:200])

    # 2. Every office maps into the peer set. An office whose entity is not a
    #    peer is invisible to every cross-state comparison — which is how
    #    "Maharashtra (AG Nagpur)" would have dropped Maharashtra out of the
    #    count while looking completely fine in the rotation.
    unmatched = [o["slug"] for o in j.audit_offices
                 if j.canonical_entity(o.get("entity")) is None]
    check("every audit office maps to a peer entity", not unmatched, str(unmatched))

    # 3. The peer set is the denominator of every structural claim.
    check("peer set is non-trivial", j.peer_count >= 28, str(j.peer_count))
    check("entities are unique",
          len(j.entities) == len({e.lower() for e in j.entities}))

    # 4. Money. Indian grouping is 2-2-3, and a figure printed 3-3-3 is the
    #    kind of wrong that no reader reports and every reader notices.
    check("indian grouping", j.format_money(33973) == "₹33,973 crore",
          j.format_money(33973))
    check("indian grouping past a lakh", j.format_money(126700) == "₹1,26,700 crore",
          j.format_money(126700))
    check("lakh converts to crore", j.to_base_unit(100, "lakh") == 1.0,
          str(j.to_base_unit(100, "lakh")))
    try:
        j.to_base_unit(5, "billion")
        check("an unknown scale raises rather than guesses", False)
    except juris.JurisdictionError:
        check("an unknown scale raises rather than guesses", True)

    # 5. Fiscal year. A report is labelled by what it audits.
    check("april is the new year", j.fiscal_label("2024-05-10") == "2024-25",
          j.fiscal_label("2024-05-10"))
    check("february belongs to the year before",
          j.fiscal_label("2024-02-10") == "2023-24", j.fiscal_label("2024-02-10"))
    check("a label parses back to its opening year",
          j.fiscal_start_year("2023-24") == 2023)

    # 6. Aliases resolve; near-misses do not.
    check("alias resolves", j.canonical_entity("Jammu and Kashmir") == "Jammu & Kashmir")
    check("case and punctuation ignored", j.canonical_entity("west  bengal") == "West Bengal")
    check("a non-entity stays None", j.canonical_entity("Nowhere") is None)
    check("a partial name does not match a state",
          j.canonical_entity("Andhra") is None, "fuzzy matching would merge states")

    # 7. The scout's starting points exist.
    check("seed hosts present", len(j.seed_hosts()) >= 5, str(j.seed_hosts()))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all jurisdiction cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
