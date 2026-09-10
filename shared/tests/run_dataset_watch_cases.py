"""Finding stories in tables — arithmetic, with no model in the loop.

    python -m shared.tests.run_dataset_watch_cases

No network. Fixture tables.

What this is FOR is the inversion that would quietly produce false stories: a
"share" table (18 projects, 4 delayed) read as a "gap" table reports a 78%
failure rate instead of 22%. Both are plausible numbers about the same row, and
only one is true.
"""
import sys

from engine.digger import dataset_watch as dw

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


GAP_TABLE = [   # sanctioned vs actual — the shortfall is what did not arrive
    {"state_ut": "Kerala",   "sanctioned_budget": "100", "actual_expenditure": "95"},
    {"state_ut": "Gujarat",  "sanctioned_budget": "200", "actual_expenditure": "186"},
    {"state_ut": "Bihar",    "sanctioned_budget": "800", "actual_expenditure": "590"},
    {"state_ut": "Assam",    "sanctioned_budget": "150", "actual_expenditure": "142"},
    {"state_ut": "Punjab",   "sanctioned_budget": "120", "actual_expenditure": "113"},
    {"state_ut": "Odisha",   "sanctioned_budget": "180", "actual_expenditure": "170"},
]

SHARE_TABLE = [  # projects vs delayed — the story is the affected proportion
    {"state_ut": "Kerala",      "number_of_projects": "18",  "number_of_delayed_projects": "4"},
    {"state_ut": "Maharashtra", "number_of_projects": "101", "number_of_delayed_projects": "59"},
    {"state_ut": "Gujarat",     "number_of_projects": "31",  "number_of_delayed_projects": "22"},
    {"state_ut": "Mizoram",     "number_of_projects": "17",  "number_of_delayed_projects": "14"},
    {"state_ut": "Assam",       "number_of_projects": "44",  "number_of_delayed_projects": "9"},
]


def t_share_table_is_not_read_as_a_gap():
    """The inversion that matters: 4 delayed of 18 is a 22% failure rate, not a
    78% one. Both are plausible numbers about the same row."""
    out = dw.examine(SHARE_TABLE)
    check("watchable", out["watchable"], True)
    check("recognised as a share", out["measure"], "share")
    kerala = out["state"]["Kerala"]
    check("Kerala reads 22%, not 78%", round(kerala * 100), 22)
    check("Maharashtra reads 58%", round(out["state"]["Maharashtra"] * 100), 58)


def t_gap_table_measures_what_did_not_arrive():
    out = dw.examine(GAP_TABLE)
    check("recognised as a gap", out["measure"], "gap")
    check("Bihar shortfall is 26%", round(out["state"]["Bihar"] * 100), 26)
    check("Kerala shortfall is 5%", round(out["state"]["Kerala"] * 100), 5)


def t_outliers_are_judged_against_the_table_not_a_threshold():
    """A 40% shortfall is unremarkable where everyone is at 40% and is the story
    where nobody else exceeds 5%. An absolute threshold flags the first and
    misses the second."""
    out = dw.examine(GAP_TABLE)
    flagged = [a["key"] for a in out["anomalies"]]
    check("the outlier is flagged", "Bihar" in flagged, True)
    check("the ordinary rows are not", "Kerala" in flagged or "Assam" in flagged, False)

    uniform = [{"state_ut": s, "sanctioned_budget": "100", "actual_expenditure": "60"}
               for s in ("A", "B", "C", "D", "E", "F")]
    check("a uniformly bad table flags nobody", dw.examine(uniform)["anomalies"], [])


def t_near_total_gap_is_flagged_even_without_peers():
    rows = [{"state_ut": s, "sanctioned_budget": "100", "actual_expenditure": v}
            for s, v in [("A", "98"), ("B", "97"), ("C", "99"), ("D", "96"), ("E", "0")]]
    out = dw.examine(rows)
    flagged = {a["key"]: a for a in out["anomalies"]}
    check("total non-delivery flagged", "E" in flagged, True)
    check("reason says it reads as a decision",
          any("decision" in r for r in flagged["E"]["reasons"]), True)


def t_small_denominators_are_excluded():
    """2 of 3 is not a 67% failure rate in any useful sense, and small
    denominators generate most false anomalies."""
    rows = [{"state_ut": "Tiny", "sanctioned_budget": "3", "actual_expenditure": "1"},
            {"state_ut": "Real", "sanctioned_budget": "500", "actual_expenditure": "480"}]
    out = dw.examine(rows)
    check("tiny row excluded", list(out["state"]), ["Real"])


def t_widest_column_pair_wins():
    """A jail table matched a two-row DG/IG pair before the total-staff columns
    that covered every state. Taking the first match watches the smallest slice."""
    rows = [{"state_ut": s,
             "officers_sanctioned": ("12" if s == "A" else ""),
             "officers_actual": ("10" if s == "A" else ""),
             "total_staff_sanctioned": "500", "total_staff_actual": "400"}
            for s in ("A", "B", "C", "D", "E")]
    out = dw.examine(rows)
    check("chose the pair with more usable rows", out["rows"], 5)
    check("picked the total columns", "total" in out["expected_col"], True)


def t_columns_must_describe_the_same_thing():
    """The check that stops this module inventing stories. Real cases from
    data.gov.in: sanctioned budget 2023-24 was paired against actual
    expenditure 2021-22, and inspectors-sanctioned against
    Director-Generals-actual — reporting 99-100% vacancy across 37 states.
    Confident, arithmetic, and entirely false."""
    check("year mismatch rejected",
          dw._comparable("total_sanctioned_budget___2023_24",
                         "actual_expenditure___2021_22", "sanctioned", "actual"), False)
    check("same year accepted",
          dw._comparable("total_sanctioned_budget___2023_24",
                         "actual_expenditure___2023_24", "sanctioned", "actual"), True)
    check("different ranks rejected",
          dw._comparable("inspector__si___a_s_i____sanctioned",
                         "dg__addl_dg___ig___dig___actual", "sanctioned", "actual"), False)
    check("same rank accepted",
          dw._comparable("inspector__si___a_s_i____sanctioned",
                         "inspector__si___a_s_i____actual", "sanctioned", "actual"), True)
    check("bare columns accepted",
          dw._comparable("sanctioned", "actual", "sanctioned", "actual"), True)


def t_implausible_median_means_mispaired_not_catastrophe():
    """A table where nearly every row shows near-total failure is far more
    likely two mismatched columns than a nationwide collapse. Refusing to watch
    it costs one dataset; believing it costs 37 false candidates that all look
    arithmetically sound."""
    rows = [{"state_ut": s, "posts_sanctioned": "500", "posts_actual": "2"}
            for s in "ABCDEFGHIJ"]
    out = dw.examine(rows)
    check("not watchable", out["watchable"], False)
    check("reason names the likely cause",
          "not the same quantity" in out["why"], True)

    # a genuinely bad but plausible table is still watched
    ok = [{"state_ut": s, "posts_sanctioned": "500", "posts_actual": v}
          for s, v in zip("ABCDEFGHIJ", ["300","320","290","310","280","305","295","315","288","2"])]
    check("plausible table still watched", dw.examine(ok)["watchable"], True)


def t_changes_since_last_poll_are_surfaced():
    """A standing level is context; a move is news."""
    prev = {k: v for k, v in [("Kerala", 0.22), ("Gujarat", 0.71)]}
    out = dw.examine(SHARE_TABLE, previous=prev)
    moved = {c["key"] for c in out["changes"]}
    check("unchanged row not reported", "Kerala" in moved, False)
    prev2 = {"Kerala": 0.80}
    out2 = dw.examine(SHARE_TABLE, previous=prev2)
    check("a big move is reported", [c["key"] for c in out2["changes"]], ["Kerala"])
    check("direction stated", "narrowed" in out2["changes"][0]["reason"], True)


def t_non_accountability_table_is_not_watchable():
    rows = [{"state_ut": "Kerala", "name_of_project": "x", "details": "y"}]
    check("text register not watchable", dw.examine(rows)["watchable"], False)


def t_candidates_quote_the_arithmetic_as_their_excerpt():
    """The grounding rule downstream asks whether a finding is supported by the
    source. Here the numbers ARE the source."""
    out = dw.examine(GAP_TABLE)
    cands = dw.to_candidates(out, "Sanctioned vs actual expenditure", "https://x/1")
    check("a candidate per anomaly", len(cands), len(out["anomalies"]))
    c = cands[0]
    check("excerpt carries the row", "sanctioned" in c["excerpt"].lower(), True)
    check("agreement marked as arithmetic", c["agreement"], "arithmetic")
    check("source url carried", c["source_url"], "https://x/1")


def main():
    print("dataset-watch cases")
    for t in (t_share_table_is_not_read_as_a_gap,
              t_gap_table_measures_what_did_not_arrive,
              t_outliers_are_judged_against_the_table_not_a_threshold,
              t_near_total_gap_is_flagged_even_without_peers,
              t_small_denominators_are_excluded,
              t_widest_column_pair_wins,
              t_columns_must_describe_the_same_thing,
              t_implausible_median_means_mispaired_not_catastrophe,
              t_changes_since_last_poll_are_surfaced,
              t_non_accountability_table_is_not_watchable,
              t_candidates_quote_the_arithmetic_as_their_excerpt):
        t()
    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all dataset-watch cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
