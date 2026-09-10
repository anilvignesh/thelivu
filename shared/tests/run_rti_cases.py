"""RTI drafting and tracking.

    python -m shared.tests.run_rti_cases

No network. Pure rules.

What this is FOR is the mistake that wastes thirty days: an application phrased
as a question. The RTI Act gives access to RECORDS, and a PIO may lawfully
reject "why was no penalty recovered?" as seeking an opinion. The same
information is obtainable by asking for the document that would contain it.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from publishing import rti                       # noqa: E402
from shared.db import (                          # noqa: E402
    init_db, save_rti, mark_rti_filed, close_rti, rti_requests, rti_overdue,
)

_fails = []


def _fresh():
    """Each persistence case starts from an empty table — they share one
    throwaway SQLite file, and rows carrying over made `[0]` pick up a previous
    test's row."""
    init_db()
    from shared.db import _conn
    conn = _conn()
    try:
        conn.cursor().execute("DELETE FROM rti_requests")
        conn.commit()
    finally:
        conn.close()


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


RECORDS = [
    "a copy of each recovery notice issued to contractors under the penalty "
    "clause between 1 April 2023 and 31 March 2026",
    "a statement showing, project-wise, penalties imposed and amounts recovered",
]


# --------------------------------------------------------------------------
# the mistake that costs thirty days
# --------------------------------------------------------------------------

def t_questions_are_refused_at_draft_time():
    for bad in ["why was no penalty recovered from the contractor",
                "whether the ministry considers the recovery adequate",
                "explain the reason for the shortfall",
                "please state if action was taken"]:
        try:
            rti.draft("MoRTH", [bad], "Penalties")
            check(f"rejected: {bad[:34]}", False, True)
        except rti.RTIDraftError as e:
            check(f"rejected: {bad[:34]}", True, True)
            check("error teaches the fix", "rather than 'why was" in str(e), True)
            break


def t_record_requests_are_accepted():
    out = rti.draft("Ministry of Road Transport and Highways", RECORDS,
                    "Highway penalty recovery")
    check("application produced", "RIGHT TO INFORMATION ACT, 2005" in out, True)
    check("addressed to a PIO", "Public Information Officer" in out, True)
    check("records numbered", "1. a copy of each recovery notice" in out, True)


def t_authority_is_required():
    try:
        rti.draft("  ", RECORDS, "x")
        check("blank authority rejected", False, True)
    except rti.RTIDraftError as e:
        check("blank authority rejected", True, True)
        check("says why", "specific PIO" in str(e), True)


def t_draft_invokes_the_sections_that_protect_the_request():
    """6(3) forces a transfer rather than a rejection when the record sits
    elsewhere; 7(8) forces a refusal to name its exemption and the appellate
    authority — which is what makes a refusal appealable, and reportable."""
    out = rti.draft("MoRTH", RECORDS, "x")
    check("transfer clause cited", "Section 6(3)" in out, True)
    check("exemption must be stated", "Section 8" in out, True)
    check("appellate authority demanded", "First Appellate Authority" in out, True)


# --------------------------------------------------------------------------
# clocks
# --------------------------------------------------------------------------

def t_deadlines_follow_the_act():
    d = rti.due_dates("2026-09-10T00:00:00")
    check("reply in 30 days", d["reply_by"], "2026-10-10")
    check("first appeal 30 days after that", d["first_appeal_by"], "2026-11-09")
    check("second appeal 90 days after that", d["second_appeal_by"], "2027-02-07")


def t_silence_becomes_a_deemed_refusal():
    """Not 'still waiting'. It starts the appeal clock, and an authority that
    lets the clock run out has itself done something worth reporting."""
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    check("31 days of silence is a deemed refusal",
          rti.status_for("2026-09-10T00:00:00", now=now), rti.DEEMED_REFUSED)
    check("inside the window is still filed",
          rti.status_for((now - timedelta(days=5)).isoformat(), now=now), rti.FILED)
    check("a reply is a reply",
          rti.status_for("2026-09-10T00:00:00", replied=True, now=now), rti.ANSWERED)


# --------------------------------------------------------------------------
# a refusal is not a dead end
# --------------------------------------------------------------------------

def t_refusals_and_silence_are_themselves_leads():
    lead, why = rti.is_lead(rti.DEEMED_REFUSED)
    check("silence is a lead", lead, True)
    check("names the statutory failure", "30 days" in why, True)

    lead, why = rti.is_lead(rti.REFUSED, exemption_cited="Section 8(1)(d)")
    check("refusal is a lead", lead, True)
    check("the exemption claimed is the story", "8(1)(d)" in why, True)

    lead, _ = rti.is_lead(rti.ANSWERED)
    check("an answer is not itself a lead", lead, False)


def t_gap_suggestion_is_conservative():
    s = rti.suggest_from_gap("which highway penalties were waived", "NHAI")
    check("authority carried", s["authority"], "NHAI")
    check("asks for records not answers",
          all(not rti._QUESTION_OPENERS.match(i) for i in s["items"]), True)
    check("warns that breadth gets refused", "refused as such" in s["note"], True)


# --------------------------------------------------------------------------
# persistence — a tracker that forgets is not a tracker
# --------------------------------------------------------------------------

def t_request_persists_and_tracks_its_clock():
    _fresh()
    body = rti.draft("MoRTH", RECORDS, "Highway penalty recovery")
    rid = save_rti("MoRTH", "Highway penalty recovery", body,
                   gap_claim="project-wise recovery breakdown")
    check("saved as drafted", rti_requests()[0]["status"], rti.DRAFTED)

    d = rti.due_dates("2026-09-10T00:00:00")
    mark_rti_filed(rid, "2026-09-10T00:00:00", d["reply_by"])
    row = rti_requests()[0]
    check("marked filed", row["status"], rti.FILED)
    check("deadline stored", str(row["reply_by"])[:10], "2026-10-10")


def t_overdue_surfaces_silence_as_deemed_refusal():
    """Leaving these as 'filed' forever is exactly how a deemed refusal — which
    is appealable, and a story — gets missed."""
    _fresh()
    body = rti.draft("NHAI", RECORDS, "Recovery notices")
    rid = save_rti("NHAI", "Recovery notices", body)
    mark_rti_filed(rid, "2026-09-10T00:00:00", "2026-10-10")

    check("not overdue before the deadline", rti_overdue("2026-10-01"), [])
    overdue = rti_overdue("2026-10-20")
    check("overdue after it", len(overdue), 1)

    status = rti.status_for("2026-09-10T00:00:00",
                            now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    lead, why = rti.is_lead(status)
    close_rti(overdue[0]["id"], status, outcome_note=why, lead_flagged=lead)
    row = rti_requests()[0]
    check("closed as deemed refusal", row["status"], rti.DEEMED_REFUSED)
    check("flagged as a lead", bool(row["lead_flagged"]), True)


def t_refusal_records_the_exemption_claimed():
    """The exemption claimed is a checkable fact, and often the story."""
    _fresh()
    rid = save_rti("PIO", "x", rti.draft("PIO", RECORDS, "x"))
    mark_rti_filed(rid, "2026-09-10T00:00:00", "2026-10-10")
    lead, why = rti.is_lead(rti.REFUSED, exemption_cited="Section 8(1)(d)")
    close_rti(rid, rti.REFUSED, exemption_cited="Section 8(1)(d)",
              outcome_note=why, lead_flagged=lead)
    row = rti_requests()[0]
    check("exemption stored", row["exemption_cited"], "Section 8(1)(d)")
    check("refusal is a lead", bool(row["lead_flagged"]), True)


def main():
    print("rti cases")
    for t in (t_questions_are_refused_at_draft_time,
              t_record_requests_are_accepted,
              t_authority_is_required,
              t_draft_invokes_the_sections_that_protect_the_request,
              t_deadlines_follow_the_act,
              t_silence_becomes_a_deemed_refusal,
              t_refusals_and_silence_are_themselves_leads,
              t_gap_suggestion_is_conservative,
              t_request_persists_and_tracks_its_clock,
              t_overdue_surfaces_silence_as_deemed_refusal,
              t_refusal_records_the_exemption_claimed):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all rti cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
