"""Long-form video publishing — the details that differ from Shorts.

    python -m shared.tests.run_longform_cases

No network, no YouTube credentials: publish_video() is exercised against a
stubbed requests module, so the metadata and permalink logic is real but nothing
leaves the machine.

What this is FOR is the handful of ways a long video published through the
Shorts path goes quietly wrong — a "#Shorts" tag on a ten-minute video, a
/shorts/ permalink that redirects, chapters YouTube silently ignores. None of
these raise an error anywhere; they just produce a worse video and a wrong link.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from publishing import youtube                    # noqa: E402
from publishing import longform                   # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


class _Resp:
    def __init__(self, code=200, headers=None, payload=None):
        self.status_code = code
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeRequests:
    """Captures the metadata publish_video() sends."""
    def __init__(self):
        self.metadata = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.metadata = json
        return _Resp(200, {"Location": "https://upload.example/session"})

    def put(self, url, headers=None, data=None, timeout=None):
        return _Resp(200, payload={"id": "VID123"})


def _publish(**kw):
    fake = _FakeRequests()
    orig_req, orig_tok = youtube.requests, youtube._access_token
    youtube.requests = fake
    youtube._access_token = lambda: "token"
    try:
        result = youtube.publish_video(b"x" * 1024, kw.pop("title", "T"), **kw)
    finally:
        youtube.requests, youtube._access_token = orig_req, orig_tok
    return result, fake.metadata


def t_permalink_is_watch_not_shorts():
    """A long video served under /shorts/ redirects — and any link already
    published stays wrong."""
    (vid, url), _ = _publish()
    check("video id returned", vid, "VID123")
    check("permalink is /watch", url, "https://youtube.com/watch?v=VID123")
    check("permalink is not /shorts", "/shorts/" in url, False)


def t_no_shorts_tag_is_appended():
    """Appending #Shorts to a ten-minute video does not make it a Short; it
    mislabels it."""
    _, meta = _publish(description="A long investigation.")
    check("description unchanged",
          meta["snippet"]["description"], "A long investigation.")
    check("no #Shorts appended",
          "#shorts" in meta["snippet"]["description"].lower(), False)


def t_privacy_is_settable_and_validated():
    _, meta = _publish(privacy="unlisted")
    check("privacy honoured", meta["status"]["privacyStatus"], "unlisted")
    _, meta = _publish()
    check("defaults to public", meta["status"]["privacyStatus"], "public")
    try:
        _publish(privacy="secret")
        check("invalid privacy rejected", False, True)
    except youtube.YouTubePublishError:
        check("invalid privacy rejected", True, True)


def t_title_truncated_to_youtube_limit():
    _, meta = _publish(title="x" * 250)
    check("title capped at 100", len(meta["snippet"]["title"]), 100)


def t_chapters_render_into_the_description():
    _, meta = _publish(description="Body.",
                       chapters=[(0, "Intro"), (95, "The audit"), (600, "What it means")])
    desc = meta["snippet"]["description"]
    check("body kept", desc.startswith("Body."), True)
    check("first chapter at 0:00", "0:00 Intro" in desc, True)
    check("minutes formatted", "1:35 The audit" in desc, True)
    # 600s is 10:00, NOT 0:10:00 — the hour field only appears past an hour,
    # which is what YouTube expects and what viewers read.
    check("ten minutes has no hour field", "10:00 What it means" in desc, True)
    check("no spurious 0: prefix", "0:10:00" in desc, False)


def t_hour_long_chapters_get_an_hour_field():
    _, meta = _publish(chapters=[(0, "Intro"), (600, "Middle"), (3725, "Close")])
    desc = meta["snippet"]["description"]
    check("past an hour formatted h:mm:ss", "1:02:05 Close" in desc, True)


def t_invalid_chapter_lists_are_dropped_not_half_written():
    """YouTube silently renders NO chapters if the list is malformed, so a
    half-valid block is worse than none — it looks fine and does nothing."""
    check("fewer than three dropped",
          youtube.format_chapters([(0, "A"), (10, "B")]), "")
    check("not starting at zero dropped",
          youtube.format_chapters([(5, "A"), (10, "B"), (20, "C")]), "")
    check("valid list rendered",
          youtube.format_chapters([(0, "A"), (10, "B"), (20, "C")]).splitlines()[0],
          "0:00 A")


def t_chapters_sorted_and_blank_labels_ignored():
    out = youtube.format_chapters([(20, "C"), (0, "A"), (10, "  "), (5, "B")])
    check("blank label dropped", "  " in out, False)
    check("ascending order", out.splitlines()[0], "0:00 A")
    check("three survivors rendered", len(out.splitlines()), 3)


# --------------------------------------------------------------------------
# graduation — when a story stops fitting the reel format
# --------------------------------------------------------------------------

def _reel(hook, beats, close):
    lines = [f"HOOK: {hook}", "HOOK_CAPTION: cap", "HOOK_IMAGE: img"]
    for i, b in enumerate(beats, 1):
        lines += [f"BEAT {i}: {b}", f"BEAT {i} CAPTION: cap", f"BEAT {i} IMAGE: img"]
    lines += [f"CLOSE: {close}", "CLOSE_CAPTION: cap", "CLOSE_IMAGE: img",
              "TITLE: t", "PLACE: India", "HASHTAGS: A B C"]
    return "\n".join(lines)


W20 = " ".join(["word"] * 20)


def t_caption_and_image_lines_are_not_spoken():
    """Counting them would inflate every script by roughly a third and graduate
    stories that fit the reel format fine."""
    script = _reel(W20, [W20, W20], W20)
    check("only spoken words counted", longform.spoken_words(script), 80)


def t_short_script_does_not_graduate():
    ok, reason = longform.should_graduate(_reel(W20, [W20, W20], W20))
    check("short script stays a reel", ok, False)
    check("reason gives the count", "80" in reason, True)


def t_overlong_but_cuttable_does_not_graduate():
    """The reel rule handles this: drop a middle beat and it fits. Graduating
    here would produce long-form videos for stories that never needed one."""
    script = _reel(W20, [W20] * 12, W20)   # 280 spoken words
    total = longform.spoken_words(script)
    ok, reason = longform.should_graduate(script)
    check("script is over budget", total > longform.REEL_HARD_CEILING_WORDS, True)
    check("but does not graduate", ok, False)
    check("reason names the middle-beat cut", "middle beats" in reason, True)


def t_uncuttable_overflow_graduates():
    """Still over budget with every middle beat gone — the only cuts left are
    the hook, the close, and attribution, which the reel rule forbids."""
    long_beat = " ".join(["word"] * 130)
    script = _reel(long_beat, [long_beat] * 3, long_beat)
    ok, reason = longform.should_graduate(script)
    check("graduates to long-form", ok, True)
    check("reason names what would be lost", "attribution" in reason, True)


def t_two_beat_script_cannot_be_cut_further():
    """With no middle beats there is nothing safe left to remove."""
    long_beat = " ".join(["word"] * 200)
    ok, _ = longform.should_graduate(_reel(long_beat, [long_beat], long_beat))
    check("two-beat overflow graduates", ok, True)


# --------------------------------------------------------------------------
# script parsing and budget
# --------------------------------------------------------------------------

SCRIPT = """TITLE: The road money
PLACE: Karnataka, India
WHY_LONG_FORM: The same figure is used two different ways by two sources.
COLD_OPEN: Forty six thousand crore rupees of road work. One complaint says most of it never reached the road.
COLD_OPEN_IMAGE: A road cross-section with a hollow beneath the asphalt.
CHAPTER 1 TITLE: What the audit actually found
CHAPTER 1: The comptroller and auditor general put irregularities at one thousand nine hundred and fifty crore rupees for the year, across every department of the corporation.
CHAPTER 1 IMAGE: The audit paragraph held on screen.
CHAPTER 2 TITLE: Where the bigger number comes from
CHAPTER 2: A separate enforcement complaint uses a much larger figure, and uses it differently: as the total spent, not as the amount misappropriated.
CHAPTER 2 IMAGE: Two documents side by side with the same number circled.
CLOSE: What would settle it is a departmental audit of road contracts specifically. That has not been published.
CLOSE_IMAGE: An empty document tray.
DESCRIPTION: A look at two readings of one figure. Sources: CAG state audit, ED complaint.
HASHTAGS: BBMP Bengaluru CAG RoadWorks Audit Karnataka
WORD_COUNT: 92
"""


def t_parses_chapters_in_order():
    p = longform.parse_script(SCRIPT)
    check("title parsed", p["title"], "The road money")
    check("place parsed", p["place"], "Karnataka, India")
    check("trigger recorded", p["why_long_form"].startswith("The same figure"), True)
    check("two chapters", len(p["chapters"]), 2)
    check("chapter order", [c["n"] for c in p["chapters"]], [1, 2])
    check("chapter title", p["chapters"][0]["title"], "What the audit actually found")
    check("chapter image kept", bool(p["chapters"][1]["image"]), True)
    check("hashtags stripped of #", p["hashtags"][0], "BBMP")


def t_parses_fenced_output():
    p = longform.parse_script("```\n" + SCRIPT + "\n```")
    check("fenced script still parses", len(p["chapters"]), 2)


def t_chapter_timestamps_start_at_zero_and_ascend():
    p = longform.parse_script(SCRIPT)
    marks = longform.estimate_chapter_timestamps(p)
    check("starts at 0", marks[0][0], 0)
    check("ascending", all(b[0] >= a[0] for a, b in zip(marks, marks[1:])), True)
    check("one mark per chapter plus intro", len(marks), 3)
    check("youtube accepts the block",
          bool(youtube.format_chapters(marks)), True)


def t_budget_check_rejects_over_ceiling():
    ok, msg = longform.budget_check(longform.LONGFORM_HARD_CEILING + 1)
    check("over ceiling rejected", ok, False)
    check("advises cutting a whole chapter", "whole chapter" in msg, True)


def t_budget_check_reports_synthesis_cost():
    """A script's real cost is an hour of the reel-worker's only voice server —
    knowing it before starting is the difference between scheduling and
    discovering."""
    ok, msg = longform.budget_check(1200)
    check("target length accepted", ok, True)
    audio, synth = longform.synthesis_estimate(1200)
    check("8 minutes of audio", round(audio / 60), 8)
    check("about an hour to synthesise", round(synth / 60), 58)
    check("message states the cost", "synthesise" in msg, True)


def main():
    print("long-form video cases")
    for t in (t_permalink_is_watch_not_shorts,
              t_no_shorts_tag_is_appended,
              t_privacy_is_settable_and_validated,
              t_title_truncated_to_youtube_limit,
              t_chapters_render_into_the_description,
              t_hour_long_chapters_get_an_hour_field,
              t_invalid_chapter_lists_are_dropped_not_half_written,
              t_chapters_sorted_and_blank_labels_ignored,
              t_caption_and_image_lines_are_not_spoken,
              t_short_script_does_not_graduate,
              t_overlong_but_cuttable_does_not_graduate,
              t_uncuttable_overflow_graduates,
              t_two_beat_script_cannot_be_cut_further,
              t_parses_chapters_in_order,
              t_parses_fenced_output,
              t_chapter_timestamps_start_at_zero_and_ascend,
              t_budget_check_rejects_over_ceiling,
              t_budget_check_reports_synthesis_cost):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all long-form cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
