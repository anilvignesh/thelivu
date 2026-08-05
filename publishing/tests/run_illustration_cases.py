"""Regression cases for what happens when FLUX refuses to illustrate a beat.

    python -m publishing.tests.run_illustration_cases

No API key, no database, no network, no ffmpeg: the endpoint is replaced by a
fake whose safety filter is a word list, so the whole refusal path — the prompt
ladder, the house-ground fallback and the text-slide floor — is exercised
deterministically in under a second. A real render is ~15 minutes and costs real
FLUX calls, which is exactly why this path went untested until reel #27 hit it.

The case that produced this suite: reel #27 (Guatemala 1954) lost its entire
illustrated look because the model declined one shot out of eight, and covert
action is a subject the belief desks will keep choosing. Two properties are
pinned here:

  1. a refused scene is RE-ASKED, not re-rolled — each rung of `prompt_ladder`
     gives up more of the scene's specifics, and the statecraft vocabulary that
     class of story uses is actually in the ladder's reach;
  2. one beat that still cannot be illustrated costs that beat its metaphor and
     nothing else — the reel keeps the illustrated look via the house ground,
     and only a reel with more of them falls back to text slides.

And the boundary that outranks both: none of this touches the story. The ladder
reads the IMAGE scene and nothing else, and rewrites it only in the prompt.
"""
import base64
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageStat

from publishing import illustrate as ill
from publishing.illustrate import (LADDER_RUNGS, RUNG_SEED_STRIDE,
                                   generate_beat_images, prompt_ladder)
from publishing.make_reel import MAX_HOUSE_CARDS, _illustrate
from publishing.reel_illustrated import render_house_ground

# The reel #27 class of scene, in the shape the video-script skill emits them.
GUATEMALA = [
    "Soldiers of the junta march past a banana crate stamped with a company mark.",
    "A CIA officer slides a folder across a desk in a distant office at night.",
    "A radio tower broadcasts propaganda over a sleeping capital.",
    "An overthrown president's empty chair beneath a national map.",
]

# What a NIM-style output filter reacts to, split so the fake can be made stricter.
FLAGGED = {"soldier", "soldiers", "junta", "cia", "coup", "assassination",
           "propaganda", "overthrow", "overthrown", "bombing", "mercenaries"}
FLAGGED_STRICT = FLAGGED | {"figure", "figures", "uniformed", "hired", "detained"}


class FakeFlux:
    """A stand-in for the FLUX endpoint whose safety filter is a word list.

    Refuses the way the real one does — HTTP 200 with a black frame and
    `finishReason=CONTENT_FILTERED` — because that is the shape the code has to
    recognise, and an exception would test a different branch entirely.
    """

    def __init__(self, banned):
        self.banned = {w.lower() for w in banned}
        self.prompts, self.seeds = [], []

    def post(self, url, **kw):
        prompt = kw["json"]["prompt"]
        self.prompts.append(prompt)
        self.seeds.append(kw["json"]["seed"])
        words = {w.strip(".,;:'\"").lower() for w in prompt.split()}
        return _Resp(bool(words & self.banned))


class _Resp:
    def __init__(self, refused):
        # 120 KB of payload clears MIN_IMAGE_BYTES; a refusal returns the tiny
        # black frame the real endpoint sends.
        blob = b"\x00" * (16 if refused else 120_000)
        self._body = {"artifacts": [{
            "finishReason": "CONTENT_FILTERED" if refused else "SUCCESS",
            "base64": base64.b64encode(blob).decode()}]}

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _run_flux(scenes, banned, tmp):
    """generate_beat_images against the fake. Returns (paths, fake)."""
    import requests
    fake = FakeFlux(banned)
    requests.post = fake.post
    ill.os.environ["NVIDIA_API_KEY"] = "test-key-not-a-real-one"
    return generate_beat_images(scenes, tmp, place="Guatemala"), fake


def _check(results, name, got, want, why):
    ok = got == want
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {why}"
          + ("" if ok else f"\n        got {got!r}, want {want!r}"))


def main():
    import requests
    results = []
    real_post = requests.post
    print("prompt ladder:")

    # ---- 1. the ladder is a re-ask, not a re-roll --------------------------
    rungs = prompt_ladder(GUATEMALA[0])
    _check(results, "the ladder has LADDER_RUNGS rungs", len(rungs), LADDER_RUNGS,
           "the per-scene ceiling on FLUX calls is a published constant")
    _check(results, "rung 0 is the scene as written", "junta" in rungs[0].lower(), True,
           "the first attempt must still be the most faithful one")
    _check(results, "rung 1 abstracts the statecraft nouns",
           any(w in rungs[1].lower() for w in ("soldier", "junta")), False,
           "THE reel #27 bug: none of the protest vocabulary touched 'soldiers of "
           "the junta', so the old single retry re-sent the same prompt")
    # Checked on the scene only — the still-life lead in front of it says the word
    # "people" itself, in the sentence that asserts there are none.
    scene_at_2 = rungs[2][len(ill._STILL_LIFE):]
    _check(results, "rung 2 empties the frame of people",
           any(w in scene_at_2.lower() for w in ("figure", "person", "people", "man")),
           False,
           "rung 1's replacements are mostly people, and a depicted person in a "
           "violent context is what an image classifier is looking at")
    _check(results, "rung 2 asserts emptiness rather than forbidding people",
           rungs[2].startswith("This is a still life."), True,
           "the module's own measured lesson (see _BLANK): this model does what a "
           "prompt asserts and ignores what it forbids")

    # ---- 2. the ladder never touches the story -----------------------------
    scene = GUATEMALA[1]
    before = scene
    prompt_ladder(scene)
    _check(results, "the ladder does not mutate its input", scene, before,
           "the scene string is shared with the script; rewriting is prompt-only")
    _check(results, "the ladder is deterministic",
           prompt_ladder(scene) == prompt_ladder(scene), True,
           "same scene, same prompts — a reel rebuild must be reproducible")

    print("\nrefusal path (fake endpoint):")
    with tempfile.TemporaryDirectory(prefix="illcases_") as tmp:
        tmp = Path(tmp)

        # ---- 3. a refusal that rung 1 clears --------------------------------
        paths, fake = _run_flux([GUATEMALA[0]], FLAGGED, tmp / "a")
        _check(results, "a flagged scene is illustrated at rung 1",
               paths[0] is not None, True,
               "one filtered beat used to cost the whole reel its look")
        _check(results, "it cost exactly two calls", len(fake.prompts), 2,
               "rung 0 is still tried first — the faithful prompt is never skipped")
        _check(results, "the re-ask moved the seed",
               fake.seeds[1] - fake.seeds[0], RUNG_SEED_STRIDE,
               "no reason to hand a re-asked question the seed just refused")

        # ---- 4. a refusal that needs rung 2 ---------------------------------
        paths, fake = _run_flux([GUATEMALA[0]], FLAGGED_STRICT, tmp / "b")
        _check(results, "a scene the abstraction cannot save reaches rung 2",
               paths[0] is not None, True,
               "covert-action imagery is the class this desk keeps choosing")
        _check(results, "it cost three calls", len(fake.prompts), 3, "one per rung")

        # ---- 5. an accepted scene costs one call, as before -------------------
        paths, fake = _run_flux(GUATEMALA[2:3], set(), tmp / "c")
        _check(results, "an unflagged scene still costs one call",
               len(fake.prompts), 1,
               "the ladder must not make the ordinary reel more expensive")

        # ---- 6. total refusal still reports the beat as missing ---------------
        paths, fake = _run_flux([GUATEMALA[0]], {"symbolic"}, tmp / "d")
        _check(results, "a scene refused at every rung comes back None",
               paths, [None],
               "the ladder makes a refusal rare, it does not pretend one away")
        _check(results, "and stops at the top of the ladder",
               len(fake.prompts), LADDER_RUNGS, "no unbounded re-asking")

        # ---- 7. one bare beat keeps the look; two do not ----------------------
        print("\nhouse ground vs text-slide floor:")
        beats = [(f"spoken line {i}", f"caption {i}") for i in range(5)]
        fields = {"beats": beats, "images": list(GUATEMALA) + ["a quiet street"],
                  "place": "Guatemala"}
        snapshot = list(beats)

        def _stub(misses):
            def gen(scenes, out_dir, progress=None, place=None):
                out = Path(out_dir)
                out.mkdir(parents=True, exist_ok=True)
                made = []
                for i in range(len(scenes)):
                    if i in misses:
                        made.append(None)
                        continue
                    p = out / f"beat_{i}.png"
                    Image.new("RGB", (8, 8), (20, 17, 12)).save(p)
                    made.append(p)
                return made
            return gen

        real_gen = ill.generate_beat_images
        try:
            ill.generate_beat_images = _stub({2})
            got = _illustrate(fields, tmp / "e", lambda *_a: None)
            _check(results, "one refused beat keeps the illustrated look",
                   got is not None and len(got) == 5, True,
                   "reel #27 lost eight beats of illustration to one refusal")
            _check(results, "and the refused beat gets a house frame, not a gap",
                   got and got[2] and got[2][0].name.startswith("house_"), True,
                   "the substitute is drawn in this look, so the reel stays whole")

            ill.generate_beat_images = _stub({1, 3})
            got = _illustrate(fields, tmp / "f", lambda *_a: None)
            _check(results, f"more than {MAX_HOUSE_CARDS} falls back to text slides",
                   got, None,
                   "past the exception, an inked field stops reading as a beat that "
                   "chose texture — the honest product is the consistent text reel")

            _check(results, "the story text is never touched", fields["beats"],
                   snapshot,
                   "illustration is decoration; the words are the reporting")
        finally:
            ill.generate_beat_images = real_gen

        # ---- 8. the house ground is a designed frame, not a black slug --------
        card = render_house_ground(tmp / "house.png", variant=0)
        img = Image.open(card)
        stat = ImageStat.Stat(img.convert("L"))
        _check(results, "house ground is a full reel frame", img.size, (1080, 1920),
               "it goes through draw_illustrated_frame like any illustration")
        _check(results, "it is ink-dark, in palette", 6 < stat.mean[0] < 60, True,
               f"mean luminance {stat.mean[0]:.1f} — the ground every FLUX frame "
               f"in this style has")
        _check(results, "it has tooth, not a flat fill", stat.stddev[0] > 3, True,
               f"stddev {stat.stddev[0]:.1f} — gradient, disc and grain; a flat "
               f"black rectangle would read as a failed render")
        again = render_house_ground(tmp / "house2.png", variant=0)
        _check(results, "it is deterministic per beat",
               Path(card).read_bytes() == Path(again).read_bytes(), True,
               "the same beat gets the same field on every rebuild")

    requests.post = real_post
    bad = results.count(False)
    print(f"\n{len(results) - bad}/{len(results)} illustration cases pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
