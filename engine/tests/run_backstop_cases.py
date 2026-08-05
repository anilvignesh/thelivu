"""A signed government PDF you can open is not "single-sourced".

Charter §4.1a, added 2026-08-05. The two-source backstop held run #153 because
the verifier read two tabled CAG reports instead of quoting two newspapers — and
no newspaper had ever reported the earlier year's figure, so the second source
did not exist and never would. Two sources reduce error about the WORLD; they
cannot corroborate what a document SAYS better than the document. When we read
the record ourselves we are the reporter, not an aggregator.

The URL is the whole guard. "Primary" is a self-declared tier a model could
assert about a document it never opened; a link is what lets a reader check us.

    ./venv/bin/python -m engine.tests.run_backstop_cases
"""
from engine.agents.orchestrator import _undersourced_load_bearing   # noqa: E402

PASS, FAIL = [], []
HEAD = ("| Claim | Load-bearing | Verdict | Independent sources | Best tier | Note |\n"
        "|---|---|---|---|---|---|\n")
URL = "https://cag.gov.in/webroot/uploads/report.pdf"


def check(label, got, want, note=""):
    (PASS if got == want else FAIL).append(label)
    print(f"  {'PASS' if got == want else 'FAIL'}  {label}")
    if got != want:
        print(f"        got {got!r}, want {want!r}")
    elif note:
        print(f"        {note}")


def held(*rows):
    return _undersourced_load_bearing(HEAD + "".join(r + "\n" for r in rows))


print("\nthe exemption opens for exactly the right case:")
check("primary + URL passes on one source",
      held(f"| A | yes | Verified | 1 | Primary | {URL} — para 4.5, p.64 |"), [],
      "run #153's actual shape — this is the story that could not be published")

print("\nand for nothing else:")
check("primary WITHOUT a url is still held",
      held("| A | yes | Verified | 1 | Primary | para 4.5, tabled report |"), ["A"],
      "a tier a model asserts about a document nobody can open is worth nothing")
check("a url on a NON-primary tier is still held",
      held(f"| A | yes | Verified | 1 | 2 | {URL} — news write-up |"), ["A"],
      "a link to a newspaper is not a primary record")
check("a url on tier 3 is still held",
      held(f"| A | yes | Verified | 1 | 3 | {URL} |"), ["A"])
check("zero sources, primary + url — still exempt",
      held(f"| A | yes | Verified | 0 | Primary | {URL} |"), [],
      "0 and 1 mean the same thing here: the document is the source")

print("\nthe rest of the backstop is untouched:")
check("two sources always passed", held("| A | yes | Verified | 2 | 2 | two outlets |"), [])
check("one source, no exemption, held", held("| A | yes | Verified | 1 | 2 | one outlet |"), ["A"])
check("not load-bearing is ignored", held("| A | no | Verified | 1 | 2 | colour |"), [])
check("unverified is not this guard's job",
      held("| A | yes | Unverified | 1 | 2 | thin |"), [],
      "'unverified' already holds by its own verdict")
check("failed is not this guard's job", held("| A | yes | Failed | 0 | — | wrong |"), [])

print("\nmixed table — only the undersourced row is named:")
check("three rows, one blocker",
      held(f"| A | yes | Verified | 1 | Primary | {URL} |",
           "| B | yes | Verified | 2 | 2 | corroborated |",
           "| C | yes | Verified | 1 | 2 | single outlet |"), ["C"])

print("\nit can still never falsely block:")
check("no table at all", _undersourced_load_bearing("prose only, no table"), [])
check("empty input", _undersourced_load_bearing(""), [])
check("ragged row is skipped", held("| A | yes |"), [])

print("\n" + "=" * 68)
if FAIL:
    print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
    raise SystemExit(1)
print(f"all {len(PASS)} backstop cases pass")
