"""Run the premise-check regression cases and report verdict vs expectation.

    python -m engine.desks.ek.tests.run_gate_cases          # all cases
    python -m engine.desks.ek.tests.run_gate_cases banana-republic guatemala-1954

Needs the same env as the engine (ANTHROPIC_API_KEY, DATABASE_URL). Pull them
from Railway the way command_center/run.sh does — the local .env keys drift.

This is a judgment test, not an assertion suite: the verdict is checked
automatically, but the `also` notes are for a human reading the output. A gate
that returns the right verdict for the wrong reason is still broken.
"""
import sys
from pathlib import Path

import yaml

from engine.agents.skill_runner import run_skill

CASES = Path(__file__).parent / "gate_cases.yaml"


def _verdict(out):
    for line in out.splitlines():
        if line.strip().upper().startswith("VERDICT:"):
            return line.split(":", 1)[1].strip().upper()
    return "(no VERDICT line)"


def main(argv):
    cases = yaml.safe_load(CASES.read_text())["cases"]
    if argv:
        cases = [c for c in cases if c["id"] in argv]
        if not cases:
            print(f"no case matched {argv}")
            return 2

    passed, failed, gaps = [], [], []
    for c in cases:
        print("=" * 72)
        print(f"CASE {c['id']}  — expect {c['expect']}")
        print("-" * 72)
        try:
            out = run_skill("ek:premise-check",
                            f"CANDIDATE RECEIVED BELIEF:\n\n{c['belief'].strip()}",
                            max_tokens=1024, topic=c["id"])
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((c["id"], f"raised {type(e).__name__}"))
            continue

        got = _verdict(out)
        ok = got == c["expect"]
        # A `known_gap` case is a calibration boundary we have decided NOT to
        # chase — the gate disagrees with the expectation on a genuinely
        # borderline candidate, and tightening the prompt until it complies
        # would loosen a floor that is working on the clear cases. It stays in
        # the suite as a sensitivity marker: if it ever flips, that is real
        # signal about a prompt edit, in either direction.
        if ok:
            passed.append((c["id"], got))
        elif c.get("known_gap"):
            gaps.append((c["id"], got))
        else:
            failed.append((c["id"], got))
        print(out.strip())
        print("-" * 72)
        label = "PASS" if ok else ("KNOWN GAP" if c.get("known_gap") else "FAIL")
        print(f"  {label}: got {got}, expected {c['expect']}")
        if c.get("also"):
            print(f"  check by eye: {c['also'].strip()}")
        print()

    print("=" * 72)
    total = len(passed) + len(failed) + len(gaps)
    print(f"{len(passed)}/{total} verdicts as expected"
          + (f"  ({len(gaps)} known calibration gap(s))" if gaps else ""))
    for cid, got in gaps:
        print(f"  KNOWN GAP {cid}: {got} — open editorial question, not a regression")
    for cid, got in failed:
        print(f"  FAIL {cid}: {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
