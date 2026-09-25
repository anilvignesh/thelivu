"""The questions no single document answers.

`analyst.py` reads one document and asks what it says. That is extraction, and
it is bounded by the report in front of it — which means the best it can ever
return is a finding the auditor already printed. "₹30,308 crore uncollected" is
on page 11 of a report the CAG published with a press release. Restating it
makes us a commentator.

Anil, 2026-09-15: *"we are pulling up news which the media is not giving enough
coverage, in this we become the primary source of news."*

That happens here, across documents:

    the same objection in N consecutive years, never resolved
    the same failure in N states — structural, not local
    an audit finding with no follow-through in any later report
    a figure that moves in the wrong direction

None of these is visible from inside one report. All of them are visible from
126.7M characters of twenty-nine states over ten years, which is what the corpus
already holds and what, until now, nothing read.

---

**NO MODEL IS IN THE DETECTION LOOP.** Every detector below is arithmetic over
grounded rows — the same discipline `dataset_watch.level_finding` follows, and
for the same reason: there is nothing here that could be a hallucination. A
synthesis cites the finding ids it rests on, each of which quotes a retained
document, so the chain document → excerpt → finding → synthesis survives intact
to publication.

**THE FLOOD RULE IS STRUCTURAL, NOT A PROMPT.** Detectors read only
`db.state_findings()`, which is `cause = 'state'` and nothing else. Karnataka's
₹97,814 crore of flood damage is in this corpus and looks exactly like a
governance failure — an enormous number, in an audit report, beside the word
"loss". A ten-year pattern assembled out of monsoons would be confidently,
repeatedly wrong in public. The filter lives in the accessor so that no detector
written later can forget it.

**WHAT THIS DOES NOT DO.** It does not write the story and it does not decide
one is worth telling. Telling *the state failed* from *it rained* is judgement,
and so is telling a scandal from an accounting convention. That tier is
attended: `draft_dossier()` assembles the evidence for a person, and a person
takes it from there.
"""

import hashlib
import json
import logging
import re
from collections import defaultdict

log = logging.getLogger("synthesis")

# A pattern needs three consecutive years before it is a pattern. Two is a
# coincidence with a witness.
MIN_CONSECUTIVE_YEARS = 3
# A failure is structural when it shows up in this many peers in one year.
# Five is deliberately low as a floor — what makes the claim strong is the
# FRACTION of the peer set, which is stored alongside and reported with it.
MIN_ENTITIES = 5
# And it must cover at least this share of the peer set to be called structural
# rather than "several states".
MIN_PEER_SHARE = 0.25
# Two amounts are "the same figure" within this relative tolerance — audit
# reports restate a number with different rounding between volumes.
AMOUNT_TOLERANCE = 0.01
# A finding has had a chance at follow-through only if we actually hold a later
# report for that entity.
FOLLOW_UP_GAP_YEARS = 2
# Above this share of a cross-entity total held by ONE entity, the claim says
# so. Not a rejection — the finding is still real and the count still holds; it
# is the sum that stops meaning what a reader assumes it means.
CONCENTRATION_FLOOR = 0.4
# How much a figure must ACTUALLY grow across the run before the direction is
# worth reporting. Monotonic-and-nothing-else is too weak a test: a figure
# drifting 100 → 105 over six years rises every single year and is a story
# about nothing. Caught by the test fixture on 2026-09-20, where a flat Kerala
# series came out beside Punjab's genuine 1,000 → 4,000 looking identical.
MIN_GROWTH = 1.5


# ── Shaping the rows ────────────────────────────────────────────────────────

def entity_of(source_key, j):
    """The peer-set entity a source belongs to, or None.

    `cag-kerala` is Kerala; `cag-nagpur` is Maharashtra, because four audit
    offices answer to a city rather than their state. That mapping lives in the
    jurisdiction file, so this is a lookup rather than a rule about India.
    """
    if not source_key:
        return None
    key = str(source_key).lower()
    for office in j.audit_offices:
        slug = str(office.get("slug") or "").lower()
        if slug and (key == slug or key.endswith(f"-{slug}") or key == f"cag-{slug}"):
            return office.get("entity")
    # A source that is not an audit office may still name its entity directly.
    return j.canonical_entity(key.replace("-", " "))


def prepare(rows, j):
    """Attach entity and integer year; drop rows that cannot be placed.

    A finding with no year cannot join a cross-year comparison and a finding
    with no entity cannot join a cross-entity one. Dropped rather than bucketed
    into "unknown", because an "unknown" bucket accumulates and then gets
    counted."""
    out = []
    for r in rows:
        year = j.fiscal_start_year(r.get("published"))
        entity = entity_of(r.get("source_key"), j)
        if year is None or not entity:
            continue
        d = dict(r)
        d["year"] = year
        d["entity"] = entity
        out.append(d)
    return out


# ── The four detectors ──────────────────────────────────────────────────────

def recurring_objection(rows, j, min_years=MIN_CONSECUTIVE_YEARS):
    """The same objection, in the same place, year after year.

    A single year's objection is a finding the auditor published. The same
    objection in six consecutive years is a different claim entirely — it says
    the correction never happened, and nobody assembles it because it requires
    holding six reports at once.

    Consecutive is enforced strictly. A category appearing in 2014, 2019 and
    2023 is not "three years running", and the looser reading would turn almost
    every category in a ten-year corpus into a pattern.
    """
    out = []
    by = defaultdict(list)
    for r in rows:
        if r.get("category"):
            by[(r["entity"], r["category"])].append(r)

    for (entity, category), group in sorted(by.items()):
        years = sorted({r["year"] for r in group})
        for run in _consecutive_runs(years):
            if len(run) < min_years:
                continue
            members = [r for r in group if r["year"] in set(run)]
            total = _sum_amounts(members)
            claim = (f"{entity}: {_phrase(category)} raised in "
                     f"{len(run)} consecutive audit years "
                     f"({run[0]}–{run[-1]}) and never resolved")
            if total:
                claim += f", {j.format_money(round(total))} in total"
            out.append(_synthesis(
                kind="recurring", claim=claim, members=members, j=j,
                entities=[entity], years=[str(y) for y in run],
                category=category, amount_cr=total))
    return out


def structural_failure(rows, j, min_entities=MIN_ENTITIES,
                       min_share=MIN_PEER_SHARE):
    """The same failure across many peers in one year — structural, not local.

    `dataset_watch.level_finding` already asks this of ONE government table:
    when 27 of 27 states are failing at roughly the same rate, the uniformity is
    the story and there is no outlier to find. This asks it of the corpus, where
    the evidence is prose in twenty-nine separate reports and no table exists.

    `peer_count` is stored with the claim, not recomputed at read time. "14 of
    30 states" and "14 of 16 states" are different findings, and the peer set
    grows whenever a new audit office is discovered.
    """
    out = []
    by = defaultdict(list)
    for r in rows:
        if r.get("category"):
            by[(r["year"], r["category"])].append(r)

    peers = j.peer_count
    for (year, category), group in sorted(by.items()):
        entities = sorted({r["entity"] for r in group})
        if len(entities) < min_entities:
            continue
        if peers and len(entities) / peers < min_share:
            continue
        total = _sum_amounts(group)
        claim = (f"{_phrase(category)} in {len(entities)} of {peers} "
                 f"{j.entity_kind}s in {year} — {', '.join(entities[:6])}"
                 f"{' and others' if len(entities) > 6 else ''}")
        top_entity, top_amount, share = _concentration(group)
        if total:
            claim += f", {j.format_money(round(total))} across them"
            # SAY SO WHEN THE SUM IS ONE STATE.
            #
            # Measured over the first real corpus, 2026-09-25: all eight
            # structural claims were dominated by a single entity, between 41%
            # and 96%, six of them above 60%. "₹2,71,214 crore across 8 states"
            # was ₹1,68,283 crore of Maharashtra with seven small numbers
            # attached — every digit true, and the impression it leaves false.
            #
            # That is the same failure `unsupported_number_claims()` blocks in
            # a reel: a real figure attached to the wrong claim. Summing a
            # state's total budget savings with another's short-transfer to a
            # road-safety fund produces a number that is arithmetic rather than
            # a finding, so the concentration travels WITH the total instead of
            # being left for whoever reads it to discover.
            if share and share >= CONCENTRATION_FLOOR:
                claim += (f" — of which {j.format_money(round(top_amount))} "
                          f"is {top_entity} alone ({round(share * 100)}%)")
        out.append(_synthesis(
            kind="structural", claim=claim, members=group, j=j,
            entities=entities, years=[str(year)], category=category,
            amount_cr=total, peer_count=peers))
    return out


def no_follow_through(rows, coverage, j, gap=FOLLOW_UP_GAP_YEARS):
    """A figure raised once, and never accounted for in any later report we hold.

    The dangerous version of this detector is the one that mistakes *we never
    read the later report* for *the later report was silent*. Those are opposite
    conclusions drawn from the same absence, and only one of them is a story.

    So a finding qualifies only when the corpus actually HOLDS a report for that
    entity at least `gap` years later. `coverage` is `db.corpus_coverage()` —
    what we hold, not what exists.

    Matching is on the figure, because an amount is the one thing an audit
    report restates when it follows something up. The claim is worded as what
    was actually checked — no later report in OUR corpus names the figure again
    — and not as "it was never followed up", which is a stronger statement than
    the evidence supports.
    """
    # Only years we have actually READ count as a chance at follow-through.
    #
    # The first version counted a later report as a chance the moment the
    # corpus HELD it. Measured 2026-09-25, that was far too generous: 38 of 73
    # documents had any findings at all, and each of those had been read at
    # roughly one chunk in thirty. "Not named again in any later report" was
    # therefore true of almost everything, and the 13 claims it produced rested
    # on a single finding each.
    #
    # Holding a document and reading it are different states, and the gap
    # between them is exactly where an absence stops being evidence. So a year
    # counts only when some finding was extracted from it — imperfect, since a
    # read chunk is not a read report, but it is the difference between "we
    # looked" and "it is on the disk".
    read_years = defaultdict(set)
    for f in rows:
        read_years[f["entity"]].add(f["year"])

    have = defaultdict(set)
    for c in coverage or []:
        ent = entity_of(c.get("source_key"), j)
        y = j.fiscal_start_year(c.get("published"))
        if ent and y is not None and y in read_years.get(ent, ()):
            have[ent].add(y)

    by_entity = defaultdict(list)
    for r in rows:
        by_entity[r["entity"]].append(r)

    # ONE synthesis per (entity, year, category), carrying every figure that
    # qualified — not one per finding.
    #
    # Emitting per finding looked right and silently destroyed evidence: the
    # fingerprint is kind|jurisdiction|entities|years|category, `store_synthesis`
    # upserts on it, so five Maharashtra 2024 idle-funds findings overwrote each
    # other and the stored row named ONE of them. Measured 2026-09-25: 26
    # detections collapsed into 13 rows, and the survivors looked like thin
    # single-finding claims because their siblings had been overwritten, not
    # because nothing else qualified.
    stranded = defaultdict(list)
    for entity, group in sorted(by_entity.items()):
        years_held = have.get(entity) or set()
        for r in group:
            amount = _as_float(r.get("amount_cr"))
            if not amount:
                continue
            later_held = [y for y in years_held if y >= r["year"] + gap]
            if not later_held:
                continue
            mentioned_again = any(
                o is not r and o["year"] > r["year"]
                and _same_figure(amount, _as_float(o.get("amount_cr")))
                for o in group)
            if mentioned_again:
                continue
            stranded[(entity, r["year"], r.get("category"))].append(
                (r, max(later_held)))

    out = []
    for (entity, year, category), members in sorted(
            stranded.items(), key=lambda kv: str(kv[0])):
        rows_only = [m for m, _ in members]
        through = max(t for _, t in members)
        total = _sum_amounts(rows_only) or 0
        if len(rows_only) == 1:
            what = j.format_money(round(total))
        else:
            what = (f"{len(rows_only)} findings totalling "
                    f"{j.format_money(round(total))}")
        claim = (f"{entity}: {what} of "
                 f"{_phrase(category or 'audit finding')} in {year} "
                 f"{'is' if len(rows_only) == 1 else 'are'} not named again in "
                 f"any later audit report we have READ (through {through})")
        out.append(_synthesis(
            kind="no-follow-through", claim=claim, members=rows_only, j=j,
            entities=[entity], years=[str(year)], category=category,
            amount_cr=total))
    return out


def wrong_direction(rows, j, min_years=MIN_CONSECUTIVE_YEARS,
                    min_growth=MIN_GROWTH):
    """A figure that gets worse every year, in consecutive years.

    Worded as movement and nothing more. The plan calls this "a figure that
    moves in the wrong direction after an assurance" — an assurance is not
    something this corpus records, so claiming one would be inventing the part
    that makes the story. What is provable is the direction, and that is what
    the claim says.
    """
    out = []
    by = defaultdict(dict)
    for r in rows:
        amount = _as_float(r.get("amount_cr"))
        if not amount or not r.get("category"):
            continue
        slot = by[(r["entity"], r["category"])]
        # Several findings of one category in one year: take the largest, which
        # is the one an audit report leads with.
        if r["year"] not in slot or amount > _as_float(slot[r["year"]].get("amount_cr")):
            slot[r["year"]] = r

    for (entity, category), per_year in sorted(by.items()):
        years = sorted(per_year)
        for run in _consecutive_runs(years):
            if len(run) < min_years:
                continue
            amounts = [_as_float(per_year[y].get("amount_cr")) for y in run]
            if not all(b > a for a, b in zip(amounts, amounts[1:])):
                continue
            if not amounts[0] or amounts[-1] < amounts[0] * min_growth:
                continue
            members = [per_year[y] for y in run]
            claim = (f"{entity}: {_phrase(category)} grew every year from "
                     f"{j.format_money(round(amounts[0]))} in {run[0]} to "
                     f"{j.format_money(round(amounts[-1]))} in {run[-1]}")
            out.append(_synthesis(
                kind="wrong-direction", claim=claim, members=members, j=j,
                entities=[entity], years=[str(y) for y in run],
                category=category, amount_cr=amounts[-1]))
    return out


# ── Running them ────────────────────────────────────────────────────────────

def run(jurisdiction_key=None, store=True, rows=None, coverage=None):
    """Every detector over the corpus. Returns the syntheses found.

    Re-runnable by design: each synthesis carries a fingerprint over its kind,
    entities, years and category, so a nightly pass updates a claim whose
    evidence grew instead of filing a second copy of it.
    """
    from shared import db, jurisdiction as juris

    j = juris.load(jurisdiction_key)
    raw = db.state_findings() if rows is None else rows
    cov = db.corpus_coverage() if coverage is None else coverage
    prepared = prepare(raw, j)
    log.info("synthesis: %d findings, %d placed in %s",
             len(raw), len(prepared), j.key)

    found = []
    found += recurring_objection(prepared, j)
    found += structural_failure(prepared, j)
    found += no_follow_through(prepared, cov, j)
    found += wrong_direction(prepared, j)

    if store:
        for s in found:
            try:
                s["id"] = db.store_synthesis(
                    kind=s["kind"], claim=s["claim"], evidence_ids=s["evidence"],
                    jurisdiction=j.key, entities=s["entities"], years=s["years"],
                    category=s.get("category"), amount_cr=s.get("amount_cr"),
                    peer_count=s.get("peer_count"),
                    fingerprint=s["fingerprint"])
            except Exception as e:                              # noqa: BLE001
                log.warning("could not store synthesis %s: %s",
                            s["fingerprint"], e)
    return found


def draft_dossier(synthesis, findings_by_id=None):
    """Everything a person needs to judge one synthesis, as text.

    This is where the attended tier begins and it is deliberately not a model
    call. A synthesis is arithmetic; deciding it is a story — rather than an
    accounting convention, a reclassification, or a state that simply reports
    more thoroughly than its neighbours — is judgement, and the plan puts
    judgement in front of a person.

    Every claim is printed with its verbatim excerpt and the document it came
    from, so the first thing the reader sees is the evidence rather than the
    conclusion.
    """
    from shared import db

    if findings_by_id is None:
        findings_by_id = {r["id"]: r for r in db.state_findings()}

    lines = [synthesis["claim"], ""]
    lines.append(f"kind: {synthesis['kind']}   "
                 f"years: {', '.join(synthesis.get('years') or [])}   "
                 f"{synthesis.get('category') or ''}")
    if synthesis.get("peer_count"):
        lines.append(f"peer set: {len(synthesis.get('entities') or [])} of "
                     f"{synthesis['peer_count']}")
    lines.append("")
    lines.append("EVIDENCE — every line below is quoted from a retained document:")
    for fid in synthesis.get("evidence") or []:
        f = findings_by_id.get(fid)
        if not f:
            lines.append(f"  [{fid}] (finding no longer in the corpus)")
            continue
        lines.append(f"  [{fid}] {f.get('source_key')} {f.get('published')} — "
                     f"{f.get('claim')}")
        if f.get("excerpt"):
            lines.append(f"        “{f['excerpt']}”")
        lines.append(f"        document {str(f.get('doc_sha256'))[:12]}")
    lines.append("")
    lines.append("Before this becomes a story, check: is the rise a "
                 "reclassification? Does a state that reports more thoroughly "
                 "look worse here than one that reports less? Is there a "
                 "published response?")
    return "\n".join(lines)


# ── helpers ─────────────────────────────────────────────────────────────────

def _synthesis(kind, claim, members, j, entities, years, category=None,
               amount_cr=None, peer_count=None):
    ids = sorted({int(m["id"]) for m in members if m.get("id") is not None})
    fp = hashlib.sha256("|".join([
        kind, j.key, ",".join(sorted(entities)), ",".join(sorted(years)),
        category or ""]).encode()).hexdigest()[:32]
    return {"kind": kind, "claim": claim, "evidence": ids,
            "entities": list(entities), "years": list(years),
            "category": category, "amount_cr": amount_cr,
            "peer_count": peer_count, "fingerprint": fp}


def _consecutive_runs(years):
    """[2011,2012,2013,2016] -> [[2011,2012,2013],[2016]]"""
    runs, current = [], []
    for y in sorted(years):
        if current and y == current[-1] + 1:
            current.append(y)
        elif current and y == current[-1]:
            continue
        else:
            if current:
                runs.append(current)
            current = [y]
    if current:
        runs.append(current)
    return runs


def _concentration(rows):
    """(entity, largest single amount, its share of the total) for a group.

    Answers "is this a spread failure or one state's number" — the question a
    cross-entity total cannot answer about itself."""
    amounts = [(_as_float(r.get("amount_cr")) or 0, r.get("entity")) for r in rows]
    total = sum(a for a, _ in amounts)
    if not total:
        return None, None, None
    top_amount, top_entity = max(amounts)
    return top_entity, top_amount, top_amount / total


def _sum_amounts(rows):
    total = sum(_as_float(r.get("amount_cr")) or 0 for r in rows)
    return total or None


def _as_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _same_figure(a, b, tol=AMOUNT_TOLERANCE):
    if not a or not b:
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b))


def _phrase(category):
    """A category as it reads in a sentence."""
    words = {
        "recovery": "money advanced and not recovered",
        "idle": "funds left idle",
        "non-compliance": "non-compliance with audit requirements",
        "delay": "delay in sanctioned work",
        "diversion": "diversion of funds",
        "shortfall": "shortfall against sanctioned provision",
        "irregular": "irregular expenditure",
    }
    return words.get(str(category or "").lower(),
                     re.sub(r"[-_]+", " ", str(category or "an audit objection")))


def main(argv=None):
    """    python -m engine.synthesis            # run every detector, store
    python -m engine.synthesis --dry-run       # print, store nothing
    python -m engine.synthesis --dossier 12    # the evidence behind one

    No API key needed and none used: detection is arithmetic over rows that
    already quote their documents.
    """
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Thelivu synthesise tier")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be found, write nothing")
    ap.add_argument("--jurisdiction", default=None)
    ap.add_argument("--kind", help="only one of: recurring | structural | "
                                   "no-follow-through | wrong-direction")
    ap.add_argument("--dossier", type=int, metavar="ID",
                    help="print the evidence behind one stored synthesis")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.dossier:
        from shared import db
        rows = [s for s in db.syntheses(limit=500) if s["id"] == args.dossier]
        if not rows:
            print(f"no synthesis {args.dossier}", file=sys.stderr)
            return 1
        print(draft_dossier(rows[0]))
        return 0

    found = run(args.jurisdiction, store=not args.dry_run)
    if args.kind:
        found = [s for s in found if s["kind"] == args.kind]
    for s in sorted(found, key=lambda x: -(x.get("amount_cr") or 0)):
        print(f"[{s['kind']:18s}] {s['claim']}")
        print(f"{'':20s} {len(s['evidence'])} finding(s): "
              f"{', '.join(str(i) for i in s['evidence'][:8])}")
    print(f"\n{len(found)} synthesis/es"
          f"{' (nothing written — dry run)' if args.dry_run else ' stored'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
