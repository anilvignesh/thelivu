"""Finding stories in tables, with no model in the loop.

The digger's original mode is index → document → model reads it. That mode's
whole risk surface is the model: it can misread a figure, and every guard in
this package (grounding, cross-check, pre-filter) exists to catch that.

This mode has no such surface. A government table with a "sanctioned" column and
an "actual" column already contains the finding; what is needed is arithmetic,
not comprehension. **Nothing here calls a model.** A finding it produces cannot
be a hallucination, because nothing generated it — it is a subtraction over rows
that were fetched, with the rows kept.

That is not a small distinction for this desk. It means these findings arrive at
the review step already at a standard the prose pipeline has to work to reach.

## What it looks for

Accountability data has a recognisable *shape*, independent of topic: two
columns that ought to match and do not.

  * sanctioned vs actual, released vs utilised, imposed vs recovered,
    target vs achievement, posts sanctioned vs filled.

The gap between them is the story, and it is the same story whether the subject
is highway penalties, jail staffing or scheme funds. `SHAPES` below is that list
expressed as column-name patterns, which is why a new dataset needs no new code:
if its columns match a known shape, it is watchable.

## What counts as an anomaly

Not "the gap is large" — that is usually just scale. Three things worth a
reviewer's attention:

  1. **An outlier against the same table.** One state recovering 4% where the
     rest recover 60% is a question; everyone recovering 60% is a policy.
  2. **A move since we last looked.** A column that changed sharply between
     polls is news in a way a standing level is not.
  3. **A gap that is near-total.** 100% unrecovered is qualitatively different
     from 70%, because it usually means a decision rather than a shortfall.
"""

import statistics

# Column-name fragments that mark the two sides of an accountability gap.
# Matched loosely against normalised column names, because government tables
# spell the same idea a dozen ways.
# Two kinds, because the arithmetic differs:
#
#   "gap"   — expected vs delivered. The story is what did NOT arrive, so the
#             measure is (expected - actual) / expected.
#   "share" — a population vs the part of it that went wrong. The story is the
#             proportion affected, so the measure is affected / total. Reading
#             one as the other inverts it: 4 delayed of 18 projects is a 22%
#             failure rate, not a 78% one.
SHARE_SHAPES = [
    ("projects", "delayed"),
    ("cases", "pending"),
    ("posts", "vacant"),
    ("strength", "vacant"),
    ("total", "vacant"),
    ("received", "pending"),
    ("filed", "pending"),
]

SHAPES = [
    ("sanctioned", "actual"),
    ("sanctioned", "expenditure"),
    ("released", "utilised"),
    ("released", "utilized"),
    ("released", "expenditure"),
    ("allocated", "spent"),
    ("allocated", "expenditure"),
    ("imposed", "recovered"),
    ("target", "achievement"),
    ("target", "achieved"),
    ("sanctioned", "vacant"),
    ("sanctioned", "filled"),
    ("demanded", "collected"),
    ("registered", "disposed"),
]

# A gap only means something above a floor: 2 of 3 is not a 67% failure rate in
# any useful sense, and small denominators generate most false anomalies.
MIN_DENOMINATOR = 10
# How far from the table's own middle a row must sit to be worth flagging.
OUTLIER_SIGMAS = 2.0
NEAR_TOTAL_GAP = 0.95
# A table where nearly every row shows near-total failure is far more likely to
# be two mismatched columns than a nationwide collapse. This catches the
# mispairings the comparability check does not: "executive_staff jail cadre" vs
# "executive_staff officers" shares enough context to pass, and reported 100%
# across 37 states. Refusing to watch such a table costs one dataset; believing
# it costs 37 false candidates that all look arithmetically sound.
IMPLAUSIBLE_MEDIAN = 0.90


def _norm(name):
    return (name or "").lower().replace("_", " ").strip()


import re as _re

_YEAR = _re.compile(r"(19|20)\d{2}([\s_-]?\d{2})?")


def _context(colname, keyword):
    """A column name with the shape keyword and punctuation stripped — what the
    column is ABOUT, as a token set."""
    n = _norm(colname).replace(keyword, " ")
    return {t for t in _re.split(r"[^a-z0-9]+", n) if t and len(t) > 1}


def _years(colname):
    return {m.group(0).replace("-", "_").replace(" ", "_")
            for m in _YEAR.finditer(_norm(colname))}


def _comparable(f1, f2, a_kw, b_kw, min_overlap=0.5):
    """Do these two columns describe the SAME thing measured two ways?

    This is the check that stops the module inventing stories. Without it, "most
    usable rows" happily paired `total_sanctioned_budget_2023_24` against
    `actual_expenditure_2021_22` (different years), and
    `inspector_si_asi_sanctioned` against `dg_addl_dg_ig_actual` — inspectors
    against Director-Generals, two different ranks — which reported a 99-100%
    "vacancy" across 37 states. Confident, arithmetic, and entirely false.

    Two requirements: any years named must match, and what remains of the column
    names after removing the shape keyword must substantially overlap.
    """
    y1, y2 = _years(f1), _years(f2)
    if y1 and y2 and not (y1 & y2):
        return False
    c1, c2 = _context(f1, a_kw), _context(f2, b_kw)
    c1 -= y1
    c2 -= y2
    if not c1 and not c2:
        return True          # bare "sanctioned" vs "actual" — same thing
    if not c1 or not c2:
        return False
    return len(c1 & c2) / min(len(c1), len(c2)) >= min_overlap


def _candidate_pairs(fieldnames):
    """Every (expected, actual, shape, kind) this table could support, keeping
    only pairs that describe the same subject."""
    norm = {f: _norm(f) for f in fieldnames}
    out = []
    for kind, shapes in (("gap", SHAPES), ("share", SHARE_SHAPES)):
        for a_kw, b_kw in shapes:
            for f1, n1 in norm.items():
                if a_kw not in n1:
                    continue
                for f2, n2 in norm.items():
                    if f2 == f1 or b_kw not in n2:
                        continue
                    if not _comparable(f1, f2, a_kw, b_kw):
                        continue
                    out.append((f1, f2, (a_kw, b_kw), kind))
    return out


def detect_shape(fieldnames, records=None):
    """(expected_col, actual_col, shape, kind) or None.

    When several column pairs match — common in wide tables — prefer the pair
    that yields the MOST usable rows. A jail-staffing table matched
    "DG/Addl DG/IG sanctioned vs actual" first, a two-row population, when the
    total-staff columns beside it covered every state. Taking the first match
    silently watches the smallest slice of the table.
    """
    pairs = _candidate_pairs(fieldnames)
    if not pairs:
        return None
    if not records:
        f1, f2, shape, kind = pairs[0]
        return f1, f2, shape, kind

    key = key_field([f for f in fieldnames])
    best, best_n = None, -1
    for f1, f2, shape, kind in pairs:
        n = len(gaps(records, key, f1, f2, kind=kind))
        if n > best_n:
            best, best_n = (f1, f2, shape, kind), n
    return best if best_n > 0 else pairs[0]


def key_field(fieldnames):
    """The column naming the subject of each row — usually a state."""
    for f in fieldnames:
        n = _norm(f)
        if any(k in n for k in ("state", "ut", "district", "ministry",
                                "department", "scheme", "name", "entity")):
            if "no" not in n.split() and "number" not in n:
                return f
    return fieldnames[0] if fieldnames else None


def gaps(records, key, expected_col, actual_col, kind="gap",
         min_denominator=MIN_DENOMINATOR):
    """[(key, total, other, fraction)] for usable rows.

    `kind="gap"`   -> fraction is what did not arrive: (expected - actual)/expected
    `kind="share"` -> fraction is the affected proportion: affected/total
    """
    from engine.digger.datagov import to_number
    out = []
    for r in records:
        k = (r.get(key) or "").strip()
        exp, act = to_number(r.get(expected_col)), to_number(r.get(actual_col))
        if not k or exp is None or act is None or exp < min_denominator or exp <= 0:
            continue
        frac = (act / exp) if kind == "share" else max(0.0, (exp - act) / exp)
        out.append((k, exp, act, min(frac, 1.0)))
    return out


def anomalies(rows, sigmas=OUTLIER_SIGMAS):
    """Rows worth a reviewer's attention, with the reason.

    Compared against the table's OWN distribution rather than an absolute
    threshold: a 40% shortfall is unremarkable in a table where everyone is at
    40% and is the story in one where nobody else exceeds 5%. An absolute
    threshold would flag the first and miss the second.
    """
    if len(rows) < 4:
        return []
    fractions = [f for _, _, _, f in rows]
    mean = statistics.fmean(fractions)
    try:
        sd = statistics.stdev(fractions)
    except statistics.StatisticsError:
        sd = 0.0

    found = []
    for key, exp, act, frac in rows:
        reasons = []
        if sd > 0 and frac > mean + sigmas * sd:
            reasons.append(
                f"{frac*100:.0f}% shortfall against a table average of "
                f"{mean*100:.0f}% — an outlier among its own peers")
        if frac >= NEAR_TOTAL_GAP:
            reasons.append(
                f"{frac*100:.0f}% of what was committed did not arrive, which "
                "is usually a decision rather than a shortfall")
        if reasons:
            found.append({"key": key, "expected": exp, "actual": act,
                          "shortfall": frac, "reasons": reasons})
    return sorted(found, key=lambda a: -a["shortfall"])


def changes(previous, current, threshold=0.25):
    """Rows that moved sharply since the last poll.

    A standing level is context; a move is news. Stored as {key: shortfall}.
    """
    out = []
    for key, exp, act, frac in current:
        was = previous.get(key)
        if was is None:
            continue
        if abs(frac - was) >= threshold:
            direction = "widened" if frac > was else "narrowed"
            out.append({"key": key, "from": was, "to": frac,
                        "reason": f"gap {direction} from {was*100:.0f}% to {frac*100:.0f}% since the last check"})
    return out


def examine(records, previous=None):
    """Everything this module can say about one table. No model involved."""
    if not records:
        return {"watchable": False, "why": "no rows"}
    fields = list(records[0].keys())
    shape = detect_shape(fields, records)
    if not shape:
        return {"watchable": False, "why": "no accountability shape in the columns",
                "fields": fields}
    expected_col, actual_col, kind, measure = shape
    key = key_field([f for f in fields if f not in (expected_col, actual_col)])
    rows = gaps(records, key, expected_col, actual_col, kind=measure)
    if not rows:
        return {"watchable": True, "why": "shape present but no usable rows",
                "shape": kind}
    median = statistics.median(f for _, _, _, f in rows)
    if len(rows) >= 8 and median >= IMPLAUSIBLE_MEDIAN:
        return {
            "watchable": False,
            "why": (f"median shortfall of {median*100:.0f}% across {len(rows)} rows "
                    f"— '{expected_col}' and '{actual_col}' are almost certainly "
                    "not the same quantity measured two ways"),
            "shape": kind,
        }

    return {
        "watchable": True,
        "shape": kind,
        "measure": measure,
        "key_field": key,
        "expected_col": expected_col,
        "actual_col": actual_col,
        "rows": len(rows),
        "median_shortfall": median,
        "anomalies": anomalies(rows),
        "changes": changes(previous or {}, rows),
        "state": {k: f for k, _, _, f in rows},
    }


def to_candidates(result, dataset_title, dataset_url, target_key="datagov"):
    """Anomalies as digger candidates, in the same shape the prose path emits.

    The excerpt is the arithmetic itself. That is deliberate: the grounding rule
    downstream asks whether a finding is supported by the fetched source, and
    here the numbers ARE the source — quoted from the row they came from.
    """
    out = []
    for a in result.get("anomalies", []):
        out.append({
            "target_key": target_key,
            "title": f"{a['key']}: {a['shortfall']*100:.0f}% shortfall in {dataset_title[:60]}",
            "finding": (f"{a['key']} shows {a['expected']:,.0f} committed against "
                        f"{a['actual']:,.0f} delivered — " + "; ".join(a["reasons"])),
            "excerpt": (f"{result['key_field']}={a['key']}; "
                        f"{result['expected_col']}={a['expected']:,.0f}; "
                        f"{result['actual_col']}={a['actual']:,.0f}"),
            "source_url": dataset_url,
            "agreement": "arithmetic",
        })
    for c in result.get("changes", []):
        out.append({
            "target_key": target_key,
            "title": f"{c['key']}: {c['reason'][:70]}",
            "finding": f"{c['key']} in {dataset_title[:70]} — {c['reason']}",
            "excerpt": f"{result['key_field']}={c['key']}; "
                       f"previous={c['from']*100:.0f}%; current={c['to']*100:.0f}%",
            "source_url": dataset_url,
            "agreement": "arithmetic",
        })
    return out
