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
    paths = []
    for i, scene in enumerate(scenes):
        if progress:
            try:
                progress(i, len(scenes))
            except Exception:
                pass
        try:
            r = requests.post(
                FLUX_URL,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                json={"prompt": f"{_soften(scene)} {STYLE}",
                      "width": GEN_W, "height": GEN_H,
                      "steps": 35, "cfg_scale": 3.5, "seed": seed},
                timeout=180,
            )
            r.raise_for_status()
            art = r.json()["artifacts"][0]
            # The filter does not error — it returns a black frame with a reason.
            reason = str(art.get("finishReason") or "")
            if "FILTER" in reason.upper():
                log.warning("beat %d: content-filtered (%s) — no image", i, reason)
                paths.append(None)
                continue
            data = base64.b64decode(art["base64"])
            if len(data) < MIN_IMAGE_BYTES:
                log.warning("beat %d: %d-byte image, treating as blank", i, len(data))
                paths.append(None)
                continue
            p = out_dir / f"beat_{i}.png"
            p.write_bytes(data)
            paths.append(p)
        except Exception as e:
            log.warning("beat %d illustration failed: %s", i, e)
            paths.append(None)
    return paths
