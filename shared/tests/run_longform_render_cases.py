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
CHAPTER 1 IMAGE 1: A ledger open on a desk.
CHAPTER 1 IMAGE 2: A rubber stamp resting beside an unsigned page.

CHAPTER 2 TITLE: The money
CHAPTER 2: Two thousand seven hundred and thirty-two crore rupees was imposed in penalties over three years, and seven hundred and eighty crore of it was recovered. The rest is still outstanding.
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
    # Three prompts but only 30 seconds: the third would be an eight-second
    # flash, so it is dropped rather than squeezed in.
    check("30s with three images", lfr._shot_count(30.0, 3), 2)
    check("40s with three images", lfr._shot_count(40.0, 3), 3)


def t_the_cap_holds_however_long_the_chapter_runs():
    check("ten minutes, six images", lfr._shot_count(600.0, 6),
          lfr.MAX_SHOTS_PER_UNIT)


# ------------------------------------------------------------------- framing

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

    Both chapters here run ~30s, which buys two 12-second shots and not three —
    so chapter 2's third image goes unused, and that is the intended answer:
    the shot budget comes from the narration, not from how many prompts the
    writer happened to supply.
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
    # SCRIPT carries no RECORD lines at all, so every chapter is flagged.
    check("every recordless chapter flagged",
          sum(1 for f in flags if f.startswith("Chapter")), len(parsed["chapters"]))
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
              t_frames_are_landscape):
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
