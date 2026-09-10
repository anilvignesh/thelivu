"""Evidence depth and stopping rules.

    python -m shared.tests.run_evidence_cases

No network, no database. Pure rules.

What this is FOR is the two mistakes that look fine in a transcript:
publishing a named allegation that rests on someone else's reporting, and
recording "we stopped looking" as if it meant "there is nothing there".
"""
import sys

from shared import evidence as ev

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


# --------------------------------------------------------------------------
# the bar rises with what an error costs
# --------------------------------------------------------------------------

def t_supporting_colour_may_rest_on_reporting():
    c = ev.Claim("A contractor was fined in Gujarat.", ev.SUPPORTING, ev.SECONDARY)
    check("supporting + secondary passes", c.shortfall(), None)


def t_spine_claim_needs_primary():
    c = ev.Claim("Kerala has nine of the fifty-five failures.", ev.SPINE, ev.SECONDARY)
    s = c.shortfall()
    check("spine + secondary blocked", s is not None, True)
    check("blocker names the requirement", "needs a primary" in (s or ""), True)


def t_hook_needs_primary():
    """The cold open is the most screenshotted line and travels furthest from
    its context."""
    check("hook + secondary blocked",
          ev.Claim("Rs 2,732 crore imposed.", ev.HOOK, ev.SECONDARY).shortfall() is not None,
          True)
    check("hook + primary passes",
          ev.Claim("Rs 2,732 crore imposed.", ev.HOOK, ev.PRIMARY).shortfall(), None)


def t_naming_someone_needs_primary_AND_their_side():
    """The failure that does real harm and is hardest to undo after the fact."""
    bare = ev.Claim("KNR was not penalised.", ev.NAMED, ev.PRIMARY)
    s = bare.shortfall()
    check("named + primary but no response is blocked", s is not None, True)
    check("blocker names the missing side", "response" in (s or ""), True)

    withside = ev.Claim("KNR was not penalised.", ev.NAMED, ev.PRIMARY,
                        dispute_noted=True)
    check("named + primary + dispute noted passes", withside.shortfall(), None)

    secondary = ev.Claim("KNR was not penalised.", ev.NAMED, ev.SECONDARY,
                         dispute_noted=True)
    check("named on reporting alone still blocked",
          secondary.shortfall() is not None, True)


def t_unsourced_never_passes():
    for tier in ev.TIERS:
        c = ev.Claim("x", tier, ev.UNSOURCED, response_noted=True, dispute_noted=True)
        check(f"unsourced blocked at {tier}", c.shortfall() is not None, True)


def t_assess_reports_every_blocker():
    ready, blockers = ev.assess([
        ev.Claim("ok", ev.SUPPORTING, ev.SECONDARY),
        ev.Claim("spine", ev.SPINE, ev.SECONDARY),
        ev.Claim("named", ev.NAMED, ev.SECONDARY),
    ])
    check("not publishable", ready, False)
    check("both blockers reported", len(blockers), 2)


# --------------------------------------------------------------------------
# stopping: "we ended" vs "we were stopped"
# --------------------------------------------------------------------------

def t_saturation_is_conclusive():
    check("saturated ends it", ev.is_conclusive(ev.SATURATED), True)
    check("all-spine-primary ends it", ev.is_conclusive(ev.ALL_SPINE_PRIMARY), True)


def t_being_blocked_is_not_evidence_of_absence():
    """robots-disallowed, 403 and JS-rendered tell us nothing about whether the
    evidence exists. Treating them as conclusive writes a capability gap up as
    a finished investigation."""
    check("blocked is not conclusive", ev.is_conclusive(ev.BLOCKED), False)
    check("budget exhausted is not conclusive", ev.is_conclusive(ev.BUDGET), False)


def t_report_flags_a_non_conclusive_stop():
    out = ev.report(
        [ev.Claim("ok", ev.SUPPORTING, ev.SECONDARY)],
        ev.Stop(ev.BLOCKED, "rajyasabha.nic.in disallows this crawler",
                handoff="open it in a browser"))
    check("stop is labelled STOPPED not ENDED", "STOPPED" in out, True)
    check("absence warning present", "not evidence of absence" in out, True)
    check("handoff surfaced", "browser" in out, True)


def t_conclusive_stop_reads_as_ended():
    out = ev.report([ev.Claim("ok", ev.SUPPORTING, ev.SECONDARY)],
                    ev.Stop(ev.SATURATED, "two rounds, no new load-bearing fact"))
    check("reads as ENDED", "ENDED" in out, True)
    check("no absence warning", "not evidence of absence" in out, False)


def t_unknown_stop_reason_rejected():
    try:
        ev.Stop("gave_up")
        check("unknown stop reason rejected", False, True)
    except ValueError:
        check("unknown stop reason rejected", True, True)


# --------------------------------------------------------------------------
# escalation overrides the budget
# --------------------------------------------------------------------------

def t_escalations_explain_themselves():
    got = dict(ev.escalations([ev.CONFLICTING_FIGURES, ev.NAMING_SOMEONE]))
    check("both triggers returned", len(got), 2)
    check("conflict tells you not to pick the striking one",
          "more striking" in got[ev.CONFLICTING_FIGURES], True)
    check("naming demands both", "their side" in got[ev.NAMING_SOMEONE], True)


def t_two_ways_trigger_cites_the_precedent():
    got = dict(ev.escalations([ev.FIGURE_USED_TWO_WAYS]))
    check("BBMP precedent cited", "46,300" in got[ev.FIGURE_USED_TWO_WAYS], True)


def t_unknown_triggers_ignored():
    check("unknown trigger dropped", ev.escalations(["vibes"]), [])


# --------------------------------------------------------------------------
# the live draft, scored by its own rule
# --------------------------------------------------------------------------

def t_the_nh_draft_is_not_yet_publishable():
    """Encodes the actual NH penalty-gap draft. It must fail on exactly the two
    claims identified by hand: the 55-failures split carrying Chapter 2, and
    the KNR chain that names a company."""
    claims = [
        ev.Claim("Rs 2,732cr imposed, Rs 780cr recovered", ev.HOOK, ev.PRIMARY,
                 source="LS Unstarred Q843, 23 Jul 2026"),
        ev.Claim("527 delayed projects; Kerala 11", ev.SPINE, ev.PRIMARY,
                 source="LS Unstarred Q843 annexure"),
        ev.Claim("55 failures since 2014; Kerala 9", ev.SPINE, ev.SECONDARY,
                 source="press report of MoRTH reply"),
        ev.Claim("Rs 119cr penalty, NH-46 Madhya Pradesh", ev.SUPPORTING, ev.SECONDARY),
        ev.Claim("11 officers removed", ev.SUPPORTING, ev.SECONDARY),
        ev.Claim("KNR debarred; RTI says no penalty levied, against NHAI's own rule",
                 ev.NAMED, ev.SECONDARY, dispute_noted=True),
    ]
    ready, blockers = ev.assess(claims)
    check("draft not publishable", ready, False)
    check("exactly two blockers", len(blockers), 2)
    check("55-failures split flagged",
          any("55 failures" in b for b in blockers), True)
    check("KNR chain flagged", any("KNR" in b for b in blockers), True)
    check("primary-sourced spine not flagged",
          any("527" in b for b in blockers), False)


def main():
    print("evidence cases")
    for t in (t_supporting_colour_may_rest_on_reporting,
              t_spine_claim_needs_primary,
              t_hook_needs_primary,
              t_naming_someone_needs_primary_AND_their_side,
              t_unsourced_never_passes,
              t_assess_reports_every_blocker,
              t_saturation_is_conclusive,
              t_being_blocked_is_not_evidence_of_absence,
              t_report_flags_a_non_conclusive_stop,
              t_conclusive_stop_reads_as_ended,
              t_unknown_stop_reason_rejected,
              t_escalations_explain_themselves,
              t_two_ways_trigger_cites_the_precedent,
              t_unknown_triggers_ignored,
              t_the_nh_draft_is_not_yet_publishable):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all evidence cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
