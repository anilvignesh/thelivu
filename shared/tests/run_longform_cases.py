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
from datetime import datetime                     # noqa: E402


def _fresh_db():
    from shared.db import init_db, _conn
    init_db()
    conn = _conn()
    try:
        conn.cursor().execute("DELETE FROM longform_queue")
        conn.commit()
    finally:
        conn.close()

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


def t_metadata_never_counts_as_narration():
    """A multi-line DESCRIPTION with a numbered source list pushed a 1,298-word
    script to 1,661 and over the hard ceiling. The counter is an allowlist now:
    only narration counts, and anything unrecognised counts as nothing."""
    script = "\n".join([
        "TITLE: t", "PLACE: India",
        "COLD_OPEN: one two three",
        "COLD_OPEN_IMAGE: a picture of something",
        "CHAPTER 1 TITLE: A chapter title with several words",
        "CHAPTER 1: four five",
        "CHAPTER 1 IMAGE 1: another picture entirely",
        "CHAPTER 1 IMAGE 2: and a third picture here",
        "CLOSE: six",
        "DESCRIPTION: a description that runs on",
        "Sources:",
        "1. A long source citation with a great many words in it",
        "2. Another long source citation, equally wordy",
        "HASHTAGS: A B C", "WORD_COUNT: 0",
    ])
    check("only narration counted", longform.spoken_words(script), 6)


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


def t_a_shipped_reel_does_not_close_a_topic():
    """Anil, 2026-09-10: "we are not gonna say, the reel is done, no long
    video." A reel that shipped fit 225 words; that says nothing about whether
    the material behind it needed more."""
    long_beat = " ".join(["word"] * 90)
    dense = _reel(long_beat, [long_beat] * 3, long_beat)
    ok, reason = longform.also_warrants_longform(dense)
    check("dense reel still owes a long video", ok, True)
    check("reason points at what was cut", "cut" in reason, True)


def t_new_material_after_the_reel_qualifies_a_topic():
    """A dig that kept going, or an RTI that came back."""
    modest = _reel(W20, [W20, W20], W20)         # 80 words, fits fine
    ok, _ = longform.also_warrants_longform(modest)
    check("modest reel alone does not qualify", ok, False)
    ok, reason = longform.also_warrants_longform(modest, additional_material_words=300)
    check("with new material it qualifies", ok, True)
    check("reason cites the new material", "further words" in reason, True)


def t_thin_topic_is_not_stretched_into_long_form():
    """A long video that is the same story said more slowly is padding."""
    ok, reason = longform.also_warrants_longform(_reel(W20, [W20], W20))
    check("thin topic stays a reel", ok, False)
    check("reason names the failure mode", "more slowly" in reason, True)


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
OPEN_LOOP: Was the money spent badly, or was it taken?
CHAPTER 1 TITLE: What the audit actually found
CHAPTER 1: The comptroller and auditor general put irregularities at one thousand nine hundred and fifty crore rupees for the year, across every department of the corporation.
CHAPTER 1 IMAGE 1: The audit paragraph held on screen.
CHAPTER 1 IMAGE 2: A ledger with two columns of very different heights.
CHAPTER 1 RECORD: LS Unstarred Q843, 23 July 2026 | https://sansad.in/x.pdf | 2,732 crore
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


def t_open_loop_is_parsed_and_not_spoken():
    """OPEN_LOOP is the contract the script holds itself to — the close must
    answer it by name. It is never narrated, so it must not inflate the count."""
    p = longform.parse_script(SCRIPT)
    check("open loop parsed", p["open_loop"], "Was the money spent badly, or was it taken?")
    check("open loop not counted as spoken",
          longform.spoken_words("OPEN_LOOP: " + " ".join(["word"] * 30)), 0)


def t_parses_fenced_output():
    p = longform.parse_script("```\n" + SCRIPT + "\n```")
    check("fenced script still parses", len(p["chapters"]), 2)


def t_record_lines_are_parsed_as_evidence_not_illustration():
    """A RECORD is a real document page, a different asset class from a
    generated IMAGE — it IS the evidence rather than an image that might be
    mistaken for it, and the third field is what makes it evidence rather than
    a prop: the page shown must contain that phrase."""
    p = longform.parse_script(SCRIPT)
    ch1 = p["chapters"][0]
    check("record parsed", len(ch1["records"]), 1)
    r = ch1["records"][0]
    check("description read", r["description"].startswith("LS Unstarred Q843"), True)
    check("url read", r["url"].endswith(".pdf"), True)
    check("locating phrase read", r["quote"], "2,732 crore")
    check("records kept separate from images", len(ch1["images"]), 2)


def t_record_line_is_not_counted_as_narration():
    check("record contributes no spoken words",
          longform.spoken_words("CHAPTER 1 RECORD: a doc | http://x | some phrase here"), 0)


def t_chapters_carry_multiple_images():
    """One image per chapter leaves each on screen ~58s against a reel's ~15s,
    so long-form runs 2-3 per chapter and the parser has to keep them all."""
    p = longform.parse_script(SCRIPT)
    ch1 = p["chapters"][0]
    check("both images kept", len(ch1["images"]), 2)
    check("order preserved", ch1["images"][0].startswith("The audit paragraph"), True)
    check("single `image` still points at the first", ch1["image"], ch1["images"][0])


def t_unnumbered_image_line_still_works():
    """The old single-IMAGE form must keep parsing — chapter 2 of the fixture
    uses it."""
    p = longform.parse_script(SCRIPT)
    ch2 = p["chapters"][1]
    check("unnumbered image parsed", len(ch2["images"]), 1)
    check("accessible as image", bool(ch2["image"]), True)


def t_chapter_timestamps_start_at_zero_and_ascend():
    p = longform.parse_script(SCRIPT)
    marks = longform.estimate_chapter_timestamps(p)
    check("starts at 0", marks[0][0], 0)
    check("ascending", all(b[0] >= a[0] for a, b in zip(marks, marks[1:])), True)
    check("one mark per chapter plus intro", len(marks), 3)
    check("youtube accepts the block",
          bool(youtube.format_chapters(marks)), True)


def t_length_alone_never_fails_a_script():
    """News reporting: the detail is the product. A cap on length is what the
    reel already has, and cutting load-bearing material to fit one is the
    failure this format exists to fix."""
    for words in (1500, 2500, 4000):
        ok, msg = longform.budget_check(words)
        check(f"{words}w accepted on length", ok, True)
    ok, msg = longform.budget_check(2500)
    check("long scripts get a padding caution, not a rejection",
          "every chapter still changes" in msg, True)


def t_only_machine_time_can_fail_a_script():
    """And when it does, the answer is to schedule differently, not to cut."""
    fits, why = longform.fits_window(2500)
    check("two hours fits an eight-hour window", fits, True)
    # 8h of synthesis at 7.2x is ~10,000 words, so the threshold is well past
    # anything editorial — which is the point.
    fits, why = longform.fits_window(15000)
    check("very long narration does not fit", fits, False)
    check("named as a scheduling problem", "scheduling problem" in why, True)
    check("explicitly not a reason to cut", "Do not cut the story" in why, True)
    fits, _ = longform.fits_window(15000, hours=24)
    check("a wider window fits it", fits, True)


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


# --------------------------------------------------------------------------
# the graduation queue — the reel pipeline reporting on itself
# --------------------------------------------------------------------------

def t_queue_is_idempotent_per_run():
    """A rebuilt run must not queue the same story twice."""
    _fresh_db()
    from shared.db import queue_longform, longform_queue
    check("first queue accepted", bool(queue_longform(7, "T", "over at 118s", 118.0)), True)
    check("repeat ignored", queue_longform(7, "T", "over again", 120.0), None)
    check("one row", len(longform_queue()), 1)


def t_queued_story_is_eligible_not_ready():
    """Outgrowing a reel makes a story eligible for long-form. It still has to
    clear the evidence bar, and a queue entry carries no claims yet — so the
    slot must skip rather than publish it."""
    _fresh_db()
    from shared.db import queue_longform
    from shared import evidence as ev
    queue_longform(8, "Highway penalties", "over at 118s", 118.0)
    cands = longform.queued_candidates()
    check("candidate surfaced", len(cands), 1)
    check("carries the reel's reason", "118s" in cands[0]["reason"], True)

    cands[0]["claims"] = [ev.Claim("names a firm", ev.NAMED, ev.SECONDARY)]
    chosen, why = longform.slot_decision(cands, datetime(2026, 9, 11, 23, 0))
    check("not published on eligibility alone", chosen, None)
    check("skip explains itself", "evidence bar" in why, True)


def t_a_cleared_story_takes_the_slot():
    _fresh_db()
    from shared import evidence as ev
    cands = [{"title": "Cleared story", "word_count": 1200,
              "queued_since": "2026-09-01",
              "claims": [ev.Claim("primary figure", ev.HOOK, ev.PRIMARY)]}]
    chosen, why = longform.slot_decision(cands, datetime(2026, 9, 11, 23, 0))
    check("published", chosen["title"], "Cleared story")
    check("names the render deadline", "rendering must start by" in why, True)


def t_longest_waiting_cleared_story_wins():
    """A piece that has held up for two weeks of digging is more certain, not
    more stale."""
    _fresh_db()
    from shared import evidence as ev
    ok = lambda: [ev.Claim("f", ev.HOOK, ev.PRIMARY)]
    cands = [{"title": "Newer", "word_count": 900, "queued_since": "2026-09-09", "claims": ok()},
             {"title": "Older", "word_count": 900, "queued_since": "2026-09-01", "claims": ok()}]
    chosen, _ = longform.slot_decision(cands, datetime(2026, 9, 11, 23, 0))
    check("oldest cleared story chosen", chosen["title"], "Older")


# --------------------------------------------------------------------------
# the two gates — approval is the trigger, not a calendar
# --------------------------------------------------------------------------

def t_the_pipeline_cannot_skip_a_gate():
    """A state machine that silently accepts an illegal move is how a video
    reaches YouTube without a person having read the script."""
    check("cannot jump queued -> posted",
          longform.can_advance(longform.QUEUED, longform.POSTED)[0], False)
    check("cannot jump scripted -> rendered",
          longform.can_advance(longform.SCRIPTED, longform.RENDERED)[0], False)
    check("cannot jump script_ok -> posted",
          longform.can_advance(longform.SCRIPT_OK, longform.POSTED)[0], False)
    check("legal step allowed",
          longform.can_advance(longform.SCRIPT_OK, longform.RENDERED)[0], True)
    check("posted is terminal",
          longform.can_advance(longform.POSTED, longform.RENDERED)[0], False)


def t_the_machine_may_not_pass_its_own_gates():
    """Rendering an unread script wastes an hour of the only voice server;
    posting an unwatched video is worse."""
    for state, nxt in ((longform.SCRIPTED, longform.SCRIPT_OK),
                       (longform.RENDERED, longform.POSTED)):
        try:
            longform.advance(1, state, nxt, by="system")
            check(f"{state} blocked for system", False, True)
        except PermissionError as e:
            check(f"{state} blocked for system", True, True)
            check("reason names the cost", "voice server" in str(e) or "unwatched" in str(e), True)


def t_a_person_may_pass_a_gate():
    _fresh_db()
    from shared.db import queue_longform, longform_queue
    queue_longform(9, "Story", "over at 118s", 118.0)
    qid = longform_queue(status=longform.QUEUED)[0]["id"]
    longform.advance(qid, longform.QUEUED, longform.SCRIPTED, by="system")
    check("pipeline may script it", len(longform_queue(status=longform.SCRIPTED)), 1)
    longform.advance(qid, longform.SCRIPTED, longform.SCRIPT_OK, by="anil")
    check("a person may approve", len(longform_queue(status=longform.SCRIPT_OK)), 1)


def t_anything_can_be_dropped_at_any_live_state():
    """A story can turn out wrong at any point before it ships."""
    for state in (longform.QUEUED, longform.SCRIPTED, longform.SCRIPT_OK,
                  longform.RENDERED):
        check(f"{state} can be dropped",
              longform.can_advance(state, longform.DROPPED)[0], True)


def t_rendering_sits_between_the_gates():
    """Not before the first — an hour of narration on a script nobody has read
    is how the box ends up busy with something thrown away."""
    check("render follows script approval",
          longform.can_advance(longform.SCRIPT_OK, longform.RENDERED)[0], True)
    check("render does not follow scripting directly",
          longform.can_advance(longform.SCRIPTED, longform.RENDERED)[0], False)


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
              t_metadata_never_counts_as_narration,
              t_short_script_does_not_graduate,
              t_overlong_but_cuttable_does_not_graduate,
              t_uncuttable_overflow_graduates,
              t_a_shipped_reel_does_not_close_a_topic,
              t_new_material_after_the_reel_qualifies_a_topic,
              t_thin_topic_is_not_stretched_into_long_form,
              t_two_beat_script_cannot_be_cut_further,
              t_parses_chapters_in_order,
              t_open_loop_is_parsed_and_not_spoken,
              t_parses_fenced_output,
              t_record_lines_are_parsed_as_evidence_not_illustration,
              t_record_line_is_not_counted_as_narration,
              t_chapters_carry_multiple_images,
              t_unnumbered_image_line_still_works,
              t_chapter_timestamps_start_at_zero_and_ascend,
              t_length_alone_never_fails_a_script,
              t_only_machine_time_can_fail_a_script,
              t_queue_is_idempotent_per_run,
              t_queued_story_is_eligible_not_ready,
              t_a_cleared_story_takes_the_slot,
              t_longest_waiting_cleared_story_wins,
              t_the_pipeline_cannot_skip_a_gate,
              t_the_machine_may_not_pass_its_own_gates,
              t_a_person_may_pass_a_gate,
              t_anything_can_be_dropped_at_any_live_state,
              t_rendering_sits_between_the_gates,
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
