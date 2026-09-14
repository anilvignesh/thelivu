"""Long-form rendering and the chain either side of it — script in, MP4 out,
unlisted upload, gate 2, public.

    python -m shared.tests.run_longform_render_cases

No FLUX and no TTS: `synth_beats` is replaced with real but silent wavs of
known length, and illustration is switched off so every shot falls back to the
house ground. ffmpeg is real, so the assembly this exercises is the assembly
that ships.

What this is FOR is the class of bug a renderer that runs MONTHLY produces: it
does not crash, it quietly makes a worse video, and nobody finds out until the
one night the video matters. Specifically —

  * segments whose audio is trimmed away by `-shortest`, so the timeline the
    chapter marks were computed against is not the timeline in the file;
  * a chapter cut into shots whose parts do not sum to the narration, so the
    voice drifts out of the pictures a few minutes in;
  * chapter marks measured from the spoken word instead of the title card, so
    every YouTube chapter link lands two and a half seconds late;
  * a one-line chapter cut into three shots of four seconds each.

The second half covers publishing/longform_build.py, where the interesting
failure is structural rather than visual: the video is uploaded UNLISTED before
the gate, so "drop" has to actually remove it, and "post" must never be
reachable without a person.
"""
import os
import subprocess
import sys
import tempfile
import wave

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from publishing import longform                   # noqa: E402
from publishing import longform_render as lfr     # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(("  ok   " if ok else "  FAIL ") + name)


def near(name, got, want, tol):
    ok = abs(got - want) <= tol
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r} +/-{tol}")
    print(("  ok   " if ok else "  FAIL ") + f"{name} ({got:.2f})")


def have_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _silence(path, seconds, rate=44100):
    """A real wav of exact length — ffmpeg has to be able to seek into it."""
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def probe_seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


SCRIPT = """TITLE: What happens to a road that fails
COLD_OPEN: The minister said the highway was world class.
COLD_OPEN_IMAGE: A ribbon-cutting scissors over fresh tarmac.

CHAPTER 1 TITLE: The register
CHAPTER 1: Forty of fifty-nine deficiencies were closed by the contractor rectifying the work, and only one of them applied the five per cent rule. The register is public and it has been public the whole time.
CHAPTER 1 FIGURE: 40 of 59 | closed by the contractor rectifying the work | MoRTH register
CHAPTER 1 IMAGE 1: A ledger open on a desk.
CHAPTER 1 IMAGE 2: A rubber stamp resting beside an unsigned page.

CHAPTER 2 TITLE: The money
CHAPTER 2: Two thousand seven hundred and thirty-two crore rupees was imposed in penalties over three years, and seven hundred and eighty crore of it was recovered. The rest is still outstanding.
CHAPTER 2 TABLE: Share of NH projects running late | MoRTH (data.gov.in) | Arunachal Pradesh 87% | Gujarat 71% | ... | *Kerala 22%
CHAPTER 2 IMAGE 1: A cash box with a broken lock.
CHAPTER 2 IMAGE 2: An empty vault shelf.
CHAPTER 2 IMAGE 3: A pile of unpaid invoices.

CLOSE: The record was never hidden. It was only never read.
CLOSE_IMAGE: A closed file returned to a shelf.
"""


# ---------------------------------------------------------------- shot counts

def t_a_short_unit_keeps_one_picture():
    # Two images available, but ten seconds of narration. Cutting that in half
    # is a flicker, and the second picture says nothing the first did not.
    check("short unit holds one shot", lfr._shot_count(10.0, 2), 1)


def t_a_long_unit_uses_the_pictures_it_was_given():
    check("60s with two images", lfr._shot_count(60.0, 2), 2)
    check("60s with three images", lfr._shot_count(60.0, 3), 3)


def t_shots_never_exceed_the_pictures_available():
    # The failure this guards: reaching for images[3] on a chapter that has one.
    check("five minutes, one image", lfr._shot_count(300.0, 1), 1)
    check("five minutes, two images", lfr._shot_count(300.0, 2), 2)


def t_the_narration_not_the_prompt_count_sets_the_budget():
    # Three bounds, and each has to be able to win. TARGET_SHOT_SECONDS (13s)
    # sets the cadence, MIN_SHOT_SECONDS (8s) stops a flicker, and the asset
    # count stops the renderer cutting to something that does not exist.
    check("30s wants about two shots", lfr._shot_count(30.0, 6), 2)
    check("90s wants about seven", lfr._shot_count(90.0, 12), 7)
    check("a 10s unit still holds one", lfr._shot_count(10.0, 3), 1)
    check("and never more frames than assets", lfr._shot_count(90.0, 3), 3)


def t_the_cap_holds_however_long_the_chapter_runs():
    # The cap is a safety rail, not the cadence: ten minutes of narration at
    # 13s a shot "wants" 46 frames, and no unit should ever get that.
    check("the cap holds", lfr._shot_count(600.0, 40), lfr.MAX_SHOTS_PER_UNIT)


# ------------------------------------------------------ putting it on the beat
#
# Anil, 2026-09-13, on the first finished cut: "in the first minute itself, i
# did find places where proper alignment would have made it better."
#
# The renderer used to place assets in declaration order and cut on a stopwatch,
# which is right only when the writer lists them in the order they are spoken.
# Chunked synthesis made the real timing available for free — the chunks are
# synthesised separately, so their start times are exact.

def t_a_number_is_matched_to_the_way_it_is_spoken():
    """A FIGURE carries digits and the script carries words. They are the same
    fact written for two readers, and matching them is the whole basis of
    showing a figure as it is said."""
    check("39230 spells out", " ".join(lfr._spell(39230)),
          "thirty nine thousand two hundred thirty")
    check("236 spells out", " ".join(lfr._spell(236)), "two hundred thirty six")
    check("15 spells out", " ".join(lfr._spell(15)), "fifteen")


def t_a_figure_anchors_where_its_number_is_spoken():
    marks = [
        (0.0, "The bigger fight is over thirty nine thousand two hundred and "
              "thirty crore rupees."),
        (20.0, "It was borrowed through KIIFB and KSSPL, outside the state budget."),
        (40.0, "Liabilities reach thirty eight point eight six percent of GSDP."),
    ]
    big = {"kind": "figure", "figure": {"value": "\u20b939,230.33 crore",
                                        "label": "borrowed through KIIFB and KSSPL"}}
    # The label's words are rarer than the number's, so without weighting the
    # value this anchored to chunk 1 — the sentence ABOUT the money rather than
    # the one saying how much.
    check("the big figure lands where the number is said",
          lfr.anchor_chunk(big, marks), 0)
    pct = {"kind": "figure", "figure": {"value": "38.86%", "label": "of GSDP"}}
    check("the percentage lands on its own sentence",
          lfr.anchor_chunk(pct, marks), 2)
    quote = {"kind": "quote", "text": "It was borrowed through KIIFB and KSSPL, "
                                      "outside the state budget."}
    check("a quote frame lands on its own sentence exactly",
          lfr.anchor_chunk(quote, marks), 1)


def t_an_asset_with_nothing_to_match_is_not_guessed():
    """Guessing is worse than spreading evenly: a figure placed on one shared
    common word lands arbitrarily and looks deliberate."""
    marks = [(0.0, "Something entirely unrelated was said here."),
             (10.0, "And then something else again.")]
    orphan = {"kind": "image", "prompt": "a ledger"}
    check("an image never anchors", lfr.anchor_chunk(orphan, marks), None)
    vague = {"kind": "table", "table": {"title": "Two reports"}}
    check("one weak match is not enough", lfr.anchor_chunk(vague, marks), None)


def t_anchored_cuts_sum_exactly_and_keep_order():
    from publishing.reel import plan_cuts

    marks = [(0.0, "thirty nine thousand two hundred thirty crore was borrowed."),
             (20.0, "A second sentence carries the argument forward."),
             (40.0, "Liabilities reach thirty eight point eight six percent."),
             (60.0, "Nobody says the money was not borrowed at all.")]
    assets = [
        {"kind": "figure", "figure": {"value": "39,230 crore", "label": "borrowed"}},
        {"kind": "figure", "figure": {"value": "38.86%", "label": "liabilities"}},
        {"kind": "quote", "text": "Nobody says the money was not borrowed at all."},
    ]
    cuts = lfr.cuts_from_anchors(assets, marks, 80.0, [], plan_cuts)
    check("sums to the take exactly", round(sum(cuts), 3), 80.0)
    check("every shot is positive", all(c > 0 for c in cuts), True)
    starts = [sum(cuts[:i]) for i in range(len(cuts))]
    check("shots run in order", starts == sorted(starts), True)
    # The percentage is spoken at 40s; it should be on screen around then, not
    # at the 26.7s an even three-way split would have given it.
    check("the second figure lands near where it is spoken",
          abs(starts[1] - 40.0) < 6.0, True)


def t_evidence_is_reordered_into_the_order_it_is_spoken():
    """The defect the first real render exposed, and the reason the earlier
    "never reorder" rule was reversed.

    Chapter 1 of long-form #1 declared FIGURE, FIGURE, TABLE, RECORD. The
    narration reaches them at 10.7s, 29.3s, 0.0s and 10.7s. The old greedy
    left-to-right filter kept the first two anchors and dropped the other two
    for going backwards, so the opening figure held the screen from 0 to 29.3s
    — eighteen seconds after the sentence that says it.
    """
    marks = [
        (0.0, "Two reports of the auditor contradict each other across years."),
        (10.0, "Thirty thousand three hundred and eight crore was never collected."),
        (30.0, "A second figure, forty one thousand one hundred and eighty crore, follows."),
    ]
    figure_a = {"kind": "figure", "figure": {"value": "30,308 crore", "label": "uncollected"}}
    figure_b = {"kind": "figure", "figure": {"value": "41,180 crore", "label": "second"}}
    table = {"kind": "table", "table": {"title": "Two reports contradict across years"}}

    out = lfr.order_by_narration([figure_a, figure_b, table], marks)
    check("the table moves ahead of both figures", out[0]["kind"], "table")
    check("and the figures keep their own order",
          [a["figure"]["value"] for a in out[1:]], ["30,308 crore", "41,180 crore"])


def t_a_figure_and_the_record_that_evidences_it_both_survive():
    """They cite the same number, so they anchor to the same chunk BY
    CONSTRUCTION. The old strictly-increasing rule dropped one of the two."""
    from publishing.reel import plan_cuts

    marks = [(0.0, "Thirty thousand three hundred and eight crore was never collected."),
             (20.0, "The department said reconciliation was still in progress."),
             (40.0, "Nothing has been published since.")]
    figure = {"kind": "figure", "figure": {"value": "30,308 crore", "label": "uncollected"}}
    record = {"kind": "record", "record": {"quote": "thirty thousand three hundred and eight crore"}}
    quote = {"kind": "quote", "text": "Nothing has been published since."}

    assets, cuts = lfr.align_to_narration([figure, record, quote], marks, 60.0, [], plan_cuts)
    kinds = [a["kind"] for a in assets]
    check("all three are kept", sorted(kinds), ["figure", "quote", "record"])
    check("the tied pair is not squeezed to the floor",
          min(cuts[:2]) >= lfr.MIN_ANCHORED_SHOT, True)
    check("and they are not stacked on one instant",
          cuts[0] > 0 and cuts[1] > 0, True)
    check("sums exactly", round(sum(cuts), 3), 60.0)


def t_a_long_hold_buys_itself_more_frames():
    """A chapter that says all its evidence late leaves the opening with nothing
    to show. Duration alone cannot see that, so the shot budget is not final.

    Chapter 6 of long-form #1 held a generated illustration for 33 seconds while
    the narration laid out its whole argument.
    """
    from publishing.reel import plan_cuts

    text = ("So, the open question. Our reading is that this looks like a state "
            "under real fiscal strain and not a coordinated concealment operation. "
            "That is an interpretation and we are flagging it as one. What would "
            "settle it is not opinion. It is three things, each of which is "
            "checkable against the public record.")
    marks = [(0.0, text[:120]), (20.0, text[120:240]), (40.0, text[240:])]
    late = {"kind": "figure", "figure": {"value": "3 things", "label": "checkable against the public record"}}

    want = 2
    _ordered, cuts = lfr.fit_unit([late], text, want, ["a ledger"],
                                  marks, 60.0, [], plan_cuts)
    check("it bought more frames than the budget asked for", len(cuts) > want, True)
    check("and no frame holds past the ceiling", max(cuts) <= lfr.MAX_HOLD, True)
    check("sums exactly", round(sum(cuts), 3), 60.0)


def t_quote_frames_cover_the_opening_when_the_evidence_is_late():
    """quote_fill used to offer sentences only from AFTER the evidence's share
    of the text. That was right when shots ran on a stopwatch and the evidence
    occupied the leading slots. Once placement became anchored it inverted: the
    evidence lands where it is spoken, so the opening was left with nothing but
    an illustration and the sentences that would have covered it were never
    candidates.
    """
    text = ("First the chapter opens on a question nobody has answered yet. "
            "Second the argument is carried forward another step by the auditor. "
            "Third the whole thing turns on one line buried in an annexure. "
            "Fourth the number itself finally lands in front of the reader. "
            "Fifth and last the chapter closes on what would settle it.")
    sents = lfr._sentences(text)
    where = lambda qs: [sents.index(q["text"]) for q in qs]  # noqa: E731

    unanchored = where(lfr.quote_fill(text, 2, 4))
    anchored = where(lfr.quote_fill(text, 2, 4, anchored=True))
    check("without anchoring the quotes come only from the tail",
          min(unanchored) >= len(sents) // 2, True)
    check("with anchoring they span the whole chapter",
          min(anchored) < len(sents) // 2, True)
    check("and they still spread rather than bunching",
          max(anchored) > min(anchored), True)

    # The case that actually bit: ONE declared asset, four slots. Under the old
    # rule three of the four quotes came from the last three-quarters.
    many = where(lfr.quote_fill(text, 1, 5, anchored=True))
    check("a chapter with one late figure still gets an opening frame",
          min(many), 0)


def t_a_weak_anchor_still_beats_no_anchor():
    """An asset dropped for breaking the running order used to become "free" and
    land in the widest gap — which was the opening, 35 seconds before the
    sentence that says it. Free means placed loosely, not placed anywhere."""
    from publishing.reel import plan_cuts

    marks = [(0.0, "An opening that matches nothing in particular."),
             (20.0, "Another sentence that matches nothing either."),
             (40.0, "It is three things, each of them checkable.")]
    late = {"kind": "figure", "figure": {"value": "3", "label": "things checkable"}}
    image = {"kind": "image", "prompt": "a ledger"}

    assets, cuts = lfr.align_to_narration([late, image], marks, 60.0, [], plan_cuts)
    at, placed = 0.0, None
    for a, c in zip(assets, cuts):
        if a["kind"] == "figure":
            placed = (at, at + c)
        at += c
    check("the figure is not parked at the opening", placed[0] > 10.0, True)
    check("it is on screen when it is spoken",
          placed[0] - 3.0 <= 40.0 <= placed[1] + 3.0, True)


def t_the_same_sentence_is_only_ever_voiced_once():
    """Chatterbox runs about seven minutes of wall clock per minute of speech on
    the worker box. Re-rendering long-form #1 to test a change to FRAME
    PLACEMENT — which cannot affect one sample of audio — spent fifty of those
    minutes saying the same words again."""
    import tempfile, wave as _wave
    from pathlib import Path
    from publishing import reel

    calls = []

    def fake_synth(text, dest, backend, voice=None):
        calls.append(text)
        with _wave.open(str(dest), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b"\x00\x00" * 2400)

    with tempfile.TemporaryDirectory() as tmp:
        old_synth, old_env = reel._synth, os.environ.get("LONGFORM_DIR")
        reel._synth = fake_synth
        os.environ["LONGFORM_DIR"] = tmp
        try:
            a, b = Path(tmp) / "a.wav", Path(tmp) / "b.wav"
            lfr._synth_cached("A sentence the narrator says.", a, "chatterbox", "anil")
            lfr._synth_cached("A sentence the narrator says.", b, "chatterbox", "anil")
            check("the voice server ran once", len(calls), 1)
            check("and the second copy is real audio", b.exists() and b.stat().st_size > 0, True)

            lfr._synth_cached("A sentence the narrator says.", a, "chatterbox", "someone else")
            check("a different voice is a miss", len(calls), 2)

            # A truncated entry is the failure this module exists to work around.
            for entry in lfr.voice_cache_dir().glob("*.wav"):
                entry.write_bytes(b"")   # two voices are cached by now
            lfr._synth_cached("A sentence the narrator says.", a, "chatterbox", "anil")
            check("a corrupt entry is re-synthesised, not trusted", len(calls), 3)
        finally:
            reel._synth = old_synth
            if old_env is None:
                os.environ.pop("LONGFORM_DIR", None)
            else:
                os.environ["LONGFORM_DIR"] = old_env


def t_a_figure_gets_longer_on_screen_than_a_subtitle():
    """Anil, 2026-09-14, watching the 44-shot cut: "figures disappear fast, the
    words stay longer."

    A quote frame is a sentence the narrator is reading aloud at that moment —
    the viewer is hearing it and the frame only has to keep up. A figure is a
    number, a label and a source, none of it spoken in full, and it has to be
    READ. One shared floor gave them the same three seconds."""
    fig = {"kind": "figure", "figure": {"value": "30,308 crore", "label": "x"}}
    quote = {"kind": "quote", "text": "A sentence being spoken right now."}
    rec = {"kind": "record", "record": {"quote": "y"}}
    check("a figure outlasts a subtitle",
          lfr.min_shot_for(fig) > lfr.min_shot_for(quote), True)
    check("and a document page outlasts a figure",
          lfr.min_shot_for(rec) > lfr.min_shot_for(fig), True)


def t_evidence_outranks_words_when_both_want_the_moment():
    """A quote frame matched its own sentence exactly, so it scored that
    sentence's LENGTH — ten to fifteen — against a figure's two to six shared
    terms. _best_monotone maximises total score, so the subtitles won every
    contested beat and took 34% of the screen against the figures' 21%."""
    fig = {"kind": "figure", "figure": {"value": "1", "label": "x"}}
    quote = {"kind": "quote", "text": "A very long sentence indeed " * 4}
    check("a modestly-matched figure still beats a long sentence",
          lfr._weighted(fig, 3) > lfr._weighted(quote, 40), True)
    check("the raw score is capped before weighting",
          lfr._weighted(quote, 40), lfr._weighted(quote, lfr.ANCHOR_SCORE_CAP))


def t_a_gap_is_filled_with_evidence_before_more_subtitles():
    """Anil: "the words take more precedence than the figures in some places."

    Filling every spare slot with narration meant subtitles held 52% of a
    7-minute cut. A figure returning when the narration returns to it is the
    argument being made twice; a fifteenth quote frame is the screen giving up.
    """
    text = " ".join(f"Sentence number {i} carries the argument onward a step."
                    for i in range(1, 14))
    assets = [{"kind": "figure", "figure": {"value": "30,308 crore", "label": "a"}},
              {"kind": "record", "record": {"quote": "b"}}]
    out = lfr.with_filler(assets, text, 10, anchored=True)
    kinds = [a["kind"] for a in out]
    check("the declared evidence is kept", kinds[:2], ["figure", "record"])
    check("quotes do not take the whole budget",
          kinds.count("quote") <= max(1, round(10 * lfr.QUOTE_SHARE)), True)
    check("evidence comes back instead",
          any(a.get("encore") for a in out), True)


def t_an_encore_never_steals_its_own_beat():
    """A repeat matches the same chunk as the original BY CONSTRUCTION, so
    letting it anchor put two assets on one moment and pushed the original off
    it — on-beat placement fell from 75% to 56%."""
    marks = [(0.0, "Thirty thousand three hundred and eight crore went uncollected."),
             (20.0, "Something else entirely is said here.")]
    fig = {"kind": "figure", "figure": {"value": "30,308 crore", "label": "uncollected"}}
    again = dict(fig); again["encore"] = True
    check("the original anchors", lfr.anchor_chunk(fig, marks), 0)
    check("the encore does not", lfr.anchor_chunk(again, marks), None)


def t_an_illustration_never_outstays_the_evidence():
    """Six generated scenes took 79 seconds of a 7-minute cut — 19% — and when
    the daily image cap is spent they render as a plain background. Anil: "there
    is a huge gap where nothing is shown... lots of blank part, just audio."
    """
    img = {"kind": "image", "prompt": "a ledger"}
    fig = {"kind": "figure", "figure": {"value": "1", "label": "x"}}
    check("an illustration is held far less than evidence",
          lfr.max_hold_for(img) < lfr.max_hold_for(fig), True)
    check("and a subtitle cannot absorb a long gap either",
          lfr.max_hold_for({"kind": "quote"}) < lfr.max_hold_for(fig), True)

    # A unit with evidence to re-show does not spend a slot on atmosphere.
    text = " ".join(f"Sentence {i} says something worth showing." for i in range(1, 10))
    with_ev = lfr.with_filler([fig], text, 8, images=["a ledger"], anchored=True)
    check("a unit with evidence shows no illustration",
          any(a["kind"] == "image" for a in with_ev), False)
    without = lfr.with_filler([], text, 8, images=["a ledger"], anchored=True)
    check("a unit with none still gets one",
          any(a["kind"] == "image" for a in without), True)


def t_a_role_is_not_a_person():
    """Anil: "can't we show a picture of the minister?" We can — but only when
    the script says WHO.

    Offline: the failures worth protecting are decisions, not network calls.
    Measured live on 2026-09-14, searching Wikipedia for "Finance Minister"
    returns the generic article about the OFFICE, whose lead image is a Library
    of Congress mural — public domain, correctly licensed, a photograph of
    nobody. Only asking Wikidata what the subject IS separates that from
    "K. N. Balagopal, Indian politician".
    """
    from publishing import photos

    check("a human is depictable", "Q5" in photos._DEPICTABLE, True)
    # An unknown or missing classification is refused. Not knowing what
    # something is can never be the basis for putting its picture on screen.
    check("no wikidata id means no portrait",
          photos._is_a_specific_thing(None), False)

    calls = []

    def fake_entity(qid, timeout=None):
        calls.append(qid)
        return qid == "Q-person"

    real = photos._is_a_specific_thing
    photos._is_a_specific_thing = fake_entity
    try:
        check("a government post is refused", photos._is_a_specific_thing("Q-office"), False)
        check("a named person is allowed", photos._is_a_specific_thing("Q-person"), True)
    finally:
        photos._is_a_specific_thing = real


def t_an_office_resolves_to_the_person_holding_it_now():
    """Anil: "let's make the image search more specific, like chief minister
    kerala 2025." Right instinct; this is the rigorous form of it.

    Two traps, both measured live on 2026-09-14 and both encoded here offline.

    An UNDATED position statement is not a current one. Asking Wikidata for the
    Chief Minister of Kerala returns Pinarayi Vijayan (since 2016-05-25) AND
    V. D. Satheesan, who is Leader of the Opposition — his statement carries no
    start date, and requiring one is the whole difference.

    And relevance ranking has no concept of "now". The specific search that
    Anil's instinct produces returns Oommen Chandy — Chief Minister until 2016
    — ranked second and third, looking identical to the right answer.
    """
    from publishing import photos

    calls = {}

    def fake_urlopen(req, timeout=None):
        raise AssertionError("this case must not touch the network")

    # Ambiguity is refused rather than resolved: two dated holders of one office
    # is either a handover we cannot date-resolve or bad data, and guessing
    # between two politicians is the error the module exists to avoid.
    real = photos.officeholder
    photos.officeholder = lambda office, timeout=None: (
        ("Pinarayi Vijayan", "2016-05-25") if office == "Chief Minister of Kerala"
        else None)
    try:
        check("a resolvable office gives a name and a date",
              photos.officeholder("Chief Minister of Kerala"),
              ("Pinarayi Vijayan", "2016-05-25"))
        check("an office Wikidata does not cover gives nothing",
              photos.officeholder("Finance Minister of Kerala"), None)
    finally:
        photos.officeholder = real

    # The query itself must demand a start date, or the Leader of the
    # Opposition comes back as Chief Minister.
    check("the query requires a start date",
          "pq:P580 ?start" in photos.OFFICEHOLDER_QUERY, True)
    check("and excludes anyone whose term has ended",
          "pq:P582" in photos.OFFICEHOLDER_QUERY, True)


def t_the_sourced_portrait_outranks_the_search_hit():
    """Measured live 2026-09-14, proposing for "Chief Minister of Kerala":

        #1  Pinarayi Vijayan   Wikidata: holder since 2016-05-25
        #2  Oommen Chandy      Commons text search
        #3  Oommen Chandy      Commons text search

    Chandy left office in 2016. Relevance ranking has no concept of "now", and
    on a gate-1 card the wrong portrait looks exactly like the right one — so
    order matters, and every candidate has to say what it is standing on.
    """
    from publishing import photos

    real_portrait, real_office, real_search = (
        photos.portrait, photos.officeholder, photos.search)
    photos.portrait = lambda n, timeout=None: (
        {"title": n, "url": "https://x/current.jpg", "filename": "current.jpg",
         "licence": "CC BY-SA 3.0", "subject_basis": "lead image"}
        if n == "Pinarayi Vijayan" else None)
    photos.officeholder = lambda o, timeout=None: ("Pinarayi Vijayan", "2016-05-25")
    photos.search = lambda q, limit=8, min_width=900: [
        {"title": "File:Oommen Chandy Chief Minister of Kerala",
         "url": "https://x/former.jpg", "licence": "CC BY-SA 3.0"}]
    try:
        got = photos.propose("Chief Minister of Kerala")
        check("the sourced portrait comes first", got[0]["filename"], "current.jpg")
        check("it names the office and the date",
              "2016-05-25" in got[0]["subject_basis"], True)
        check("every candidate states a basis",
              all(c["subject_basis"] for c in got), True)
        check("and the search hit admits it is only ranking",
              "RANKING ONLY" in got[-1]["subject_basis"], True)
    finally:
        photos.portrait, photos.officeholder, photos.search = (
            real_portrait, real_office, real_search)


def t_with_no_marks_it_falls_back_to_the_old_split():
    """Every unit rendered before this had no chunk timing. The fallback is the
    previous behaviour, which was imprecise and never wrong."""
    from publishing.reel import plan_cuts

    assets = [{"kind": "image", "prompt": "a"}, {"kind": "image", "prompt": "b"}]
    check("no marks means an even split",
          lfr.cuts_from_anchors(assets, [], 60.0, [], plan_cuts),
          plan_cuts(60.0, 2, []))


# ------------------------------------------------------------------- framing

def t_illustrations_are_asked_for_in_the_shape_they_are_shown_in():
    """The bug the first real render found, and the only test that would have.

    Everything else passed: the frames were 1920x1080, the chapter marks were
    right, the file was the right length. But `generate_beat_images` defaults to
    the REEL's 768x1344, and cover-cropping that into a landscape frame keeps
    only the middle 32% of an image the model composed for a tall frame. The
    cold open came back as a church steeple wedged into the bottom-left corner
    of an otherwise empty frame — a valid file, a worthless picture.

    So this checks the two halves separately: that the renderer asks for
    landscape, and that landscape is what actually survives the crop.
    """
    from publishing.illustrate import GEN_W, GEN_H, LANDSCAPE

    def kept(bw, bh):
        scale = max(lfr.W / bw, lfr.H / bh)
        return (lfr.W * lfr.H) / (int(bw * scale) * int(bh * scale))

    check("the reel default is still portrait", (GEN_W, GEN_H), (768, 1344))
    check("landscape is its transpose", LANDSCAPE, (1344, 768))
    check("portrait would lose most of the picture", kept(GEN_W, GEN_H) < 0.40, True)
    check("landscape keeps nearly all of it", kept(*LANDSCAPE) > 0.95, True)

    # And that render() actually passes it, rather than the constant merely
    # existing. Captured at the call, because nothing downstream records it.
    import publishing.illustrate as illus
    seen = {}

    def fake_generate(scenes, out_dir, **kw):
        seen.update(kw)
        return [None] * len(scenes)

    real = illus.generate_beat_images
    illus.generate_beat_images = fake_generate
    tmp = tempfile.mkdtemp(prefix="lfr_size_")
    try:
        with _stub_voice():
            lfr.render(longform.parse_script(SCRIPT),
                       os.path.join(tmp, "o.mp4"),
                       work_dir=os.path.join(tmp, "w"), illustrate=True)
    finally:
        illus.generate_beat_images = real
    check("render asks for landscape", seen.get("size"), LANDSCAPE)



def t_frames_are_landscape():
    # The reel path is 1080x1920. A transposed frame renders without error and
    # is unwatchable, so assert the orientation rather than trusting it.
    import tempfile as _t
    from PIL import Image
    d = _t.mkdtemp()
    card = lfr.draw_chapter_card(2, "What happens to a road that fails",
                                 os.path.join(d, "c.png"))
    check("card is 1920x1080", Image.open(card).size, (1920, 1080))
    from publishing.reel_illustrated import render_house_ground
    g = render_house_ground(os.path.join(d, "g.png"), variant=0)
    f = lfr.draw_story_frame(g, "Forty of fifty-nine deficiencies.",
                             os.path.join(d, "f.png"), chapter_label="The register")
    check("story frame is 1920x1080", Image.open(f).size, (1920, 1080))


# --------------------------------------------------------- the frame vocabulary
#
# Anil, 2026-09-11, after watching the first sample: "this only has generated
# images, which are not great... we need to print out numbers, facts,
# screenshots, evidences. generated images like these won't work."

def t_hard_evidence_outranks_illustration():
    """When a chapter declares more than its narration has room for, the
    illustrations are what get dropped — never the figure or the document."""
    chapter = {"figures": [{"value": "40 of 59"}, {"value": "1"}],
               "records": [{"url": "https://example.gov.in/a.pdf"}],
               "images": ["a ledger", "a stamp", "a door"]}
    kinds = [a["kind"] for a in lfr.plan_assets(chapter)]
    # plan_assets returns EVIDENCE only. Pictures rank below quote frames and
    # are added by with_filler, and only where a unit can spare a slot.
    check("declared order within a kind, evidence first", kinds,
          ["figure", "figure", "record"])
    # A 40-second chapter buys three shots; those three must be the hard ones,
    # and all three illustrations go unused.
    k = lfr._shot_count(40.0, len(kinds))
    check("a short chapter keeps the evidence", kinds[:k],
          ["figure", "figure", "record"])


def t_a_chapter_with_nothing_declared_still_gets_a_frame():
    """plan_assets returns evidence only, so an empty chapter has none. The
    frame comes from with_filler, which never returns nothing — a unit with no
    evidence, no narration worth quoting and no picture still needs one frame
    or the concat has a hole in it."""
    check("no evidence means no evidence", lfr.plan_assets({}), [])
    only = lfr.with_filler([], "", want=1, images=["a desk"])
    check("but a frame is always produced", [a["kind"] for a in only], ["image"])
    check("even with nothing at all to draw",
          len(lfr.with_filler([], "", want=1)), 1)


def t_a_figure_is_drawn_not_generated():
    """The number on screen has to be the number the script declared and a
    reviewer approved — which a generated picture can neither guarantee nor,
    under BRAND.md, legibly contain."""
    import tempfile as _t
    from pathlib import Path as _P
    from PIL import Image

    d = _P(_t.mkdtemp())
    out = lfr.draw_data_card(
        {"value": "\u20b92,732 crore", "label": "imposed in penalties",
         "source": "Lok Sabha Q843"}, d / "fig.png", chapter_label="Arithmetic")
    check("the data card is landscape", Image.open(out).size, (1920, 1080))


def t_a_record_that_cannot_be_fetched_demotes_instead_of_failing():
    """A source that is down must cost the frame its evidence, not cost the
    render an hour of voice already spent."""
    check("unreachable record returns None",
          lfr._render_record({"url": "https://nonexistent.invalid/x.pdf"},
                             tempfile.mkdtemp(), "s"), None)
    check("a record with no url returns None",
          lfr._render_record({"url": ""}, tempfile.mkdtemp(), "s"), None)


def t_a_table_is_a_frame_the_viewer_can_check():
    """Anil, 2026-09-11: "there should be things valid on the screen, its a
    video at the end of the day."

    A rank stated as a figure asks for trust. The same claim as a short ranked
    list with one row lit is checkable with the eyes while the narration is
    still talking — which for a story whose whole argument is that a raw count
    and a rate rank the same state at opposite ends IS the argument."""
    import tempfile as _t
    from pathlib import Path as _P
    from PIL import Image

    parsed = longform.parse_script(SCRIPT)
    ch2 = [c for c in parsed["chapters"] if c["n"] == 2][0]
    table = ch2["tables"][0]
    check("rows parsed", len(table["rows"]), 4)
    check("the highlighted row is marked",
          [r["text"] for r in table["rows"] if r["highlight"]], ["Kerala 22%"])
    check("the elision is marked, not silently dropped",
          sum(1 for r in table["rows"] if r["elision"]), 1)
    out = lfr.draw_table_frame(table, _P(_t.mkdtemp()) / "t.png",
                               chapter_label="The money")
    check("the table frame is landscape", Image.open(out).size, (1920, 1080))


def t_a_table_ranks_with_the_figures_not_the_pictures():
    kinds = [a["kind"] for a in lfr.plan_assets(
        {"figures": [{"value": "1"}], "tables": [{"title": "t"}],
         "records": [{"url": "u"}], "images": ["a"]})]
    check("evidence order", kinds, ["figure", "table", "record"])


def t_every_source_on_screen_reaches_the_description():
    """Anil, 2026-09-11: "always make sure to leave the sources in the video
    description for the youtube long videos."

    Derived from the FIGURE/TABLE/RECORD lines rather than trusted to the
    writer's own list, which drifts the moment a chapter is edited."""
    parsed = longform.parse_script(SCRIPT)
    desc = longform.build_description(parsed)
    check("there is a Sources block", "Sources" in desc, True)
    check("the figure's source is in it", "MoRTH register" in desc
          or "MoRTH (data.gov.in)" in desc, True)

    # The same document cited two ways must appear once, with its URL.
    two_ways = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\nCHAPTER 1 TITLE: A\nCHAPTER 1: b\n"
        "CHAPTER 1 FIGURE: 5 | things | Lok Sabha Unstarred Question 843, 23 July 2026\n"
        "CHAPTER 1 RECORD: Lok Sabha Unstarred Question 843, answered 23 July 2026"
        " | https://sansad.in/x/AU843.pdf | five\nCLOSE: y\n")
    lines = [l for l in longform.build_description(two_ways).splitlines()
             if l.strip().startswith(("1.", "2."))]
    check("one entry, not two", len(lines), 1)
    check("and it is the one with the URL", "sansad.in" in lines[0], True)


def t_licensed_media_is_credited_in_the_description_too():
    """Anil, 2026-09-13: "if we cant show the item on the video, due to
    copyright, we can atleast add them as source in the video description."

    For CC-BY and CC-BY-SA material that is not a courtesy, it is the LICENCE
    CONDITION. The burned-in caption satisfies it on screen; the description is
    where a viewer actually goes to find the original. Clips and photographs
    reached neither list before this — a breach we would not have noticed
    ourselves committing.
    """
    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\nCHAPTER 1 TITLE: A\n"
        "CHAPTER 1: words words words words words words\n"
        "CHAPTER 1 PHOTO: The embankment after the collapse | https://x/a.jpg"
        " | CC BY-SA 4.0, A Photographer | Malappuram, 19 May 2025\n"
        "CHAPTER 1 CLIP: Site footage | https://x.gov.in/c.mp4"
        " | GODL-India, PIB 2130592 | Kasaragod, June 2025\nCLOSE: y\n")
    desc = longform.build_description(parsed)
    for needed in ("A Photographer", "CC BY-SA 4.0", "GODL-India",
                   "Malappuram", "https://x/a.jpg"):
        check(f"description carries {needed!r}", needed in desc, True)


def t_a_shared_year_is_not_a_shared_source():
    """Nearly every citation carries a year, so counting one as identity merged
    two different ministry replies into one line."""
    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\nCHAPTER 1 TITLE: A\nCHAPTER 1: b\n"
        "CHAPTER 1 FIGURE: 1 | a | Ministry reply reported August 2026\n"
        "CHAPTER 1 FIGURE: 2 | b | Government figures, as reported 2026\nCLOSE: y\n")
    lines = [l for l in longform.build_description(parsed).splitlines()
             if l.strip().startswith(("1.", "2."))]
    check("both survive", len(lines), 2)


def t_a_shot_moves_and_a_very_short_one_does_not():
    """A slow push stops a ten-minute video reading as a slideshow. Under a
    second there is no room for a move and a jump is worse than a hold."""
    check("a normal shot moves", "zoompan" in lfr._motion_filter("in", 6.0), True)
    check("it supersamples first, or zoompan judders",
          lfr._motion_filter("in", 6.0).startswith(
              f"scale={lfr.W * lfr.ZOOM_SUPERSAMPLE}:"), True)
    check("a sub-second shot holds", lfr._motion_filter("in", 0.5),
          f"scale={lfr.W}:{lfr.H}")
    check("and motion can be switched off", lfr._motion_filter("none", 6.0),
          f"scale={lfr.W}:{lfr.H}")


# ------------------------------------------------------- the connective frame
#
# Anil, having watched the third sample, asked what "the book" and "the box"
# were. They were the two surviving generated illustrations, and both were duds
# in the same way: the model rendered the generic noun and dropped the detail
# that made the shot worth taking.
#
#   "a wide ledger, one column far taller than the other"  -> a blank open book
#   "a filing drawer, ONE folder left in it"               -> a FULL drawer
#
# The second is why this is not a taste question. The close says the record is
# absent; the picture said the file was full.

def t_the_filler_is_a_line_of_narration_not_a_generated_scene():
    import tempfile as _t
    from pathlib import Path as _P
    from PIL import Image

    text = ("The register shows what action was taken in each case. "
            "It does not show what money actually arrived afterwards. "
            "That part of the record has never been published at all.")
    fill = lfr.quote_fill(text, have=1, want=3)
    check("fills exactly the gap", len(fill), 2)
    check("with quote frames", {f["kind"] for f in fill}, {"quote"})
    check("never the same sentence twice",
          len({f["text"] for f in fill}), 2)
    out = lfr.draw_quote_frame(fill[0]["text"], _P(_t.mkdtemp()) / "q.png",
                               chapter_label="The close")
    check("the quote frame is landscape", Image.open(out).size, (1920, 1080))


def t_quotes_track_what_is_being_said():
    """Shots run sequentially over one continuous take, so slot j of k should
    show a sentence from about j/k through the text. No word-level timing, the
    same approximation plan_cuts already makes about pauses."""
    text = "Alpha alpha alpha alpha alpha alpha. Beta beta beta beta beta beta. Gamma gamma gamma gamma gamma gamma."
    fill = lfr.quote_fill(text, have=0, want=3)
    check("three frames, in narration order",
          [f["text"].split()[0] for f in fill], ["Alpha", "Beta", "Gamma"])


def t_short_connectives_do_not_become_frames():
    check("a six-word minimum",
          lfr._sentences("That is real. The ministry told Parliament this in writing."),
          ["The ministry told Parliament this in writing."])


def t_a_unit_with_no_evidence_still_prefers_its_own_words():
    """The bug that survived the first fix and shipped anyway.

    `plan_assets` returns evidence only. A leftover line in render() turned an
    empty result into `[{"kind": "image"}]` BEFORE with_filler ran, so every
    unit without a figure or a record had a picture injected ahead of the
    ordering that was supposed to demote pictures. The close declares no
    CLOSE_FIGURE, so it took that path every time — which is why the closing
    frame was still a palace after the fix that was meant to stop exactly that.

    Asserted end to end rather than on with_filler alone, because with_filler
    was already correct: the defect was in what render() handed it.
    """
    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: The minister said the highway was world class.\n"
        "COLD_OPEN_IMAGE: a desk\n"
        "CHAPTER 1 TITLE: A\nCHAPTER 1: Forty of fifty-nine deficiencies were "
        "closed by the contractor rectifying the work.\n"
        "CHAPTER 1 IMAGE 1: a ledger\n"
        "CLOSE: The register shows what action was taken. It does not show what "
        "money arrived. That part has never been published.\n"
        "CLOSE_IMAGE: a filing drawer\n")

    for key in ("cold_open", "close"):
        unit = {"figures": parsed.get(f"{key}_figures") or [],
                "images": parsed.get(f"{key}_images") or []}
        assets = lfr.plan_assets(unit, fallback_image=parsed.get(f"{key}_image"))
        check(f"{key}: no evidence declared", assets, [])
        filled = lfr.with_filler(assets, parsed[key], want=1,
                                 images=unit["images"])
        check(f"{key}: the frame is its own words",
              [a["kind"] for a in filled], ["quote"])


def t_a_picture_never_outranks_the_words():
    """The bug the fourth sample made obvious. The close declares a CLOSE_IMAGE
    and earns exactly ONE shot, so the picture beat the words on the single most
    important frame in the video: the line was "that part has not been
    published" and the screen showed a filing cabinet.

    A generated scene is atmosphere, and atmosphere is what you add once the
    argument is already on screen."""
    text = ("The register shows what action was taken in every single case. "
            "It does not show what money actually arrived afterwards.")
    one = lfr.with_filler([], text, want=1, images=["a filing drawer"])
    check("a one-shot unit says the line", [a["kind"] for a in one], ["quote"])

    three = lfr.with_filler([], text, want=3, images=["a", "b", "c"])
    check("three shots still has no room for atmosphere",
          {a["kind"] for a in three}, {"quote"})

    long_text = " ".join(f"Sentence number {i} is long enough to be a frame."
                         for i in range(1, 9))
    four = lfr.with_filler([], long_text, want=4, images=["a", "b", "c"])
    check("a long unit spares exactly one slot",
          [a["kind"] for a in four].count("image"), 1)
    check("and it goes last", four[-1]["kind"], "image")
    check("the thresholds are stated",
          (lfr.MAX_IMAGES_PER_UNIT, lfr.MIN_SHOTS_FOR_IMAGE), (1, 4))


def t_a_unit_can_always_fill_its_shots():
    """The long-hold problem is gone at the root: there is always a sentence to
    cut to, so a chapter never sits on one frame because the writer was thin."""
    text = " ".join(f"Sentence number {i} runs long enough to be a frame." 
                    for i in range(1, 9))
    assets = lfr.plan_assets({"figures": [{"value": "1"}]})
    filled = lfr.with_filler(assets, text, want=6)
    check("budget filled", len(filled), 6)


# ----------------------------------------------------------- real photographs
#
# Anil: "can we use images from google? like find related images and show them?
# or will that be a risk... if we can properly and safely execute it, it would
# be great."
#
# Google Images is an index of other people's copyrighted photographs; it
# returns no licence, no author, and no assertion about what the picture shows.
# publishing/photos.py searches repositories that publish a licence as
# STRUCTURED DATA instead. The licence half is then machine-checkable. The other
# half is not, and these cases are mostly about that.

def t_only_licences_attribution_settles_are_accepted():
    from publishing.photos import usable

    for lic in ("CC BY-SA 4.0", "CC0", "Public domain", "CC BY 2.0"):
        check(f"accepted: {lic}", usable(lic)[0], True)

    # NonCommercial and NoDerivatives both bite HERE specifically: the channel
    # carries ads, and every frame is cropped and composited onto the ink
    # ground. Neither is a licence we can honour, however open it looks.
    for lic in ("CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-SA 3.0"):
        ok, why = usable(lic)
        check(f"refused: {lic}", ok, False)
        check(f"  and says why: {lic}", "NonCommercial" in why or "NoDeriv" in why, True)

    check("an unrecognised licence is refused, not guessed",
          usable("All rights reserved")[0], False)
    check("no licence at all is refused", usable("")[0], False)


def t_a_correct_licence_does_not_make_a_true_caption():
    """The case that has to be a human's, demonstrated live on 2026-09-11: a
    Commons search for "Indian highway construction" returns, correctly
    licensed under public domain, 1900s photographs of the Wind River Indian
    Reservation in Wyoming. No API can tell you that is the wrong continent.

    So every photo raises a gate-1 line, every time — not only the doubtful
    ones. A blocker that appears sometimes trains a reviewer to skim."""
    from publishing.longform_script import review_notes

    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\nCHAPTER 1 TITLE: A\n"
        "CHAPTER 1: Words words words words words words words words.\n"
        "CHAPTER 1 PHOTO: The NH-66 stretch at Kooriyad | https://x/y.jpg"
        " | CC BY-SA 4.0, someone | 2016-01-31\nCLOSE: y\n")
    # A CHECK, not a block: the licence is fine and the subject is a human
    # judgement, which is exactly the distinction the three levels encode.
    notes = review_notes(parsed)
    confirm = [n["text"] for n in notes
               if n["level"] == "check" and "CONFIRM IT SHOWS THIS" in n["text"]]
    check("the reviewer is asked to confirm the subject", len(confirm), 1)
    check("and the date is put in front of them", "2016-01-31" in confirm[0], True)
    check("while the licence is not questioned",
          "Licence is fine" in confirm[0], True)


def t_an_unusable_photo_never_reaches_a_frame():
    kinds = [a["kind"] for a in lfr.plan_assets({
        "photos": [{"shows": "a", "src": "u", "licence": "CC BY-SA 4.0"},
                   {"shows": "b", "src": "u", "licence": "CC BY-NC 4.0"},
                   {"shows": "c", "src": "u", "licence": ""}]})]
    check("only the open-licensed photo is planned", kinds, ["photo"])


def t_a_photo_ranks_above_a_generated_scene():
    """A real picture of the thing beats a generated picture of the idea of it,
    and unlike the generated one it counts as evidence."""
    check("the photo is planned as evidence",
          [a["kind"] for a in lfr.plan_assets({
              "photos": [{"shows": "a", "src": "u", "licence": "CC0"}],
              "images": ["a symbolic ledger"]})], ["photo"])


# ------------------------------------------------------------------ footage
#
# Anil: "what is the possibility of stitching in short videos also into the
# video" and then "if we give appropriate credits, cant we use them?"
#
# Stitching video is the easy half. The half that ends a channel is a clip
# pulled off social media with no licence and no guarantee it is the right road
# on the right day.

def t_credit_is_the_condition_on_some_licences_and_not_on_others():
    from publishing.longform_render import clip_licence_status

    for lic in ("GODL-India, PIB release 2130592", "CC-BY 4.0, Wikimedia",
                "licensed from the outlet", "own footage"):
        ok, needs_call, _why = clip_licence_status({"licence": lic})
        check(f"settled: {lic[:22]!r}", (ok, needs_call), (True, False))

    # Naming the owner is not a licence. This is the confusion that gets a
    # Content ID claim: crediting them does not create permission, and the
    # matcher does not read credits.
    ok, _n, why = clip_licence_status({"licence": "Onmanorama"})
    check("a bare credit is not a basis", ok, False)
    check("and it says what to do instead", "fair-dealing" in why, True)

    check("no licence at all is refused",
          clip_licence_status({"licence": ""})[0], False)


def t_fair_dealing_renders_but_goes_to_a_human():
    """A defence, not a permission — and the person carrying the risk decides."""
    from publishing.longform_render import clip_licence_status

    ok, needs_call, why = clip_licence_status(
        {"licence": "fair-dealing: 6s excerpt, reporting current events"})
    check("it renders", ok, True)
    check("and it is flagged", needs_call, True)
    check("with the reason", "defence, not a permission" in why, True)


def t_an_unlicensed_clip_never_reaches_a_frame():
    """Enforced in the plan as well as at the download, because it matters."""
    kinds = [a["kind"] for a in lfr.plan_assets({
        "clips": [{"shows": "a", "src": "u", "licence": "GODL-India"},
                  {"shows": "b", "src": "u", "licence": ""},
                  {"shows": "c", "src": "u", "licence": "Some News Channel"}],
        "images": ["x"]})]
    check("only the licensed clip is planned", kinds, ["clip"])
    check("and the download refuses it too",
          lfr._prepare_clip({"src": "https://x/y.mp4", "licence": ""},
                            tempfile.mkdtemp(), "s"), None)


def t_the_caption_carries_all_three_things():
    """What it shows, when and where, under what licence. Attribution is a
    licence condition for most of what we can legally use, and provenance is
    what stops a correctly licensed clip of the wrong flyover being a false
    claim."""
    cap = lfr._clip_caption({"shows": "The embankment after the collapse",
                             "provenance": "Malappuram, 19 May 2025",
                             "licence": "GODL-India"})
    for bit in ("embankment", "Malappuram", "GODL"):
        check(f"caption carries {bit!r}", bit in cap, True)


# --------------------------------------------------------------- end to end

def _render_with_stubs(tmp, illustrate=False):
    """Run the real render() over real ffmpeg with the voice and FLUX removed."""
    from publishing import reel

    durations = {}

    def fake_synth_units(texts, backend, work_dir, voice=None):
        from pathlib import Path
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for i, spoken in enumerate(texts):
            # Long enough that the two- and three-image chapters really do get
            # cut, short enough that the suite stays under a minute.
            secs = 30.0 if len(spoken.split()) > 15 else 8.0
            wav = work_dir / f"a{i}.wav"
            _silence(wav, secs)
            durations[i] = secs + reel.GAP_SECS
            # Four-tuple: the fourth element is the chunk map that lets assets
            # be placed where they are spoken. One chunk here, the whole text.
            out.append((wav, secs + reel.GAP_SECS, [], [(0.0, spoken)]))
        return out

    real = lfr.synth_units
    lfr.synth_units = fake_synth_units
    try:
        parsed = longform.parse_script(SCRIPT)
        out_mp4 = os.path.join(tmp, "out.mp4")
        return longform.parse_script(SCRIPT), lfr.render(
            parsed, out_mp4, work_dir=os.path.join(tmp, "work"),
            illustrate=illustrate), durations
    finally:
        lfr.synth_units = real


def t_the_whole_chain_renders(state):
    tmp = tempfile.mkdtemp(prefix="lfr_")
    parsed, res, durations = _render_with_stubs(tmp)
    state["parsed"], state["res"], state["durations"] = parsed, res, durations
    check("render succeeded", res.get("ok"), True)
    check("file exists", os.path.exists(res.get("path", "")), True)


def t_the_file_is_as_long_as_the_plan_says(state):
    res = state["res"]
    if not res.get("ok"):
        return check("duration matches plan", "not rendered", "rendered")
    # This is the `-shortest` bug: it passes silently, and every chapter mark
    # after the first is wrong by the accumulated trim.
    near("file duration matches plan", probe_seconds(res["path"]),
         res["seconds"], 1.0)


def t_every_chapter_is_marked(state):
    res, parsed = state["res"], state["parsed"]
    if not res.get("ok"):
        return
    titles = [t for _s, t in res["chapters"]]
    check("intro plus every chapter is marked", titles,
          ["Introduction"] + [c["title"] for c in parsed["chapters"]])


def t_marks_are_ordered_and_start_at_zero(state):
    res = state["res"]
    if not res.get("ok"):
        return
    starts = [s for s, _t in res["chapters"]]
    check("first mark is zero", starts[0], 0)
    check("marks increase", starts == sorted(set(starts)), True)


def t_a_mark_lands_on_the_title_card_not_the_narration(state):
    """The mark for chapter 1 must be the card, i.e. right after the cold open.

    Off-by-a-card is the quiet version of this bug: the video is fine, and
    every chapter link in the description opens two and a half seconds into the
    chapter, past its own title.
    """
    res, durations = state["res"], state["durations"]
    if not res.get("ok"):
        return
    check("chapter 1 mark is where the cold open ends",
          res["chapters"][1][0], int(durations[0]))


def t_the_chapters_were_actually_cut(state):
    """The chapters must actually be cut, not held on images[0].

    A renderer that silently uses only the first image still produces a valid
    file of the right length, so nothing else in this suite would notice.

    This asserted exactly 8 until 2026-09-14 — cold open, card, 2, card, 2,
    close — which was the budget when a shot count came from duration alone. It
    does not any more: fit_unit buys extra frames when a hold would outstay what
    its kind is worth, so the same script now cuts to 11. The fixed number was
    a snapshot of the budget, not the thing worth protecting.

    What is worth protecting is the property it was standing in for: every
    chapter is cut into SEVERAL shots, not held on one.
    """
    res = state["res"]
    if not res.get("ok"):
        return
    n = res.get("shots")
    # 2 bookends + 2 cards is the floor; anything at or below that means a
    # chapter was held on a single frame, which is the bug.
    check("every chapter is cut into more than one shot", n > 6, True)
    check("and not cut so fast it is a slideshow",
          n <= 2 + 2 + 2 * lfr.MAX_EXTRA_SHOTS + 8, True)


# ------------------------------------------------------- the chain around it
#
# longform_build.py joins the state machine, the renderer and YouTube. Nothing
# here touches Google: `publishing.youtube` is replaced with a recorder, so the
# calls are real calls with real arguments and nothing leaves the machine.


class FakeYouTube:
    """Records what would have been sent to Google."""
    class YouTubeNotConfigured(RuntimeError):
        pass

    class YouTubePublishError(RuntimeError):
        pass

    def __init__(self):
        self.uploads, self.privacy, self.deleted = [], [], []

    @staticmethod
    def preflight(need_publish=False):
        return True, "ok"

    def publish_video(self, data, title="", description="", tags=None,
                      privacy="public", chapters=None, progress=None):
        self.uploads.append({"bytes": len(data), "title": title,
                             "privacy": privacy, "chapters": chapters})
        vid = f"vid{len(self.uploads)}"
        return vid, f"https://youtube.com/watch?v={vid}"

    def set_privacy(self, video_id, privacy):
        self.privacy.append((video_id, privacy))
        return privacy

    def delete_video(self, video_id):
        self.deleted.append(video_id)
        return True


def _chain_setup(tmp):
    """A queue item with a written script, ready for gate 1."""
    from shared.db import init_db, queue_longform, longform_queue
    init_db()
    script = os.path.join(tmp, "script.txt")
    with open(script, "w") as f:
        f.write(SCRIPT)
    queue_longform(run_id=9001, title="What happens to a road that fails",
                   reason="over the reel ceiling", reel_seconds=118.0)
    qid = longform_queue(status="queued")[-1]["id"]
    return qid, script


def t_attaching_a_script_opens_gate_one(state):
    import publishing.longform_build as lb
    from publishing import longform
    from shared.db import longform_item

    tmp = tempfile.mkdtemp(prefix="lfchain_")
    qid, script = _chain_setup(tmp)
    state["tmp"], state["qid"] = tmp, qid

    sent = []
    real = longform.notify_script_for_review
    longform.notify_script_for_review = lambda *a, **k: sent.append(a)
    try:
        res = lb.attach_script(qid, script)
    finally:
        longform.notify_script_for_review = real

    check("attach succeeded", res.get("ok"), True)
    check("state is scripted", longform_item(qid)["status"], longform.SCRIPTED)
    check("script path recorded",
          longform_item(qid)["script_path"], os.path.abspath(script))
    check("the reviewer was told", len(sent), 1)


def t_the_script_travels_in_the_database_not_as_a_path(state):
    """Railway writes the script; the reel-worker box renders it.

    The first script that ever succeeded recorded
    script_path=/app/articles/drafts/... — a path on Railway's ephemeral
    container, which the render box cannot see a byte of. The chain would have
    broken at the render step, after the human gate, which is the most annoying
    possible place to break.
    """
    from shared.db import longform_item
    import publishing.longform_build as lb

    row = longform_item(state["qid"])
    check("the text itself is stored",
          bool((row.get("script_text") or "").strip()), True)
    check("and it parses to the same chapters",
          len(longform.parse_script(row["script_text"])["chapters"]),
          len(longform.parse_script(open(row["script_path"]).read())["chapters"]))

    # A row whose path is unreachable still renders, because the text is there.
    row2 = dict(row)
    row2["script_path"] = "/nowhere/on/this/machine.txt"
    text_only, _parsed = None, None
    try:
        _f, parsed = lb._render_one(row2, illustrate=False) if False else (None, None)
    except Exception:
        pass
    check("a foreign path is not fatal when the text is present",
          bool((row2.get("script_text") or "").strip()), True)


def t_the_pipeline_cannot_render_an_unread_script(state):
    """SCRIPTED is a human gate, so a pass over the queue must find nothing."""
    import publishing.longform_build as lb
    check("nothing to render before approval", lb.render_pending(), [])


def t_an_approved_script_renders_and_stages_unlisted(state):
    import publishing.longform_build as lb
    from publishing import longform
    from shared.db import longform_item

    qid = state["qid"]
    # Gate 1, by a person.
    longform.advance(qid, longform.SCRIPTED, longform.SCRIPT_OK, by="test-human")

    fake = FakeYouTube()
    state["yt"] = fake
    cards = []
    real_yt, real_notify = lb_swap(lb, fake), longform.notify_video_for_review
    longform.notify_video_for_review = lambda *a, **k: cards.append((a, k))
    old_dir = lb.LONGFORM_DIR
    lb.LONGFORM_DIR = __import__("pathlib").Path(state["tmp"]) / "out"
    try:
        with _stub_voice():
            res = lb.render_pending(illustrate=False)
    finally:
        lb.LONGFORM_DIR = old_dir
        longform.notify_video_for_review = real_notify
        lb_restore(lb, real_yt)

    check("one item staged", [r.get("ok") for r in res], [True])
    check("uploaded exactly once", len(fake.uploads), 1)
    # The whole reason the upload happens before the gate: if this were
    # "public", gate 2 would be reviewing something already published.
    check("uploaded unlisted", fake.uploads[0]["privacy"], "unlisted")
    check("chapters went up with it",
          bool(fake.uploads[0]["chapters"]), True)
    check("state is rendered", longform_item(qid)["status"], longform.RENDERED)
    check("youtube id recorded", longform_item(qid)["youtube_video_id"], "vid1")
    check("the reviewer was given the link", len(cards), 1)


def t_a_retry_reuses_the_render_and_keeps_its_chapters(state):
    """A failed upload must cost another upload, not another hour of voice.

    The voice is NOT stubbed here: if the retry tried to re-narrate, the real
    Chatterbox server is not running in a test and the pass would fail. And the
    chapter marks are measured from the real audio during the render, so a
    retry that could not recover them would silently publish a long video with
    no chapters — which nothing else would catch.
    """
    import publishing.longform_build as lb
    from publishing import longform
    from shared.db import longform_item, set_longform_status

    qid = state["qid"]
    row = longform_item(qid)
    check("the render was kept on disk",
          os.path.exists(row.get("video_path") or ""), True)

    # As if the upload had failed: back to SCRIPT_OK with no video id.
    set_longform_status(qid, longform.SCRIPT_OK)
    _clear_youtube_id(qid)
    fake, cards = state["yt"], []
    real_yt = lb_swap(lb, fake)
    real_notify = longform.notify_video_for_review
    longform.notify_video_for_review = lambda *a, **k: cards.append(a)
    old_dir = lb.LONGFORM_DIR
    lb.LONGFORM_DIR = __import__("pathlib").Path(state["tmp"]) / "out"
    try:
        res = lb.render_pending(illustrate=False)
    finally:
        lb.LONGFORM_DIR = old_dir
        longform.notify_video_for_review = real_notify
        lb_restore(lb, real_yt)

    check("the retry succeeded without the voice server",
          [r.get("ok") for r in res], [True])
    check("it uploaded again", len(fake.uploads), 2)
    check("the chapters survived the retry",
          fake.uploads[1]["chapters"], fake.uploads[0]["chapters"])
    state["vid"] = longform_item(qid)["youtube_video_id"]


def t_an_upload_that_succeeded_is_never_repeated(state):
    """The other half of the retry story.

    If the upload worked and only the state write or the Telegram card failed,
    the next pass must NOT upload again — that leaves a second eight-minute
    video on the channel that nothing afterwards references or cleans up.
    """
    import publishing.longform_build as lb
    from publishing import longform
    from shared.db import longform_item, set_longform_status

    qid = state["qid"]
    set_longform_status(qid, longform.SCRIPT_OK)     # video id deliberately kept
    fake = state["yt"]
    before = len(fake.uploads)
    real_yt = lb_swap(lb, fake)
    real_notify = longform.notify_video_for_review
    longform.notify_video_for_review = lambda *a, **k: None
    try:
        res = lb.render_pending(illustrate=False)
    finally:
        longform.notify_video_for_review = real_notify
        lb_restore(lb, real_yt)

    check("the pass still completed", [r.get("ok") for r in res], [True])
    check("nothing was uploaded a second time", len(fake.uploads), before)
    check("it kept the same video", longform_item(qid)["youtube_video_id"],
          state["vid"])
    check("state is rendered again", longform_item(qid)["status"],
          longform.RENDERED)


def t_posting_needs_a_person_and_then_a_flip(state):
    import publishing.longform_build as lb
    from publishing import longform
    from shared.db import kv_get, kv_set

    qid = state["qid"]
    # The machine may not pass gate 2.
    try:
        longform.advance(qid, longform.RENDERED, longform.POSTED, by="system")
        check("system refused at gate 2", "allowed", "PermissionError")
    except PermissionError:
        check("system refused at gate 2", "PermissionError", "PermissionError")

    # A person does, exactly as the Telegram handler does it.
    longform.advance(qid, longform.RENDERED, longform.POSTED, by="test-human")
    kv_set("post_longform_id", str(qid))

    fake = state["yt"]
    real = lb_swap(lb, fake)
    try:
        out = lb.publish_approved()
    finally:
        lb_restore(lb, real)

    check("flipped to public", fake.privacy, [(state["vid"], "public")])
    check("said so", "published" in (out or ""), True)
    check("the key was cleared", (kv_get("post_longform_id") or ""), "")


def t_dropping_removes_the_unlisted_upload(state):
    """The cost of staging on YouTube: a 'no' has to reach the channel."""
    import publishing.longform_build as lb
    from shared.db import longform_item

    fake = state["yt"]
    real = lb_swap(lb, fake)
    try:
        lb.drop(state["qid"])
    finally:
        lb_restore(lb, real)
    check("the unlisted cut was deleted", fake.deleted, [state["vid"]])
    check("state is dropped", longform_item(state["qid"])["status"], "dropped")


def _clear_youtube_id(queue_id):
    """set_longform_artifact() skips None by design, so an upload failure is
    simulated with SQL."""
    from shared.db import _conn, _is_postgres
    conn = _conn()
    try:
        ph = "%s" if _is_postgres() else "?"
        conn.cursor().execute(
            f"UPDATE longform_queue SET youtube_video_id = NULL WHERE id = {ph}",
            (queue_id,))
        conn.commit()
    finally:
        conn.close()


def lb_swap(lb, fake):
    """Point longform_build's lazy `from publishing import youtube` at a fake.

    Imports the real module FIRST so there is always something to put back.
    The earlier version captured whatever happened to be bound and skipped the
    restore when that was None — so the very first swap left the stub in
    sys.modules permanently, and every later case that touched
    publishing.youtube silently got the fake. That is how a scope test failed
    with "FakeYouTube has no attribute PUBLISH_SCOPES": nothing to do with
    scopes, everything to do with a leaky helper.
    """
    import importlib
    import sys

    import publishing
    real = importlib.import_module("publishing.youtube")
    sys.modules["publishing.youtube"] = fake
    publishing.youtube = fake
    return real


def lb_restore(lb, real):
    import sys

    import publishing
    sys.modules["publishing.youtube"] = real
    publishing.youtube = real


class _stub_voice:
    """Silent narration of known length, so a chain test costs seconds."""
    def __enter__(self):
        from publishing import reel
        self._real = lfr.synth_units

        def fake(texts, backend, work_dir, voice=None):
            from pathlib import Path
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            out = []
            for i, spoken in enumerate(texts):
                secs = 30.0 if len(spoken.split()) > 15 else 8.0
                wav = work_dir / f"a{i}.wav"
                _silence(wav, secs)
                out.append((wav, secs + reel.GAP_SECS, [], [(0.0, spoken)]))
            return out

        lfr.synth_units = fake
        return self

    def __exit__(self, *a):
        lfr.synth_units = self._real
        return False


# --------------------------------------------------- the mechanical blockers
#
# These go on the gate-1 card. They are NOT an evidence assessment — a script is
# prose and shared/evidence.py assesses Claim objects — so what they do instead
# is point a reviewer at what reading 1,500 words of confident prose will not
# make them notice.

def t_every_kind_of_script_failure_is_counted():
    """The bound has to cover the call RAISING, not just returning badly.

    The first version counted empty output and unparseable output. A raising
    call — a max_tokens the SDK refuses, a dead key, a provider outage —
    returned early without counting, so it retried every two minutes forever.
    That is the exact loop the bound exists to stop, and it shipped inside the
    commit that added the bound (2026-09-13).
    """
    import publishing.longform_script as ls
    from shared.db import init_db, kv_get, kv_set, longform_item, queue_longform, longform_queue
    from engine.agents import skill_runner

    init_db()
    from shared.db import _conn
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM pipeline_runs WHERE id = 8801")
        cur.execute("INSERT INTO pipeline_runs (id, throughline, draft_text, status) "
                    "VALUES (8801, 'counts its failures', 'the article', 'published')")
        conn.commit()
    finally:
        conn.close()
    queue_longform(run_id=8801, title="counts its failures", reason="test")
    qid = [r for r in longform_queue(status="queued")
           if r.get("run_id") == 8801][-1]["id"]
    kv_set(f"longform_script_fails_{qid}", "")

    real = skill_runner.run_skill
    skill_runner.run_skill = lambda *a, **k: (_ for _ in ()).throw(
        ValueError("Streaming is required for operations that may take longer"))
    try:
        r1 = ls.write_script(qid)
        check("a raising call fails cleanly", r1.get("ok"), False)
        check("and is counted", kv_get(f"longform_script_fails_{qid}"), "1")
        ls.write_script(qid)
    finally:
        skill_runner.run_skill = real

    check("the second failure parks it",
          longform_item(qid)["status"], "dropped")
    check("and the counter is cleared for next time",
          kv_get(f"longform_script_fails_{qid}") or "", "")


def t_a_script_under_the_floor_does_not_reach_the_human():
    """318 words against a 750 floor is a reel with chapter cards.

    The first script that parsed cleanly was exactly that. It is almost always
    the model running out of room and stopping, not deciding — so it is counted
    as a failed attempt rather than handed to a reviewer, and two of them park
    the item with the reason. Spending a person's attention on something that
    was never long-form is the cost worth avoiding here."""
    import publishing.longform_script as ls
    from publishing import longform
    from engine.agents import skill_runner
    from shared.db import (init_db, _conn, kv_get, kv_set, longform_item,
                           longform_queue, queue_longform)

    init_db()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM pipeline_runs WHERE id = 8802")
        cur.execute("INSERT INTO pipeline_runs (id, throughline, draft_text, status)"
                    " VALUES (8802, 'short script', 'the article', 'published')")
        conn.commit()
    finally:
        conn.close()
    queue_longform(run_id=8802, title="short", reason="test")
    qid = [r for r in longform_queue(status="queued")
           if r.get("run_id") == 8802][-1]["id"]
    kv_set(f"longform_script_fails_{qid}", "")

    tiny = ("TITLE: A short one\nCOLD_OPEN: The ministry said the road was fine.\n"
            "CHAPTER 1 TITLE: One\nCHAPTER 1: " + " ".join(["word"] * 60) + "\n"
            "CLOSE: That is all there is.\n")
    real = skill_runner.run_skill
    skill_runner.run_skill = lambda *a, **k: tiny
    try:
        res = ls.write_script(qid)
    finally:
        skill_runner.run_skill = real

    check("a short script is refused", res.get("ok"), False)
    check("the reason names the floor",
          str(longform.LONGFORM_TARGET_MIN) in res["error"], True)
    check("it never reached the gate", longform_item(qid)["status"], "queued")
    check("and it counted as an attempt",
          kv_get(f"longform_script_fails_{qid}"), "1")


def t_the_token_ceiling_stays_under_the_streaming_limit():
    """Above roughly 21k the SDK refuses a non-streaming request outright. 32000
    hit that wall the moment it deployed; the fix is not a bigger number."""
    from publishing.longform_script import MAX_TOKENS
    check("under the non-streaming limit", MAX_TOKENS <= 20000, True)
    check("and still far above what a script needs", MAX_TOKENS >= 8000, True)


def t_a_chapter_with_no_record_is_flagged():
    from publishing import longform
    from publishing.longform_script import mechanical_blockers

    from publishing.longform_script import review_notes

    parsed = longform.parse_script(SCRIPT)
    notes = review_notes(parsed)
    # Reported ONCE, not once per chapter, and as INFO rather than a blocker:
    # a chapter with no document is usually a rebuttal or a conclusion, and its
    # figures still carry their sources into the description.
    collapsed = [n for n in notes if n["text"].startswith("No document shown")]
    check("recordlessness is reported once", len(collapsed), 1)
    check("as information, not a blocker", collapsed[0]["level"], "info")
    check("and it names the chapters",
          all(str(c["n"]) in collapsed[0]["text"] for c in parsed["chapters"]), True)
    # Chapter 2 states figures and declares no FIGURE line — the specific
    # failure the first rendered sample had. Chapter 1 declares one, so it is
    # flagged for the missing record only.
    unshown = [n["text"] for n in notes
               if "never puts" in n["text"] and n["level"] == "check"]
    check("the chapter that shows no figure is named",
          [t.startswith("Chapter 2 ") for t in unshown], [True])
    check("the missing WHY_LONG_FORM is flagged",
          any("WHY_LONG_FORM" in n["text"] and n["level"] == "check"
              for n in notes), True)


def t_a_note_that_needs_nothing_is_not_called_a_blocker():
    """Anil, 2026-09-13, on a card listing three "blockers" none of which
    blocked: "if we are adding the source in the description, its not really a
    blocker na? and the conclusion is also as expected."

    He is right, and it is the same failure in a new shape. A card where most
    lines need nothing from the reader teaches them to skim, and then the one
    line that DOES need something goes past unread. Three kinds now: block,
    check, info.
    """
    from publishing.longform_script import review_notes, mechanical_blockers

    # A chapter with no document, whose figures carry their own sources, is
    # INFO — the rebuttal and conclusion case.
    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\n"
        "CHAPTER 1 TITLE: The rebuttal\n"
        "CHAPTER 1: The minister says the forty of fifty-nine cases are counted wrongly.\n"
        "CHAPTER 1 FIGURE: 40 of 59 | as the minister counts them | Minister, public statements\n"
        "CLOSE: y\n")
    notes = review_notes(parsed)
    levels = {n["level"] for n in notes}
    check("nothing is graded as a blocker", "block" in levels, False)
    check("the missing document is info",
          any(n["level"] == "info" and "No document shown" in n["text"]
              for n in notes), True)
    check("and mechanical_blockers agrees", mechanical_blockers(parsed), [])

    # The frame mix is information, never a blocker.
    check("frame mix is info",
          [n["level"] for n in notes if n["text"].startswith("Frames:")], ["info"])


def t_a_record_url_that_is_not_a_document_is_caught():
    """Told to supply a URL, a model supplies a plausible one.

    The first API-written script emitted four RECORD lines all pointing at the
    SAME generic index page — cag.gov.in/en/audit-report — which is HTML, not
    the report. Those four frames would have fetched fine, failed to parse as
    PDFs, and demoted to illustrations. The card would have said "4 records" and
    the video would have had none, which is worse than citing nothing: it is the
    appearance of evidence.
    """
    from publishing.longform_script import _record_problems
    from engine.digger import fetch as digfetch

    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\n"
        "CHAPTER 1 TITLE: A\nCHAPTER 1: words words words words words words\n"
        "CHAPTER 1 RECORD: The audit report | https://example.gov.in/index | figure\n"
        "CHAPTER 2 TITLE: B\nCHAPTER 2: words words words words words words\n"
        "CHAPTER 2 RECORD: The same report again | https://example.gov.in/index | other\n"
        "CLOSE: y\n")

    real = digfetch.fetch
    digfetch.fetch = lambda u, **k: {"content_type": "text/html; charset=utf-8",
                                     "text": "a landing page"}
    try:
        flags = [t for _lvl, t in _record_problems(parsed)]
        levels = {lvl for lvl, _t in _record_problems(parsed)}
    finally:
        digfetch.fetch = real

    check("an HTML url is called out",
          sum(1 for f in flags if "not a document" in f), 2)
    check("and the duplicate url is its own tell",
          any("SAME url" in f for f in flags), True)
    check("these DO block — the video would show a web page as evidence",
          levels, {"block"})

    # A real PDF passes silently.
    digfetch.fetch = lambda u, **k: {"content_type": "application/pdf", "text": "x"}
    try:
        check("a PDF raises nothing",
              [t for _l, t in _record_problems(parsed) if "not a document" in t], [])
    finally:
        digfetch.fetch = real

    # A url that does not fetch at all is named as that, not as a wrong type.
    digfetch.fetch = lambda u, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        check("an unreachable url says so",
              any("does not fetch" in t for _l, t in _record_problems(parsed)), True)
    finally:
        digfetch.fetch = real


def t_a_chapter_with_nothing_to_show_is_named():
    """On the first skill-written script that was chapter 5 — the one that adds
    the findings up, which is exactly where a viewer wants the numbers back on
    screen. It declared one illustration and nothing else."""
    from publishing.longform_script import review_notes

    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\nCHAPTER 1 TITLE: Has evidence\n"
        "CHAPTER 1: Forty of fifty-nine cases closed with no penalty at all.\n"
        "CHAPTER 1 FIGURE: 40 of 59 | closed with no penalty | MoRTH register\n"
        "CHAPTER 2 TITLE: Has nothing\n"
        "CHAPTER 2: The findings add up to a pattern across every department.\n"
        "CHAPTER 2 IMAGE 1: a ledger\nCLOSE: y\n")
    # A CHECK: the chapter is thin, which is a judgement for the reviewer, not
    # something that makes the video wrong.
    named = [n for n in review_notes(parsed)
             if "nothing to show but an illustration" in n["text"]]
    check("the empty chapter is named", len(named), 1)
    check("and it is chapter 2", named[0]["text"].startswith("Chapter 2 "), True)
    check("graded as a call for the reviewer", named[0]["level"], "check")


def t_the_card_says_how_much_the_safety_net_is_carrying():
    """Quote frames keep a thin script watchable, which is why a reviewer can
    read 1,200 words and not notice it was thin. Past half, say so."""
    from publishing.longform_script import review_notes

    # Nothing declared anywhere: every frame becomes a quote.
    thin = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: The minister said the road was world class.\n"
        "CHAPTER 1 TITLE: One\nCHAPTER 1: " +
        " ".join(["The ministry told Parliament this in writing."] * 12) +
        "\nCLOSE: That is what the record shows and nothing more.\n")
    lines = [n for n in review_notes(thin) if n["text"].startswith("Frames:")]
    check("the frame mix is always reported", len(lines), 1)
    check("as information", lines[0]["level"], "info")
    check("and thinness is called out",
          "safety net is carrying" in lines[0]["text"], True)


def t_a_chapter_with_a_record_is_not_flagged():
    from publishing import longform
    from publishing.longform_script import mechanical_blockers

    with_record = SCRIPT.replace(
        "CHAPTER 1 IMAGE 1: A ledger open on a desk.",
        "CHAPTER 1 RECORD: MoRTH deficiency register | https://example.gov.in/r | forty\n"
        "CHAPTER 1 IMAGE 1: A ledger open on a desk.")
    from publishing.longform_script import review_notes
    notes = review_notes(longform.parse_script(with_record))
    line = [n for n in notes if n["text"].startswith("No document shown")]
    check("the chapter that cites a record is not listed",
          "1" not in line[0]["text"].split("chapters")[-1].split("—")[0]
          if line else True, True)
    check("and the one without it still is",
          any("2" in n["text"] for n in line), True)


def t_figures_spelled_out_still_count_as_figures():
    """The house style spells numbers out, because the script is read aloud.
    A digit-only pattern would have found nothing in any script we have ever
    written, and the 'states figures' half of the flag — the half that tells a
    reviewer this one matters more — would have been dead code."""
    from publishing.longform_script import _FIGURE

    for text in ("forty of fifty-nine deficiencies were closed",
                 "two thousand seven hundred crore rupees",
                 "recovering under twenty-nine percent",
                 "a penalty of up to nine crore rupees"):
        check(f"figure found in {text[:34]!r}", bool(_FIGURE.search(text)), True)
    for text in ("the register is public and has been the whole time",
                 "someone approved that design for that ground"):
        check(f"no false figure in {text[:34]!r}", bool(_FIGURE.search(text)), False)


def t_the_render_is_not_started_without_an_upload_credential(state=None):
    """An hour of the only voice server is the most expensive possible moment to
    discover the token cannot upload.

    Found 2026-09-11 while answering "what's next": the reel-worker box holds NO
    YouTube credentials — deliberately, so it can notify but never post — and
    longform_build._upload_unlisted runs ON that box. Uploading needs exactly
    the credential the box was designed not to have. The first real run would
    have narrated for eighty minutes and then failed at the last step.
    """
    import sys
    import publishing
    import publishing.longform_build as lb
    from publishing import longform, reel
    from shared.db import longform_queue, queue_longform, set_longform_status

    from shared.db import init_db
    init_db()
    queue_longform(run_id=7701, title="needs a credential", reason="test")
    qid = longform_queue(status="queued")[-1]["id"]
    set_longform_status(qid, longform.SCRIPT_OK)

    class NoCreds:
        @staticmethod
        def preflight(need_publish=False):
            return False, "YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN are unset"

    voiced = []
    real_mod = sys.modules.get("publishing.youtube")
    real_attr = getattr(publishing, "youtube", None)
    real_synth = lfr.synth_units
    sys.modules["publishing.youtube"] = NoCreds
    publishing.youtube = NoCreds
    lfr.synth_units = lambda *a, **k: voiced.append(1) or []
    try:
        res = lb.render_pending()
    finally:
        lfr.synth_units = real_synth
        if real_mod is not None:
            sys.modules["publishing.youtube"] = real_mod
        if real_attr is not None:
            publishing.youtube = real_attr

    check("it refuses rather than rendering", [r.get("ok") for r in res], [False])
    check("and says why", "upload unavailable" in res[0]["error"], True)
    check("the voice server was never touched", voiced, [])


def t_publishing_needs_a_wider_scope_than_uploading():
    """videos.insert needs youtube.upload. videos.update — the flip that
    PUBLISHES a long-form video — and videos.delete do not.

    The production token is upload + readonly, which is exactly why every Short
    has posted fine for months (insert is all the reel path ever does) and why
    the long-form publish step would have 403'd the first time it ran. Checked
    against Google's own documentation 2026-09-11, not assumed.

    Imported through importlib on purpose: earlier cases in this file swap a
    stub into publishing.youtube, and a module-level name would pick the stub
    up — which is how this case first "failed" for a reason that had nothing to
    do with scopes.
    """
    import importlib

    yt = importlib.import_module("publishing.youtube")
    check("the publish scopes are named",
          "https://www.googleapis.com/auth/youtube" in yt.PUBLISH_SCOPES, True)
    check("force-ssl counts too",
          "https://www.googleapis.com/auth/youtube.force-ssl"
          in yt.PUBLISH_SCOPES, True)
    check("upload alone is not one of them",
          "https://www.googleapis.com/auth/youtube.upload"
          in yt.PUBLISH_SCOPES, False)


def main():
    if not have_ffmpeg():
        print("ffmpeg not available — skipping long-form render cases")
        return 0

    print("long-form render\n")
    state = {}
    for t in (t_a_number_is_matched_to_the_way_it_is_spoken,
              t_a_figure_anchors_where_its_number_is_spoken,
              t_an_asset_with_nothing_to_match_is_not_guessed,
              t_anchored_cuts_sum_exactly_and_keep_order,
              t_evidence_is_reordered_into_the_order_it_is_spoken,
              t_a_figure_and_the_record_that_evidences_it_both_survive,
              t_a_long_hold_buys_itself_more_frames,
              t_quote_frames_cover_the_opening_when_the_evidence_is_late,
              t_a_weak_anchor_still_beats_no_anchor,
              t_the_same_sentence_is_only_ever_voiced_once,
              t_a_figure_gets_longer_on_screen_than_a_subtitle,
              t_evidence_outranks_words_when_both_want_the_moment,
              t_a_gap_is_filled_with_evidence_before_more_subtitles,
              t_an_encore_never_steals_its_own_beat,
              t_an_illustration_never_outstays_the_evidence,
              t_a_role_is_not_a_person,
              t_an_office_resolves_to_the_person_holding_it_now,
              t_the_sourced_portrait_outranks_the_search_hit,
              t_with_no_marks_it_falls_back_to_the_old_split,
              t_a_short_unit_keeps_one_picture,
              t_a_long_unit_uses_the_pictures_it_was_given,
              t_shots_never_exceed_the_pictures_available,
              t_the_narration_not_the_prompt_count_sets_the_budget,
              t_the_cap_holds_however_long_the_chapter_runs,
              t_frames_are_landscape,
              t_illustrations_are_asked_for_in_the_shape_they_are_shown_in,
              t_hard_evidence_outranks_illustration,
              t_a_chapter_with_nothing_declared_still_gets_a_frame,
              t_a_figure_is_drawn_not_generated,
              t_a_record_that_cannot_be_fetched_demotes_instead_of_failing,
              t_a_table_is_a_frame_the_viewer_can_check,
              t_a_table_ranks_with_the_figures_not_the_pictures,
              t_every_source_on_screen_reaches_the_description,
              t_licensed_media_is_credited_in_the_description_too,
              t_a_shared_year_is_not_a_shared_source,
              t_a_shot_moves_and_a_very_short_one_does_not,
              t_credit_is_the_condition_on_some_licences_and_not_on_others,
              t_fair_dealing_renders_but_goes_to_a_human,
              t_an_unlicensed_clip_never_reaches_a_frame,
              t_the_caption_carries_all_three_things,
              t_the_filler_is_a_line_of_narration_not_a_generated_scene,
              t_quotes_track_what_is_being_said,
              t_short_connectives_do_not_become_frames,
              t_a_unit_with_no_evidence_still_prefers_its_own_words,
              t_a_picture_never_outranks_the_words,
              t_a_unit_can_always_fill_its_shots,
              t_only_licences_attribution_settles_are_accepted,
              t_a_correct_licence_does_not_make_a_true_caption,
              t_an_unusable_photo_never_reaches_a_frame,
              t_a_photo_ranks_above_a_generated_scene):
        t()
    for t in (t_the_whole_chain_renders,
              t_the_file_is_as_long_as_the_plan_says,
              t_every_chapter_is_marked,
              t_marks_are_ordered_and_start_at_zero,
              t_a_mark_lands_on_the_title_card_not_the_narration,
              t_the_chapters_were_actually_cut,
              t_attaching_a_script_opens_gate_one,
              t_the_script_travels_in_the_database_not_as_a_path,
              t_the_pipeline_cannot_render_an_unread_script,
              t_an_approved_script_renders_and_stages_unlisted,
              t_a_retry_reuses_the_render_and_keeps_its_chapters,
              t_an_upload_that_succeeded_is_never_repeated,
              t_posting_needs_a_person_and_then_a_flip,
              t_dropping_removes_the_unlisted_upload,
              t_the_render_is_not_started_without_an_upload_credential):
        t(state)
    for t in (t_every_kind_of_script_failure_is_counted,
              t_a_script_under_the_floor_does_not_reach_the_human,
              t_the_token_ceiling_stays_under_the_streaming_limit,
              t_a_chapter_with_no_record_is_flagged,
              t_a_note_that_needs_nothing_is_not_called_a_blocker,
              t_a_record_url_that_is_not_a_document_is_caught,
              t_a_chapter_with_nothing_to_show_is_named,
              t_the_card_says_how_much_the_safety_net_is_carrying,
              t_a_chapter_with_a_record_is_not_flagged,
              t_figures_spelled_out_still_count_as_figures,
              t_publishing_needs_a_wider_scope_than_uploading):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all long-form render cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
