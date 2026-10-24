"""The autopost queue alternates article reels and audit reels.

    python -m engine.tests.run_lane_alternation_cases

Pure ordering logic: no database, no network.
"""
import sys

from engine.distribution.sweep import prefer_other_lane

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def item(i, source):
    return ({"id": i, "source": source}, {"id": i})


def ids(c):
    return [p[1]["id"] for p in c]


def main():
    q = [item(1, "animate"), item(2, "animate"), item(3, "The Hindu"), item(4, "animate"), item(5, "Medianama")]
    check("after an audit, the first article goes", ids(prefer_other_lane(q, "audit"))[0], 3)
    check("after an article, the first audit goes", ids(prefer_other_lane(q, "news"))[0], 1)
    check("nothing posted yet keeps the order", ids(prefer_other_lane(q, None)), [1, 2, 3, 4, 5])
    check("only audits left: audit still goes", ids(prefer_other_lane(q[:2], "audit")), [1, 2])
    check("only articles left: article still goes", ids(prefer_other_lane([q[2], q[4]], "news")), [3, 5])
    check("no candidates", prefer_other_lane([], "audit"), [])
    check("nothing is dropped", sorted(ids(prefer_other_lane(q, "audit"))), [1, 2, 3, 4, 5])
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        return 1
    print("all lane alternation cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
