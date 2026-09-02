"""Conceptual illustrations for reel beats — FLUX.1-dev on the free NVIDIA key,
with FLUX.1-schnell on Cloudflare Workers AI as a secondary provider.

The lane is **conceptual illustration**: symbolic, non-photoreal, no text and no
recognisable real faces. That is a brand rule, not an aesthetic preference — an
image that could read as photographic evidence of a real event would undermine
the one thing Thelivu sells. Symbols are honest; fake evidence is not.

Local-only by nature: Railway never renders reels (no GPU, no voice server), so
this runs on the laptop as part of the make-reel job. Free — FLUX.1-dev is on
the same NVIDIA key as the Gemma script model.

**Second provider (2026-08-30):** the 2026-08-24 to -29 outage (docs/mistakes.md)
was NVIDIA's hosted endpoint 500ing for 5-6 days straight, not FLUX the model
being bad — so the fix for THAT failure mode is a second, independently-hosted
copy of the same model family, not a different model. Cloudflare Workers AI
serves FLUX.1-schnell (`@cf/black-forest-labs/flux-1-schnell`) free on its
10,000-Neurons/day allowance, on infra that shares nothing with NVIDIA's — when
one is down the other usually isn't. It only fires when the NVIDIA call itself
fails to transport (connection error, exhausted 5xx retries) — a content
refusal still walks `prompt_ladder` against NVIDIA as before, since a second
host of the same weights mostly earns the same refusal. Optional: with no
CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID set, this path is simply skipped and
behaviour is unchanged from before it existed.
"""

import base64
import logging
import os
import re

log = logging.getLogger("illustrate")

FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
CF_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CF_FLUX_URL = ("https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/"
              "@cf/black-forest-labs/flux-1-schnell")
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

# The 'bright' ground-tone experiment (2026-08-19) — a competing entry in
# engine/agents/style_learning.py's AVAILABLE_STYLES, not a replacement for
# STYLE. Anil's question: is the locked dark ground (owner's call 2026-07-26,
# above) costing reach against feeds that reward high-contrast bright
# first-frames? Same composition rules, same "symbolic not literal, no real
# faces" seriousness — only the ground tone changes, so this is a genuine A/B
# on one variable, not a different house style entirely.
STYLE_BRIGHT = (
    "Editorial conceptual illustration, textured screenprint / risograph style, "
    "WARM cream and kraft-paper ground throughout, bold ink-black and deep-red "
    "linework, high contrast, daylight-toned. Flat vector shapes, grainy paper "
    "texture, strong simple symbolic composition, symbolic not literal, serious. "
    "No text, no lettering, no numbers, no logos, no recognisable real faces. "
    "Serious newspaper editorial art, vertical 9:16."
)

# presentation_style value -> which ground prompt it renders with. 'static' is
# the default/fallback for any style not listed here (including 'kinetic',
# once that exists — ground tone and motion are orthogonal, kinetic inherits
# whichever ground its own AVAILABLE_STYLES entry maps to when it's added).
STYLE_BY_PRESENTATION = {
    "bright": STYLE_BRIGHT,
}

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

# How far a ladder rung moves the seed. Bigger than any plausible scene count, so
# rung 1 of scene 0 can never land on rung 0 of scene N and render its picture.
RUNG_SEED_STRIDE = 1000


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
def _article_swapper(mapping):
    """(regex, sub) for an article-aware, longest-match-first, ONE-pass swap.

    Shared by `_derisk` and `_depopulate` because both consume the article in
    front of the term they replace and have to re-emit the right a/an for the
    *replacement*. Written once: the "a a plain medallion" bug is easy to
    reintroduce by hand.
    """
    lc = {k.lower(): v for k, v in mapping.items()}
    rx = re.compile(
        r"\b(?:(a|an|the)\s+)?("
        + "|".join(re.escape(k) for k in sorted(lc, key=len, reverse=True))
        + r")\b", re.I)

    def sub(m):
        article, term = m.group(1), m.group(2)
        repl = lc[term.lower()]
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

    return rx, sub


_UNRELIABLE_RE, _derisk_sub = _article_swapper(_UNRELIABLE)


def _derisk(scene):
    """Swap out the subjects FLUX renders factually wrong or as gibberish."""
    return _UNRELIABLE_RE.sub(_derisk_sub, scene)

# Nouns that carry the news but reliably trip the filter. On a refusal we re-prompt
# with the scene abstracted — the *concept* survives, the flagged object doesn't.
# Journalism stories are full of these, so one filtered beat must not cost the whole
# reel its look. This is rung 1 of `prompt_ladder`.
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
    # ---- statecraft / covert action (added 2026-08-04, from reel #27) ----
    # The belief desks work coups, intelligence services and cold-war history —
    # Guatemala 1954 was the first — and none of the protest vocabulary above
    # touches that language, so rung 1 used to re-send an almost identical prompt
    # and get an identical refusal. These are the words that class of story
    # actually reaches for.
    "coup d'état": "sudden change of government", "coup d'etat": "sudden change of government",
    "coup": "sudden change of government", "junta": "council",
    "regime change": "change of government", "overthrow": "unseating",
    "overthrown": "unseated", "dictator": "ruler", "dictatorship": "one-man rule",
    "covert action": "unseen work", "covert operation": "unseen work",
    "covert": "unseen", "clandestine": "unseen", "espionage": "watching",
    "spy": "watcher", "spies": "watchers",
    "intelligence agency": "distant office", "intelligence service": "distant office",
    "CIA": "distant office", "assassination": "removal", "assassinate": "remove",
    "assassin": "unseen hand", "sabotage": "interference",
    "propaganda": "broadcast messaging", "psychological warfare": "broadcast messaging",
    "soldier": "uniformed figure", "soldiers": "uniformed figures",
    "troops": "uniformed figures", "militia": "group of figures",
    "mercenary": "hired figure", "mercenaries": "hired figures",
    "rebel": "figure", "rebels": "figures", "insurgent": "figure",
    "insurgents": "figures", "guerrilla": "figure", "guerrillas": "figures",
    "invasion": "arrival", "invade": "enter", "airstrike": "aircraft overhead",
    "warplane": "aircraft", "warplanes": "aircraft", "fighter jet": "aircraft",
    "bombing": "falling object", "bombed": "struck", "bomb": "falling object",
    "bombs": "falling objects", "tank": "heavy vehicle", "tanks": "heavy vehicles",
    "torture": "duress", "tortured": "held", "massacre": "great loss",
    "execution": "ending", "prisoner": "detained figure",
    "prisoners": "detained figures",
}


# ONE pass, longest match first — substituting term by term let replacements be
# re-substituted ("pellet"->"small metal shot", then "shot"->"struck") and turned
# prompts into nonsense like "small metal struck guns at young person people".
_ABSTRACT_LC = {k.lower(): v for k, v in _ABSTRACT.items()}
_ABSTRACT_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_ABSTRACT_LC, key=len, reverse=True)) + r")\b",
    re.I)


def _abstract_words(scene):
    """The lexical half of rung 1 — the noun swap with no framing sentence on it.

    Separate from `_abstract` because rung 2 wants the swap but NOT rung 1's
    prefix: prepending one framing sentence to another leaves rung 2 asserting
    emptiness over a sentence that already said "silhouettes only", and the
    depopulation pass then chews the prefix into "no identifiable empty chairs".
    """
    return _ABSTRACT_RE.sub(lambda m: _ABSTRACT_LC[m.group(0).lower()], scene)


def _abstract(scene):
    """Rung 1: strip the newsworthy-but-flaggable nouns, keep the composition."""
    out = _abstract_words(scene)
    # Kept as-is, negations and all, even though `_BLANK` above records that this
    # model weights positive assertions far above negations — this exact wording is
    # what the protest-class reels were tuned on and it does clear the filter for
    # them. The positive-assertion version is rung 2, where there is nothing left
    # to lose by rewriting it.
    return ("A purely symbolic, abstract editorial composition — objects and "
            "silhouettes only, no identifiable people, no violence depicted. "
            + out)


# Rung 2. Rung 1 keeps figures in the frame — most of its replacements ARE people
# ("uniformed figures", "young people", "detained figures") — and a depicted person
# in a violent context is the thing an image classifier is actually looking at. So
# rung 2 empties the frame: every human noun becomes the chair they are not sitting
# in. Empty chairs are a standing editorial-illustration device for absence, so this
# stays inside the house style rather than reading as a dodge.
_DEPOPULATE = {
    "uniformed figures": "empty uniforms on a rack",
    "uniformed figure": "empty uniform on a rack",
    "hired figures": "empty chairs", "hired figure": "empty chair",
    "detained figures": "empty chairs", "detained figure": "empty chair",
    "group of figures": "row of empty chairs",
    "young people": "empty school desks", "young person": "empty school desk",
    "figures": "empty chairs", "figure": "empty chair",
    "silhouettes": "empty chairs", "silhouette": "empty chair",
    "people": "empty chairs", "person": "empty chair",
    "crowds": "empty squares", "crowd": "empty square",
    "watchers": "empty chairs", "watcher": "empty chair",
    "men": "empty chairs", "man": "empty chair",
    "women": "empty chairs", "woman": "empty chair",
    "children": "empty school desks", "child": "empty school desk",
    "bodies": "empty chairs", "body": "empty chair",
}
_DEPOPULATE_RE, _depopulate_sub = _article_swapper(_DEPOPULATE)

# Stated positively and first, for the reason `_BLANK` is: this model does what a
# prompt asserts and mostly ignores what it forbids. "The frame is empty of people"
# is an assertion; "no people" is a negation.
_STILL_LIFE = ("This is a still life. The frame is calm, quiet and completely empty "
               "of people, containing only inanimate objects, architecture, landscape "
               "and simple geometric forms arranged as one symbolic composition. ")


def _still_life(scene):
    """Rung 2: the same idea with nobody in it, asserted rather than forbidden."""
    return _STILL_LIFE + _DEPOPULATE_RE.sub(_depopulate_sub, scene)


def prompt_ladder(scene):
    """The prompts to try for one scene, most faithful first.

    A refusal is not a transient failure, so it is not retried — the same prompt
    at a new seed mostly earns the same refusal. It is *re-asked*: each rung gives
    up a little more of the scene's specifics for a better chance of clearing the
    filter, and the first one that comes back with a real frame wins.

      0. the scene as written, de-risked and softened  — what ships today
      1. + the flaggable nouns abstracted away          — was the whole fallback
      2. + every person removed, emptiness asserted     — the last thing worth trying

    Pure and side-effect free, so the ladder can be asserted without a network or
    an API key. It reads the IMAGE scene only; the story, the narration and the
    captions are not its inputs and never change.
    """
    base = _derisk(_soften(scene))
    return [base, _abstract(base), _still_life(_abstract_words(base))]


LADDER_RUNGS = 3   # len(prompt_ladder(...)); the per-scene ceiling on FLUX calls


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


def generate_beat_images(scenes, out_dir, *, seed=7, progress=None, place=None,
                         ground=STYLE):
    """Render one illustration per scene. Returns a list of Paths, or None in a
    slot that failed.

    Each scene walks `prompt_ladder` until a rung comes back with a real frame, so
    a slot is only None when all three rungs were refused (or the endpoint itself
    failed). A refused scene therefore costs at most `LADDER_RUNGS` calls, and only
    a refused one — an accepted scene still costs exactly one, as before.

    `place` is the story's setting (from the script's PLACE: line). It anchors the
    architecture and landscape so a Karnataka story does not close on the US
    Capitol. Omitted when the script names no place — see `_place_clause`.

    `ground` is the STYLE prompt tail — defaults to the locked dark house style.
    Callers pick STYLE_BRIGHT (or look it up via STYLE_BY_PRESENTATION) to run
    the bright ground-tone experiment; nothing here decides which — that's
    engine/agents/style_learning.py's job.

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

        The retry matters more here than anywhere else in the reel: a missing
        illustration costs the beat its picture and, past one beat, costs the whole
        reel its look — so one transient 500 used to buy the text-slide fallback.
        `call_with_retry` is the ONE retry layer (5xx/timeouts, fails fast on 4xx,
        never touches the paid quota breaker); nothing here adds a second.

        A refusal is NOT a transient failure and is deliberately not retried here.
        The same prompt at a new seed mostly earns the same refusal, so the caller
        walks `prompt_ladder` instead — a different question, not the same one again.
        """
        def _once():
            # _BLANK and the place anchor lead: a diffusion model weights the front
            # of the prompt most, and both are assertions the tail-end STYLE string
            # has demonstrably failed to enforce as negations. No negative_prompt —
            # the endpoint 422s on it.
            full = f"{_BLANK}{_place_clause(place)}{prompt} {ground}"
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

    def _try_cloudflare(prompt, img_seed):
        """Secondary provider, only reached when the NVIDIA transport itself failed
        (see the `except` below) — same model family, independent infra. Cloudflare's
        flux-1-schnell takes no width/height (fixed native size); `draw_illustrated_frame`
        already resizes whatever it gets to 1080x1920, same as it does for FLUX.1-dev's
        768x1344, so this costs a slightly different crop, not a broken frame.

        Returns None (not raise) on any failure — this is already the fallback path,
        so its own failure should read as "no secondary either", not blow up the beat
        loop with a second traceback.
        """
        if not (CF_ACCOUNT_ID and CF_API_TOKEN):
            return None

        def _once():
            full = f"{_BLANK}{_place_clause(place)}{prompt} {ground}"
            # Diagnosed 2026-09-02 (had been failing on EVERY call since this
            # fallback was added, silently, until Anil noticed no illustrated
            # reels were shipping): Cloudflare's REST endpoint rejects `seed`
            # outright — "Additional or unevaluated properties '/seed' at '/'
            # not allowed" (confirmed with a real call, not inferred from
            # docs, which claim seed is supported). No seed control on this
            # provider means retries against it can't target a different
            # image the way NVIDIA's seed bump does; accepted, since this is
            # already the fallback of a fallback.
            r = requests.post(
                CF_FLUX_URL.format(account=CF_ACCOUNT_ID),
                headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
                json={"prompt": full, "steps": 8},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()

        try:
            # Cloudflare's own free tier has the same cold-start/overload shape the
            # NVIDIA retry was written for, but this is the fallback of a fallback —
            # a tight bound keeps a doubly-down day from doubling the render time.
            body = call_with_retry(_once, what=f"Cloudflare FLUX seed={img_seed}",
                                   tries=2, backoff=5)
        except Exception as e:
            log.warning("Cloudflare fallback also failed: %s", e)
            return None
        # REST API wraps the binding's `{image}` shape in `{"result": {...}}`.
        b64 = (body.get("result") or {}).get("image") or body.get("image")
        if not b64:
            return None
        data = base64.b64decode(b64)
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
        #
        # Each rung also moves the seed by RUNG_SEED_STRIDE. The prompt change is the
        # thing that clears a filter, but there is no reason to hand a re-asked
        # question the seed that was just refused. The stride is larger than any
        # plausible scene count so rung 1 of scene 0 can never collide with rung 0 of
        # scene N; rung 0 keeps `seed + i` exactly, so nothing about today's
        # first-attempt output changes.
        for rung, prompt in enumerate(prompt_ladder(scene)):
            img_seed = seed + i + RUNG_SEED_STRIDE * rung
            try:
                data = _try(prompt, img_seed)
            except Exception as e:
                # Transport, not judgment — `call_with_retry` already exhausted the
                # transient case, and a further rung is a different prompt, not a
                # better connection. Stop asking NVIDIA — but try the independently
                # hosted secondary once before giving up on this beat entirely (a
                # no-op when CLOUDFLARE_* isn't configured). This is exactly the
                # 2026-08-24..29 outage's failure shape: NVIDIA's endpoint down for
                # days, not this one prompt refused.
                log.warning("beat %d illustration failed: %s", i, e)
                data = _try_cloudflare(prompt, img_seed)
                if data is not None:
                    log.info("beat %d: illustrated via Cloudflare fallback", i)
                break
            if data is not None:
                if rung:
                    log.info("beat %d: illustrated at ladder rung %d", i, rung)
                break
            log.warning("beat %d: content-filtered at ladder rung %d/%d", i, rung,
                        LADDER_RUNGS - 1)
        if data is None:
            paths.append(None)
            continue
        p = out_dir / f"beat_{i}.png"
        p.write_bytes(data)
        paths.append(p)
    return paths
