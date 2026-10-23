"""Pre-publish re-verification gate — every branch of the decision tree.

    python -m shared.tests.run_reverify_cases

No network, no model. The agent is a fake that returns a canned block (or raises).
What this is FOR: docs/prepublish-gate.md. The gate fails CLOSED — every path where
the agent could not do its job must land on HELD, never CLEAR — and these cases
pin that, because a regression here silently publishes unverified journalism.
"""
import sys

from engine.distribution import reverify as rv

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))


GOOD_DRAFT = ("# Delhi struck names off its rolls\n\nThe commission removed 47.5 lakh names.\n\n"
              "Confidence: Confirmed\n\nSources: https://eci.gov.in/doc\n")


def block(rows, person="NO"):
    body = "\n".join(f"| {i} | {t} | {v} | {u} | {n} |" for i, (t, v, u, n) in enumerate(rows, 1))
    return (f"REVERIFY-RESULT\nNAMES-PERSON-ALLEGATION: {person}\n"
            "| # | Claim | Verdict | Source URL | Note |\n|---|---|---|---|---|\n"
            f"{body}\nEND-REVERIFY")


OK_ROW = ("47.5 lakh names removed", "CONFIRMED", "https://eci.gov.in/doc", "")


def route(draft, text, legal=False):
    return rv.decide(draft, legal, rv.parse_result(text)).route


# ── the tree ─────────────────────────────────────────────────────────────────

def t_clear_when_every_claim_is_confirmed_with_a_url():
    check("all confirmed -> clear", route(GOOD_DRAFT, block([OK_ROW, OK_ROW])), rv.CLEAR)


def t_contradicted_blocks():
    check("contradicted -> blocked",
          route(GOOD_DRAFT, block([OK_ROW, ("2 storeys", "CONTRADICTED", "https://x.in", "says ground-plus-one")])),
          rv.BLOCKED)


def t_contradicted_beats_unconfirmed():
    check("contradicted outranks unsupported",
          route(GOOD_DRAFT, block([("a", "UNSUPPORTED", "", ""), ("b", "CONTRADICTED", "https://x.in", "")])),
          rv.BLOCKED)


def t_unsupported_and_could_not_check_hold():
    check("unsupported -> held", route(GOOD_DRAFT, block([OK_ROW, ("a", "UNSUPPORTED", "", "")])), rv.HELD)
    check("could not check -> held", route(GOOD_DRAFT, block([OK_ROW, ("a", "COULD_NOT_CHECK", "", "")])), rv.HELD)


def t_confirmed_without_a_url_is_not_confirmed():
    check("CONFIRMED + no URL -> held", route(GOOD_DRAFT, block([("a", "CONFIRMED", "", "")])), rv.HELD)
    check("CONFIRMED + junk source -> held", route(GOOD_DRAFT, block([("a", "CONFIRMED", "trust me", "")])), rv.HELD)


def t_named_person_allegation_goes_to_a_human_even_if_all_confirmed():
    check("person + allegation -> held", route(GOOD_DRAFT, block([OK_ROW], person="YES")), rv.HELD)


def t_legal_flag_goes_to_a_human():
    check("LEGAL-FLAG YES -> held", route(GOOD_DRAFT, block([OK_ROW]), legal=True), rv.HELD)


def t_named_person_switch_can_be_turned_off():
    old = rv.ROUTE_NAMED_PERSON_TO_HUMAN
    rv.ROUTE_NAMED_PERSON_TO_HUMAN = False
    try:
        check("switch off -> clear", route(GOOD_DRAFT, block([OK_ROW], person="YES"), legal=True), rv.CLEAR)
    finally:
        rv.ROUTE_NAMED_PERSON_TO_HUMAN = old


def t_minor_tolerance_is_honoured():
    old = rv.MINOR_TOLERANCE
    rv.MINOR_TOLERANCE = 1
    try:
        check("1 unconfirmed within tolerance -> clear", route(GOOD_DRAFT, block([OK_ROW, ("a", "UNSUPPORTED", "", "")])), rv.CLEAR)
        check("2 unconfirmed exceeds it -> held",
              route(GOOD_DRAFT, block([("a", "UNSUPPORTED", "", ""), ("b", "UNSUPPORTED", "", "")])), rv.HELD)
    finally:
        rv.MINOR_TOLERANCE = old


# ── fail closed ──────────────────────────────────────────────────────────────

def t_agent_failure_holds_never_clears():
    check("no result -> held", rv.decide(GOOD_DRAFT, False, None).route, rv.HELD)


def t_unparseable_output_holds():
    for name, text in [("empty", ""), ("prose", "Looks fine to me!"), ("no end marker", "REVERIFY-RESULT\nNAMES-PERSON-ALLEGATION: NO"),
                       ("missing allegation line", "REVERIFY-RESULT\n| 1 | a | CONFIRMED | https://x | |\nEND-REVERIFY")]:
        check(f"{name} -> held", route(GOOD_DRAFT, text), rv.HELD)


def t_unknown_verdict_word_holds():
    check("verdict 'LIKELY_TRUE' -> held", route(GOOD_DRAFT, block([("a", "LIKELY_TRUE", "https://x", "")])), rv.HELD)


def t_zero_claims_is_not_a_pass():
    check("no claims -> held", route(GOOD_DRAFT, block([])), rv.HELD)


# ── artifact defects block before the agent's word is even read ──────────────

def t_artifact_defects_block():
    clear_block = block([OK_ROW])
    check("placeholder -> blocked", route(GOOD_DRAFT + "\n<the spoken opening line>\n", clear_block), rv.BLOCKED)
    check("chatbot leak -> blocked", route(GOOD_DRAFT + "\nLet me know if you want edits.\n", clear_block), rv.BLOCKED)
    check("process narration -> blocked", route(GOOD_DRAFT + "\nThis piece replaces the earlier one.\n", clear_block), rv.BLOCKED)
    no_conf = GOOD_DRAFT.replace("Confidence: Confirmed\n\n", "")
    check("no confidence label -> blocked", route(no_conf, clear_block), rv.BLOCKED)
    no_src = GOOD_DRAFT.replace("Sources: https://eci.gov.in/doc\n", "")
    check("no sources block -> blocked", route(no_src, clear_block), rv.BLOCKED)
    check("empty draft -> blocked", route("", clear_block), rv.BLOCKED)
    check("defect wins even with no agent result", rv.decide(GOOD_DRAFT + "<the opening>", False, None).route, rv.BLOCKED)


def t_ordinary_prose_is_not_a_defect():
    prose = GOOD_DRAFT + "\nThe order cites <5 and >10 storeys in two schedules, as filed.\n"
    check("a less-than/greater-than in prose is fine", rv.artifact_defects(prose), [])


# ── gate() wiring: stored verdicts, one announcement, kill switch ────────────

def t_gate_runs_the_agent_once_and_announces_once():
    import shared.db as db
    stored = {}
    announced = []
    calls = []
    # swap persistence + notification for in-memory fakes
    real_set, real_tell = db.set_run_reverify, rv._tell_anil
    db.set_run_reverify = lambda rid, v, rep, sha=None: stored.update(rid=rid, v=v, sha=sha)
    rv._tell_anil = lambda run, dec, already_published: announced.append(dec.route)
    real_enabled = rv.enabled
    rv.enabled = lambda: True
    try:
        run = {"id": 7, "draft_text": GOOD_DRAFT, "review_text": "LEGAL-FLAG: NO", "status": "pending_human"}
        runner = lambda draft, rid: (calls.append(1), rv.parse_result(block([OK_ROW, ("a", "UNSUPPORTED", "", "")])))[1]
        check("held on first look", rv.gate(run, runner=runner), rv.HELD)
        check("agent ran once", len(calls), 1)
        check("Anil told once", announced, [rv.HELD])
        # next tick: the verdict is on the row
        run.update(reverify_verdict=stored["v"], reverify_draft_sha=stored["sha"])
        check("held run needs no agent", rv.needs_agent(run), False)
        check("held stays held", rv.gate(run, runner=runner), rv.HELD)
        check("no re-run, no re-announce", (len(calls), announced), (1, [rv.HELD]))
        # the draft changes -> the verdict is stale
        run["draft_text"] = GOOD_DRAFT + "\nA new paragraph.\n"
        check("edited draft needs the agent again", rv.needs_agent(run), True)
        # Anil approves -> never second-guessed
        run.update(reverify_verdict=rv.HUMAN_APPROVED)
        check("human_approved passes without the agent", (rv.needs_agent(run), rv.gate(run, runner=runner)), (False, rv.HUMAN_APPROVED))
        check("agent still ran only once", len(calls), 1)
    finally:
        db.set_run_reverify, rv._tell_anil, rv.enabled = real_set, real_tell, real_enabled


def t_gate_raising_agent_is_a_hold():
    import shared.db as db
    real_set, real_tell, real_enabled = db.set_run_reverify, rv._tell_anil, rv.enabled
    db.set_run_reverify = lambda *a, **k: None
    rv._tell_anil = lambda *a, **k: None
    rv.enabled = lambda: True
    try:
        # run_agent() itself swallows provider errors into None; exercise that seam
        import engine.agents.skill_runner as sr
        real_run = sr.run_skill
        def boom(*a, **k): raise RuntimeError("gemini quota")
        sr.run_skill = boom
        try:
            check("provider error -> None", rv.run_agent(GOOD_DRAFT, 1), None)
            run = {"id": 9, "draft_text": GOOD_DRAFT, "review_text": "", "status": "pending_human"}
            check("provider error -> held", rv.gate(run), rv.HELD)
        finally:
            sr.run_skill = real_run
    finally:
        db.set_run_reverify, rv._tell_anil, rv.enabled = real_set, real_tell, real_enabled


def t_kill_switch_restores_old_behaviour():
    real = rv.enabled
    rv.enabled = lambda: False
    try:
        run = {"id": 1, "draft_text": "", "status": "pending_human"}
        check("disabled -> clear, no agent", (rv.needs_agent(run), rv.gate(run)), (False, rv.CLEAR))
    finally:
        rv.enabled = real


def t_sweep_helper_skips_held_and_defers_on_budget():
    from engine.distribution import sweep
    real_needs, real_gate = rv.needs_agent, rv.gate
    verdicts = {1: rv.HELD, 2: rv.BLOCKED, 3: rv.CLEAR}
    rv.needs_agent = lambda run: run.get("fresh", False)
    rv.gate = lambda run, runner=None: verdicts[run["id"]]
    try:
        ranked = [({"id": i}, {"id": 100 + i}) for i in (1, 2, 3)]
        picked, deferred = sweep._first_cleared(ranked, 2)
        check("skips held+blocked, takes the cleared one", ([r["id"] for r, _ in picked], deferred), ([3], False))
        fresh = [({"id": 1, "fresh": True}, {}), ({"id": 3, "fresh": True}, {})]
        picked, deferred = sweep._first_cleared(fresh, 1)
        check("budget exhausted -> deferred, nothing posted", (picked, deferred), ([], True))
    finally:
        rv.needs_agent, rv.gate = real_needs, real_gate


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            print(name)
            fn()
    print()
    if _fails:
        print(f"{len(_fails)} FAILED: {_fails}")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
