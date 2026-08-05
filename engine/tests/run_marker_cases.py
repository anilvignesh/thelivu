"""A decision wrapped in asterisks is still a decision.

The 2026-08-04 CAG topic was lost here, twice. topic-intake decided PROCEED and
said so — as `- Decision: **PROCEED**` — and the marker regex
`Decision:\\s*(PROCEED|PARK|DECLINE)` did not match, because `\\s*` cannot cross
the two asterisks. The run raised StructuredOutputError and died. A hand-run of
the identical prompt passed, because that time the model happened not to bold it:
the failure is stochastic markdown, not a model that failed to decide.

`_M_GATE` had already been hand-patched with `\\**` at some earlier point, so this
had been hit before and fixed for one marker instead of all of them. MARK() is
that fix generalised.

    ./venv/bin/python -m engine.tests.run_marker_cases
"""
import re

from engine.agents.skill_runner import MARK                    # noqa: E402
from engine.agents.orchestrator import (_M_DECISION, _M_GATE,   # noqa: E402
                                        _M_SELECTED, _M_VERDICT, _M_CAROUSEL)
from engine.desks.ek.pipeline import (_M_GATE as EK_GATE,       # noqa: E402
                                      _M_VERDICT as EK_VERDICT)

PASS, FAIL = [], []
F = re.IGNORECASE | re.MULTILINE


def check(label, got, want, note=""):
    (PASS if got == want else FAIL).append(label)
    print(f"  {'PASS' if got == want else 'FAIL'}  {label}")
    if got != want:
        print(f"        got {got!r}, want {want!r}")
    elif note:
        print(f"        {note}")


def val(pat, text):
    m = re.search(pat, text, F)
    return m.group(1) if m else None


print("\nthe shape that actually lost the CAG story:")
check("- Decision: **PROCEED**", val(_M_DECISION, "- Decision: **PROCEED**"), "PROCEED",
      "this exact string is in pending_topics #49's stored reply")

print("\nevery emphasis shape a model reaches for:")
for text, want in [("- Decision: PROCEED", "PROCEED"),
                   ("**Decision:** PARK", "PARK"),
                   ("Decision: *DECLINE*", "DECLINE"),
                   ("Decision:  `PROCEED`", "PROCEED"),
                   ("Decision:\n**PARK**", "PARK"),
                   ("- **Decision**: **PROCEED**", None)]:
    got = val(_M_DECISION, text)
    check(repr(text), got, want,
          "emphasis INSIDE the label is a different shape; not claimed to work"
          if want is None else "")

print("\nthe other markers get the same tolerance:")
check("trust gate bolded", val(_M_GATE, "Trust gate: **KILL**"), "KILL")
check("selected lead bolded", val(_M_SELECTED, "SELECTED_LEAD: **12**"), "12")
check("selected lead NONE", val(_M_SELECTED, "SELECTED_LEAD: `NONE`"), "NONE")
check("news verdict bolded", val(_M_VERDICT, "VERDICT: **DROP**"), "DROP")
check("ek gate bolded", val(EK_GATE, "GATE: **READY-FOR-HUMAN**"), "READY-FOR-HUMAN")
check("ek verdict bolded", val(EK_VERDICT, "VERDICT: **PURSUE-B**"), "PURSUE-B")
check("a bolded slide 1 still parses",
      bool(re.search(_M_CAROUSEL, "**SLIDE 1:** The claim", F)), True)

print("\nthe guards MUST still hold — a marker is not prose:")
check("no bare value without the label", val(_M_DECISION, "PROCEED"), None)
check("a hedge is not a decision", val(_M_DECISION, "Decision: maybe PROCEED"), None,
      "the gap class is emphasis + whitespace, never arbitrary words")
check("a different label does not match",
      val(_M_DECISION, "I will decide: PROCEED later"), None)
check("an invalid value does not match", val(_M_DECISION, "Decision: **MAYBE**"), None)
check("ek gate rejects a news value", val(EK_GATE, "GATE: **PURSUE-A**"), None)

print("\nMARK builds what it says:")
check("shape", MARK("X", "A|B"), r"X:[*_`\s]*(A|B)")

print("\n" + "=" * 68)
if FAIL:
    print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
    raise SystemExit(1)
print(f"all {len(PASS)} marker cases pass")
