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


# ---------------------------------------------------------------- text + place
# STYLE has said "No text, no lettering, no numbers, no logos" since the look was
# locked, and scene_from_beat adds "no words" — and FLUX renders gibberish anyway.
# Reel #22 closed on a seal ringed with `TELOLE WREILAPREILE OF THE THT ISER
# NLIE.T` and carried a map captioned `BENGALJRU MYSUIRK`. Two measured reasons
# the old approach cannot work:
#
#   1. The endpoint REJECTS negative_prompt — HTTP 422 extra_forbidden. FLUX.1-dev
#      on NIM is guidance-distilled and takes no negative prompt at all, so there
#      is no lever there. (Tested 2026-07-31 against the live endpoint.)
#   2. Diffusion models weight a *positive assertion* far above a negation. Same
#      prompt, same seed: appending "no text" leaves the gibberish; asserting
#      "every surface is blank and unmarked" at the FRONT removes it.
#
# So blankness is stated positively and first, where it carries weight.
_BLANK = ("Every surface in this image is completely blank, smooth and unmarked. "
          "No inscriptions, no engraved words, no printed labels, no signage. ")


def _place_clause(place):
    """Geographic anchor, or "" when the script didn't name a place.

    Reel #22's closing frame — for a Karnataka High Court story — was the UNITED
    STATES CAPITOL. The scene prompt is purely symbolic and names no country, so
    the model reaches for a generic 'government building' and lands on Washington.
    Measured: adding this clause turned that exact prompt into an Indian domed
    court building at the same seed.

    Deliberately NOT defaulted to India. Thelivu is global in scope (run #121 was
    Anthropic, in the US) — a hardcoded 'Set in India' would put Indian
    architecture on a San Francisco story, which is the same class of error in the
    other direction. No place named, no anchor.
    """
    place = (place or "").strip().rstrip(".")
    if not place:
        return ""
    return (f"Set in {place}. Architecture, landscape, clothing and context must "
            f"be {place} only; never substitute American or European landmarks. ")


# Subjects FLUX cannot render responsibly at any prompt, mapped to a symbol that
# carries the same idea. This is NOT about the safety filter (see _ABSTRACT) — it
# is about factual wrongness on a fact-checking brand.
#
# Maps are the proven case: asked for a stamp pressing on a map of the
# Bengaluru-Mysuru corridor, FLUX drew AUSTRALIA; with the India anchor added it
# drew a generic world map. It cannot draw India's outline, and a wrong-country map
# under a Karnataka headline is exactly the credibility failure we are removing.
# Seals/crests are the other: their whole visual grammar is a ring of lettering, so
# they regenerate gibberish even with _BLANK.
# Replacements are stored WITHOUT a leading article — the substitution consumes any
# article in front of the term and re-emits a correct one. Storing "a plain medallion"
# and matching a bare term turned "a state seal" into "a a plain medallion".
_UNRELIABLE = {
    "map of india": "expanse of open farmland seen from above",
    "map of the world": "expanse of open land seen from above",
    "world map": "expanse of open land seen from above",
    "maps": "expanses of open land seen from above",
    "map": "expanse of open land seen from above",
    "official seal": "plain unmarked medallion",
    "state seal": "plain unmarked medallion",
    "seals": "plain unmarked medallions",
    "seal": "plain unmarked medallion",
    "emblem": "plain unmarked medallion",
    "crest": "plain unmarked medallion",
    "coat of arms": "plain unmarked medallion",
    "logo": "plain geometric shape",
    "newspaper headline": "folded sheet of paper",
    "headline": "folded sheet of paper",
    "newspapers": "folded sheets of paper",
    "newspaper": "folded sheet of paper",
    "signboard": "blank board",
    "billboard": "blank board",
}

# Longest match first, one pass — same reason as _ABSTRACT_RE: substituting term by
# term lets a replacement be re-substituted into nonsense. The optional leading
# article is part of the match so it can be reissued with the right a/an.
_UNRELIABLE_LC = {k.lower(): v for k, v in _UNRELIABLE.items()}
_UNRELIABLE_RE = re.compile(
    r"\b(?:(a|an|the)\s+)?("
    + "|".join(re.escape(k) for k in sorted(_UNRELIABLE_LC, key=len, reverse=True))
    + r")\b", re.I)


def _derisk_sub(m):
    article, term = m.group(1), m.group(2)
    repl = _UNRELIABLE_LC[term.lower()]
    if not article:
        # Sentence-initial ("Map of India, seen at dusk") must not lose its capital.
        return repl[0].upper() + repl[1:] if term[0].isupper() else repl
    if article.lower() == "the":
        fixed = article
    else:
        # Agreement follows the REPLACEMENT, not the term it replaced:
        # "a map" -> "an expanse", "an emblem" -> "a plain medallion".
        fixed = "an" if repl[0].lower() in "aeiou" else "a"
        if article[0].isupper():
            fixed = fixed.capitalize()
    return f"{fixed} {repl}"


def _derisk(scene):
    """Swap out the subjects FLUX renders factually wrong or as gibberish."""
    return _UNRELIABLE_RE.sub(_derisk_sub, scene)

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


def generate_beat_images(scenes, out_dir, *, seed=7, progress=None, place=None):
    """Render one illustration per scene. Returns a list of Paths, or None in a
    slot that failed.

    `place` is the story's setting (from the script's PLACE: line). It anchors the
    architecture and landscape so a Karnataka story does not close on the US
    Capitol. Omitted when the script names no place — see `_place_clause`.

    Serial by design: the laptop has 14 GB and FLUX responses are large — holding
    six decoded images in memory at once is how the box starts swapping. Each
    image is written to disk and released.
    """
    import requests
    from pathlib import Path

    from shared.nvidia import call_with_retry

    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        log.warning("NVIDIA_API_KEY not set — no illustrations")
        return [None] * len(scenes)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _try(prompt, img_seed):
        """One generation attempt, transient failures retried. Returns bytes, or None
        if the safety filter refused it or the image came back blank.

        The retry matters more here than anywhere else in the reel: illustrations are
        now 2-3 per long beat rather than one, so a reel makes ~12 FLUX calls instead
        of ~5 — and because a single missing illustration drops the WHOLE reel to text
        slides (all-or-nothing, by design), one transient 500 out of twelve used to
        cost the entire illustrated look. A refusal is NOT retried here: it's handled
        by the caller re-prompting with the scene abstracted, which is the fix that
        actually works on a filter.
        """
        def _once():
            # _BLANK and the place anchor lead: a diffusion model weights the front
            # of the prompt most, and both are assertions the tail-end STYLE string
            # has demonstrably failed to enforce as negations. No negative_prompt —
            # the endpoint 422s on it.
            full = f"{_BLANK}{_place_clause(place)}{prompt} {STYLE}"
            r = requests.post(
                FLUX_URL,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                json={"prompt": full, "width": GEN_W, "height": GEN_H,
                      "steps": 35, "cfg_scale": 3.5, "seed": img_seed},
                timeout=180,
            )
            r.raise_for_status()
            return r.json()

        body = call_with_retry(_once, what=f"FLUX seed={img_seed}")
        art = body["artifacts"][0]
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
        # Per-scene seed. It used to be one fixed seed for every scene, which was
        # harmless while each beat had a distinct prompt — but sub-shots of one beat
        # deliberately reuse a near-identical prompt, and a shared seed would render
        # them as the SAME picture, so the cut would look like a stutter.
        img_seed = seed + i
        try:
            data = _try(_derisk(_soften(scene)), img_seed)
            if data is None:
                # Refused. The subject is the news, so retry with the scene
                # abstracted rather than losing the beat — one filtered beat
                # would otherwise drop the whole reel to text slides.
                log.warning("beat %d: content-filtered — retrying abstracted", i)
                data = _try(_abstract(_derisk(_soften(scene))), img_seed)
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
