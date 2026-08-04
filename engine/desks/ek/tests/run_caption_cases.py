"""Regression cases for the belief reel's caption guard.

    python -m engine.desks.ek.tests.run_caption_cases

No API key, no database, no network: unlike the gate cases (a judgment test),
this is a plain assertion suite, because `caption_ok` is the mechanical promise
that a reel cannot say — or show — a word the trust gate never passed. If it
ever silently loosens, an on-screen line can contradict the narration under it,
and nothing downstream would catch that.
"""
import sys

from publishing.belief_reel import caption_ok, clause_caption

L_UNIQ = ("What no one disputes is the uniqueness claim: cities, mines, dams, "
          "and highway grids are all more readily detected from orbit.")
L_MOON = ("From the Moon it is flatly impossible: no man-made object is visible "
          "at that distance.")
L_WALL = "It is not true that the Wall is visible from orbit."
L_ASTRO = "Most astronauts, including China's first, say they could not see it."

# (line, caption, expected, why it matters)
CASES = [
    (L_UNIQ, "cities, mines, dams, and highway grids", True,
     "negation lives in a different clause — the caption reverses nothing "
     "(rejecting this cost run #140 a caption)"),
    (L_MOON, "no man-made object is visible", True,
     "keeps the negation of the clause it quotes"),
    (L_MOON, "man-made object is visible", False,
     "THE case this guard exists for: drops the 'no' and says the opposite"),
    (L_MOON, "From the Moon it is flatly impossible", True,
     "a different clause of the same line, complete in itself"),
    (L_WALL, "the Wall is visible from orbit", False,
     "one clause, negation dropped — inverts the sentence"),
    (L_WALL, "It is not true", True, "keeps it"),
    (L_ASTRO, "say they could not see it", True, "faithful span"),
    (L_ASTRO, "astronauts could see it", False,
     "not a contiguous run of the line's words — a paraphrase"),
    (L_ASTRO, "Most astronauts say they could not see it", False,
     "reads faithful, but the words were reordered/joined across a clause; "
     "only a real span may pass"),
    (L_ASTRO, "", False, "empty is not a caption"),
    (L_MOON, "From the Moon it is flatly impossible no man-made object is visible", False,
     "over the word cap — it would render tiny and unreadable"),
]


def main():
    bad = 0
    for line, caption, want, why in CASES:
        got = caption_ok(caption, line)
        ok = got == want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {str(got):5} (want {str(want):5})  "
              f"{caption[:46]!r}\n        {why}")

    # The fallback must always produce something acceptable to the same guard —
    # if it didn't, a rejected model caption would be replaced by an unfaithful
    # one, which is worse than the problem.
    print("\n  fallbacks:")
    for line in (L_UNIQ, L_MOON, L_WALL, L_ASTRO):
        cap = clause_caption(line)
        ok = caption_ok(cap, line)
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {cap!r}")

    print(f"\n{len(CASES) + 4 - bad}/{len(CASES) + 4} caption cases pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
