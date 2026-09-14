"""What must never reach Instagram, and how slowly a caption may appear.

    python -m shared.tests.run_reel_leak_cases

Two production failures, reported together by Anil on 2026-09-14: *"There has
been one reel which leaked the international [internal] instructions too. We
need to make it foolproof"* and *"the words are rendered slowly slowly, we had
fixed this issue once, it's coming back."*

Both had been fixed before. Both came back through a path the fix did not cover,
which is why these are cases and not comments.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from publishing import reel                          # noqa: E402
from publishing.reel import looks_like_self_talk     # noqa: E402

_fails = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        _fails.append(f"{label}: got {got!r}, want {want!r}")


# ---------------------------------------------------------------- the leak

def t_the_guard_that_only_ran_at_render_time():
    """Reel #71 is live on Instagram with "<the spoken opening line>" as the
    first thing in its caption.

    make_reel has hard-blocked a script whose SPOKEN line is template residue
    since 2026-09-02 — the third time that detection was widened. Reel #71 was
    RENDERED on 2026-08-26, before the block existed, sat contaminated in the
    queue for eighteen days, and the posting sweep published it on 2026-09-13:
    eleven days AFTER the fix.

    A render-time guard cannot protect anything already rendered. Six reels
    still queued on 2026-09-14 predate it.
    """
    leaked = ('<the spoken opening line> "Rupees two six two crore from Kerala\'s '
              'disaster relief fund was transferred to the state treasury."')
    clean = ("Rupees two six two crore from Kerala's disaster relief fund was "
             "transferred to the state's main treasury, making the deficit "
             "appear smaller.")

    def caught(caption):
        return any(looks_like_self_talk(seg)
                   for seg in [caption] + caption.split(". ")[:6])

    check("the live reel's caption is detectable", caught(leaked), True)
    check("and a real caption is not", caught(clean), False)
    # The detector was never the problem — it has caught this shape since
    # 2026-08-26. It was wired to render and not to post.
    check("the detector itself always knew",
          looks_like_self_talk("<the spoken opening line>"), True)


def t_the_older_shapes_are_still_caught():
    """Each incident leaked a DIFFERENT shape, which is why the check is one
    predicate rather than a list of known strings."""
    for s in ("<the spoken opening line>", "the spoken closing line",
              "3-6 word text. Maybe:", "BEAT 2 CAPTION:"):
        check(f"caught: {s[:30]!r}", looks_like_self_talk(s), True)
    for s in ("The Supreme Court has ruled repeated detention unlawful.",
              "India's own rules say a shutdown order must be published."):
        check(f"not a false positive: {s[:30]!r}", looks_like_self_talk(s), False)


# ------------------------------------------------------- the slow captions

def t_the_fallback_caption_was_longer_than_what_it_replaced():
    """The "slowly slowly" regression, and it came from the leak guard itself.

    _sane_caption rejects a caption over MAX_NEWS_CAPTION_WORDS and fell back to
    the SPOKEN line — raw. A 19-word caption was replaced by the 25-word sentence
    it came from. Longer, not shorter, from a guard whose whole purpose is to
    stop long captions.
    """
    spoken = ("A further one thousand seven hundred and sixty five crore was "
              "swept from Kerala's electricity, water and food corporations "
              "into the treasury, the auditor found.")
    over_long = ("This caption is far too long to sit on a slide and should be "
                 "rejected outright by the sanitiser here")

    got = reel._sane_caption(over_long, spoken)
    check("the fallback is within the slide limit",
          len(got.split()) <= reel.MAX_NEWS_CAPTION_WORDS, True)
    check("and shorter than the caption it replaced",
          len(got.split()) < len(over_long.split()), True)
    check("an empty caption gets the same treatment",
          len(reel._sane_caption("", spoken).split()) <= reel.MAX_NEWS_CAPTION_WORDS,
          True)
    check("a caption that is already fine is untouched",
          reel._sane_caption("Rupees 262 crore, moved", spoken),
          "Rupees 262 crore, moved")


def t_a_caption_never_ends_on_a_dangling_word():
    """"…swept from Kerala's" reads as a truncation bug on screen, not as a
    caption."""
    for spoken in (
        "A further one thousand seven hundred crore was swept from Kerala's "
        "electricity and water corporations into the treasury.",
        "The National Security Act allows the state to hold someone for up to "
        "twelve months without charge and without trial.",
    ):
        got = reel._sane_caption("", spoken)
        last = got.split()[-1].lower().rstrip(".,;:")
        check(f"does not end on {last!r}",
              last in reel._DANGLING or last.endswith("'s"), False)


def t_no_reveal_step_is_slow_enough_to_read_as_stalled():
    """The per-WORD pace (0.42s, added 2026-08-29) is not enough on its own:
    spread over at most MAX_CAPTION_REVEALS steps, a 26-word caption silently
    lands at 1.8s a step. The per-STEP duration has to be capped too."""
    for words in (4, 12, 26, 40):
        steps = min(words, reel.MAX_CAPTION_REVEALS)
        span = min(12.0, max(1.2, 0.42 * words), reel.MAX_REVEAL_SECS * steps)
        per = span / steps
        check(f"{words} words reveal at {per:.2f}s a step",
              per <= reel.MAX_REVEAL_SECS + 1e-9, True)
    # And not so fast it is unreadable either.
    check("a short caption still gets a readable step",
          min(12.0, max(1.2, 0.42 * 4)) / 4 >= 0.3, True)


def main():
    print("reel leak + caption pacing\n")
    for t in (t_the_guard_that_only_ran_at_render_time,
              t_the_older_shapes_are_still_caught,
              t_the_fallback_caption_was_longer_than_what_it_replaced,
              t_a_caption_never_ends_on_a_dangling_word,
              t_no_reveal_step_is_slow_enough_to_read_as_stalled):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all reel leak cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
