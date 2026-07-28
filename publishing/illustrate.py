"""Conceptual illustrations for reel beats — FLUX.1-dev on the free NVIDIA key.

The lane is **conceptual illustration**: symbolic, non-photoreal, no text and no
recognisable real faces. That is a brand rule, not an aesthetic preference — an
image that could read as photographic evidence of a real event would undermine
the one thing Thelivu sells. Symbols are honest; fake evidence is not.

Local-only by nature: Railway never renders reels (no GPU, no voice server), so
this runs on the laptop as part of the make-reel job. Free — FLUX.1-dev is on
the same NVIDIA key as the Gemma script model.
"""

import base64
import logging
import os
import re

log = logging.getLogger("illustrate")

FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
# 9:16-ish at a size the endpoint accepts; frames are resized to 1080x1920.
GEN_W, GEN_H = 768, 1344

# The locked house style. Ink-dark grounds (owner's call 2026-07-26) so the whole
# feed reads as one system — earlier prototypes had warm kraft skies with only the
# frame furniture in ink, which broke the grid.
STYLE = (
    "Editorial conceptual illustration, textured screenprint / risograph style, "
    "DARK ink-black and deep charcoal ground throughout, muted kraft-paper and "
    "warm gold accents used sparingly on the dark ground. Flat vector shapes, "
    "grainy paper texture, strong simple symbolic composition, symbolic not "
    "literal, night-toned and serious. No text, no lettering, no numbers, no "
    "logos, no recognisable real faces. Serious newspaper editorial art, "
    "vertical 9:16."
)

# The NIM safety filter returns an all-black frame (finishReason=CONTENT_FILTERED)
# on this vocabulary, which is exactly the vocabulary journalism reaches for. We
# soften the *prompt* — never the story — because the image is decoration and the
# words are the reporting.
_SOFTEN = {
    "somber": "quiet", "sombre": "quiet", "grave": "serious",
    "vulnerable": "exposed", "redaction": "masked", "redacted": "masked",
    "victim": "affected person", "death": "loss", "dead": "still",
    "killed": "lost", "blood": "red", "corpse": "figure",
}

MIN_IMAGE_BYTES = 50_000  # a filtered/blank frame comes back tiny

# Nouns that carry the news but reliably trip the filter. On a refusal we retry
# once with the scene abstracted — the *concept* survives, the flagged object
# doesn't. Journalism stories are full of these, so one filtered beat must not
# cost the whole reel its look.
_ABSTRACT = {
    "police": "uniformed figures", "policeman": "a uniformed figure",
    "officer": "a uniformed figure", "gun": "a device", "pellet": "small metal shot",
    "rifle": "a long object", "weapon": "an implement", "AK-47": "a long object",
    "firing": "discharge", "fired": "discharged", "shot": "struck",
    "baton": "a rod", "lathi": "a rod", "riot": "crowd", "crackdown": "pressure",
    "beaten": "pushed back", "injury": "harm", "injured": "harmed",
    "wound": "mark", "protester": "person", "protesters": "people",
    # Phrases first — longest-match wins, so these beat the single-word entries
    # and avoid "student protesters" becoming "young person people".
    "student protesters": "young people", "student protester": "a young person",
    "pellet gun": "a device", "pellet guns": "devices",
    "student": "young person", "students": "young people", "assault": "confrontation",
    "slap": "raised hand", "slapping": "a raised hand", "arrest": "detention",
}


# ONE pass, longest match first — substituting term by term let replacements be
# re-substituted ("pellet"->"small metal shot", then "shot"->"struck") and turned
# prompts into nonsense like "small metal struck guns at young person people".
_ABSTRACT_LC = {k.lower(): v for k, v in _ABSTRACT.items()}
_ABSTRACT_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_ABSTRACT_LC, key=len, reverse=True)) + r")\b",
    re.I)


def _abstract(scene):
    """Strip the newsworthy-but-flaggable nouns, keep the composition."""
    out = _ABSTRACT_RE.sub(lambda m: _ABSTRACT_LC[m.group(0).lower()], scene)
    return ("A purely symbolic, abstract editorial composition — objects and "
            "silhouettes only, no identifiable people, no violence depicted. "
            + out)


def _soften(text):
    out = text
    for bad, ok in _SOFTEN.items():
        out = out.replace(bad, ok).replace(bad.capitalize(), ok.capitalize())
    return out


def scene_from_beat(caption, spoken=""):
    """Fallback scene when the script gave no IMAGE: line for a beat.

    Deliberately plain — the caption is already the 3-6 word gist, and FLUX does
    better with a concrete noun phrase than with a whole narration sentence.
    """
    seed = (caption or spoken or "").strip().rstrip(".")
    if not seed:
        return "An empty desk with a single document under a lamp."
    return (f"A symbolic editorial illustration representing: {seed}. "
            f"Use objects and simple figures, no words.")


def generate_beat_images(scenes, out_dir, *, seed=7, progress=None):
    """Render one illustration per scene. Returns a list of Paths, or None in a
    slot that failed.

    Serial by design: the laptop has 14 GB and FLUX responses are large — holding
    six decoded images in memory at once is how the box starts swapping. Each
    image is written to disk and released.
    """
    import requests
    from pathlib import Path

    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        log.warning("NVIDIA_API_KEY not set — no illustrations")
        return [None] * len(scenes)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _try(prompt):
        """One generation attempt. Returns bytes, or None if refused/blank."""
        r = requests.post(
            FLUX_URL,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            json={"prompt": f"{prompt} {STYLE}", "width": GEN_W, "height": GEN_H,
                  "steps": 35, "cfg_scale": 3.5, "seed": seed},
            timeout=180,
        )
        r.raise_for_status()
        art = r.json()["artifacts"][0]
        # The filter does not error — it returns a black frame with a reason.
        if "FILTER" in str(art.get("finishReason") or "").upper():
            return None
        data = base64.b64decode(art["base64"])
        return data if len(data) >= MIN_IMAGE_BYTES else None

    paths = []
    for i, scene in enumerate(scenes):
        if progress:
            try:
                progress(i, len(scenes))
            except Exception:
                pass
        data = None
        try:
            data = _try(_soften(scene))
            if data is None:
                # Refused. The subject is the news, so retry with the scene
                # abstracted rather than losing the beat — one filtered beat
                # would otherwise drop the whole reel to text slides.
                log.warning("beat %d: content-filtered — retrying abstracted", i)
                data = _try(_abstract(_soften(scene)))
                if data is None:
                    log.warning("beat %d: still filtered after abstraction", i)
        except Exception as e:
            log.warning("beat %d illustration failed: %s", i, e)
        if data is None:
            paths.append(None)
            continue
        p = out_dir / f"beat_{i}.png"
        p.write_bytes(data)
        paths.append(p)
    return paths
