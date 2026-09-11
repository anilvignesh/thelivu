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
    from publishing.longform_script import mechanical_blockers

    parsed = longform.parse_script(
        "TITLE: t\nCOLD_OPEN: x\nCHAPTER 1 TITLE: A\n"
        "CHAPTER 1: Words words words words words words words words.\n"
        "CHAPTER 1 PHOTO: The NH-66 stretch at Kooriyad | https://x/y.jpg"
        " | CC BY-SA 4.0, someone | 2016-01-31\nCLOSE: y\n")
    flags = mechanical_blockers(parsed)
    confirm = [f for f in flags if "CONFIRM IT SHOWS THIS" in f]
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

    def fake_synth_beats(beats, backend, work_dir, voice=None):
        from pathlib import Path
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for i, (spoken, _cap) in enumerate(beats):
            # Long enough that the two- and three-image chapters really do get
            # cut, short enough that the suite stays under a minute.
            secs = 30.0 if len(spoken.split()) > 15 else 8.0
            wav = work_dir / f"a{i}.wav"
            _silence(wav, secs)
            durations[i] = secs + reel.GAP_SECS
            out.append((wav, secs + reel.GAP_SECS, []))
        return out

    real = reel.synth_beats
    reel.synth_beats = fake_synth_beats
    try:
        parsed = longform.parse_script(SCRIPT)
        out_mp4 = os.path.join(tmp, "out.mp4")
        return longform.parse_script(SCRIPT), lfr.render(
            parsed, out_mp4, work_dir=os.path.join(tmp, "work"),
            illustrate=illustrate), durations
    finally:
        reel.synth_beats = real


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

    Both chapters here run ~30s, which at a 13-second target cadence buys two
    shots each. The budget comes from the narration, not from how many assets
    the writer supplied — a chapter with eight IMAGE lines and twelve seconds of
    speech still gets one frame.
    """
    res = state["res"]
    if not res.get("ok"):
        return
    # cold open (1) + card + 2 + card + 2 + close (1) = 8
    check("shot count", res.get("shots"), 8)


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
    """Point longform_build's lazy `from publishing import youtube` at a fake."""
    import publishing
    real = getattr(publishing, "youtube", None)
    import sys
    sys.modules["publishing.youtube"] = fake
    publishing.youtube = fake
    return real


def lb_restore(lb, real):
    import publishing
    import sys
    if real is not None:
        sys.modules["publishing.youtube"] = real
        publishing.youtube = real


class _stub_voice:
    """Silent narration of known length, so a chain test costs seconds."""
    def __enter__(self):
        from publishing import reel
        self._real = reel.synth_beats

        def fake(beats, backend, work_dir, voice=None):
            from pathlib import Path
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            out = []
            for i, (spoken, _c) in enumerate(beats):
                secs = 30.0 if len(spoken.split()) > 15 else 8.0
                wav = work_dir / f"a{i}.wav"
                _silence(wav, secs)
                out.append((wav, secs + reel.GAP_SECS, []))
            return out

        reel.synth_beats = fake
        return self

    def __exit__(self, *a):
        from publishing import reel
        reel.synth_beats = self._real
        return False


# --------------------------------------------------- the mechanical blockers
#
# These go on the gate-1 card. They are NOT an evidence assessment — a script is
# prose and shared/evidence.py assesses Claim objects — so what they do instead
# is point a reviewer at what reading 1,500 words of confident prose will not
# make them notice.

def t_a_chapter_with_no_record_is_flagged():
    from publishing import longform
    from publishing.longform_script import mechanical_blockers

    parsed = longform.parse_script(SCRIPT)
    flags = mechanical_blockers(parsed)
    # SCRIPT carries no RECORD lines at all, so every chapter is flagged for that.
    check("every recordless chapter flagged",
          sum(1 for f in flags if "cites no record" in f), len(parsed["chapters"]))
    # Chapter 2 states figures and declares no FIGURE line — the specific
    # failure the first rendered sample had. Chapter 1 declares one, so it is
    # flagged for the missing record only.
    unshown = [f for f in flags if "puts none on screen" in f]
    check("the chapter that shows no figure is named",
          [f.startswith("Chapter 2 ") for f in unshown], [True])
    check("the missing WHY_LONG_FORM is flagged",
          any("WHY_LONG_FORM" in f for f in flags), True)


def t_a_chapter_with_a_record_is_not_flagged():
    from publishing import longform
    from publishing.longform_script import mechanical_blockers

    with_record = SCRIPT.replace(
        "CHAPTER 1 IMAGE 1: A ledger open on a desk.",
        "CHAPTER 1 RECORD: MoRTH deficiency register | https://example.gov.in/r | forty\n"
        "CHAPTER 1 IMAGE 1: A ledger open on a desk.")
    flags = mechanical_blockers(longform.parse_script(with_record))
    check("chapter 1 is no longer flagged",
          any(f.startswith("Chapter 1 ") for f in flags), False)
    check("chapter 2 still is",
          any(f.startswith("Chapter 2 ") for f in flags), True)


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


def main():
    if not have_ffmpeg():
        print("ffmpeg not available — skipping long-form render cases")
        return 0

    print("long-form render\n")
    state = {}
    for t in (t_a_short_unit_keeps_one_picture,
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
              t_a_shared_year_is_not_a_shared_source,
              t_a_shot_moves_and_a_very_short_one_does_not,
              t_credit_is_the_condition_on_some_licences_and_not_on_others,
              t_fair_dealing_renders_but_goes_to_a_human,
              t_an_unlicensed_clip_never_reaches_a_frame,
              t_the_caption_carries_all_three_things,
              t_the_filler_is_a_line_of_narration_not_a_generated_scene,
              t_quotes_track_what_is_being_said,
              t_short_connectives_do_not_become_frames,
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
              t_the_pipeline_cannot_render_an_unread_script,
              t_an_approved_script_renders_and_stages_unlisted,
              t_a_retry_reuses_the_render_and_keeps_its_chapters,
              t_an_upload_that_succeeded_is_never_repeated,
              t_posting_needs_a_person_and_then_a_flip,
              t_dropping_removes_the_unlisted_upload):
        t(state)
    for t in (t_a_chapter_with_no_record_is_flagged,
              t_a_chapter_with_a_record_is_not_flagged,
              t_figures_spelled_out_still_count_as_figures):
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
