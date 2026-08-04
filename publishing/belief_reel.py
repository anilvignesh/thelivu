"""Turn a belief piece's verified SPOKEN SPINE into a reel script.

The news desk writes a reel by handing the finished article to the `video-script`
skill, which compresses it into hook + beats. A belief piece must not go through
that door. Its spine was written by the writer *under the verifier's ruling* and
reviewed as part of the draft — it is already the narration. Re-scripting it
after the human gate would put a generation step downstream of the trust gate,
which is precisely the seam docs/everyone-knows-desk.md §9.5 says not to open.

So the spoken words here are copied, never generated. What still has to be
decided is everything that is NOT words:

  * the on-screen caption for each beat — the big serif line the viewer reads;
  * the illustration scene for each beat;
  * the hashtags.

A caption *is* read, so it is not free either. A model proposes one, and this
module accepts it only if it is a **contiguous span of that spoken line** (≤ 8
words) that keeps the line's negation. It therefore cannot introduce a word the
verifier never saw, and it cannot flip "no astronaut saw it" into "astronauts
saw it" by dropping the "no". When the model is unavailable or its answer fails
that test, a deterministic clause-cut of the same line is used instead — worse
copy, identical guarantee.
"""
import json
import logging
import os
import re

log = logging.getLogger(__name__)

_NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NVIDIA_MODEL = "google/gemma-4-31b-it"

MAX_CAPTION_WORDS = 8

# Dropping one of these from a caption reverses the sentence it came from, which
# a contiguous-span check alone would happily allow ("no man-made object is
# visible" → "man-made object is visible").
_NEGATIONS = {"not", "no", "never", "none", "nothing", "nobody", "cannot",
              "can't", "isn't", "wasn't", "aren't", "weren't", "didn't",
              "doesn't", "don't", "won't", "hasn't", "haven't", "nor",
              "neither", "without", "un", "false", "myth", "wrong"}

SERIES_KICKER = {"ek": "EVERYONE KNOWS", "gk": "TURNS OUT"}


def _words(s):
    """Comparable word tokens: lowercase, stripped of surrounding punctuation.
    Interior punctuation is kept so "can't" stays one token."""
    return [w for w in re.findall(r"[\w'’%-]+", (s or "").lower()) if w]


def _has_negation(tokens):
    return any(t in _NEGATIONS for t in tokens)


def _clauses(line):
    return [c.strip() for c in re.split(r"[,;:—–]| - ", (line or "").strip()) if c.strip()]


def caption_ok(caption, line):
    """Is `caption` a faithful on-screen version of the spoken `line`?

    Faithful means: a contiguous run of the line's own words, no longer than
    MAX_CAPTION_WORDS, and negation-preserving. Deliberately mechanical — the
    point is that no judgement is involved in accepting it.

    Negation is checked against the CLAUSE the caption sits inside, not the
    whole sentence. Dropping the "not" out of the clause you are quoting
    reverses it, and that is the case worth blocking. A negation in a different
    clause is not: "what no one disputes is that cities are easier to see"
    yields the caption "cities are easier to see", which says nothing false and
    is the only usable fragment in the line. Judged per sentence, that caption
    was rejected and the reel fell back to a worse one — measured on run #140.
    """
    cw = _words(caption)
    # Every word of the line, tagged with the clause it belongs to, so the span
    # can be located and its clauses identified in one pass.
    tagged = [(w, i) for i, c in enumerate(_clauses(line)) for w in _words(c)]
    lw = [w for w, _ in tagged]
    if not cw or len(cw) > MAX_CAPTION_WORDS or len(cw) > len(lw):
        return False
    at = next((i for i in range(len(lw) - len(cw) + 1) if lw[i:i + len(cw)] == cw), None)
    if at is None:
        return False   # not a contiguous run of the line's own words
    # Scope = the clause(s) the caption actually covers. A caption may span
    # several (a list of nouns is several clauses to the splitter), and then all
    # of them are in scope; a negation elsewhere in the sentence is not.
    covered = {i for _w, i in tagged[at:at + len(cw)]}
    scope = [w for w, i in tagged if i in covered]
    if _has_negation(scope) and not _has_negation(cw):
        return False
    return True


# Words a caption should not end on — a fragment stopping at "from" or "and"
# reads as a sentence someone forgot to finish.
_DANGLING = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "from",
             "with", "by", "and", "or", "but", "as", "that", "which", "is",
             "was", "were", "are", "be", "been", "its", "it", "their", "his",
             "her", "this", "these", "those"}


def _trim(clause):
    """A clause cut to MAX_CAPTION_WORDS, not left dangling on a function word."""
    words = clause.split()[:MAX_CAPTION_WORDS]
    while len(words) > 2 and _words(words[-1]) and _words(words[-1])[0] in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(",;:—–-")


def clause_caption(line):
    """The deterministic fallback caption: a clause of the line, trimmed.

    Clauses first, because a comma/colon boundary is where a thought ends —
    cutting purely on a word count strands the reader mid-phrase. Clauses are
    tried in order and the first faithful one wins, EXCEPT that a negated line
    skips ahead to the clause carrying the negation: for "from the Moon it is
    impossible: no man-made object is visible", the honest caption is the second
    half, and the first half alone would be a fragment that means nothing on its
    own. Last resort is the whole line, which renders small but true.
    """
    raw = (line or "").strip().rstrip(".!?")
    if not raw:
        return ""
    clauses = [c.strip() for c in re.split(r"[,;:—–]| - ", raw) if c.strip()]
    candidates = [_trim(c) for c in clauses] + [_trim(raw)]
    for cand in candidates:
        if caption_ok(cand, line):
            return cand
    return raw


def _fallback_scene(line):
    """A scene when no model wrote one. `illustrate.scene_from_beat` already does
    this from the caption, so this only needs to exist for the script text."""
    return ""


def dress_spine(lines, *, headline="", series="", place="", timeout=300):
    """Ask the free NVIDIA-hosted model for captions, scenes and hashtags.

    Words are NOT on the table — the prompt shows the model the spoken lines and
    asks it to pick a fragment of each, and `caption_ok` enforces that whatever
    comes back really is one. Returns (captions, scenes, hashtags); on any
    failure returns the deterministic fallback so a reel is still buildable
    without a network.

    The timeout matches the video-script path's 300s for the same measured
    reason: this endpoint is free and slow (42s for a ten-token reply on
    2026-08-04), so a 2-minute ceiling times out on the model rather than on any
    real fault, and the reel silently loses its captions.
    """
    fallback = ([clause_caption(l) for l in lines], ["" for _ in lines], "")
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key or not lines:
        return fallback

    numbered = "\n".join(f"{i + 1}. {l}" for i, l in enumerate(lines))
    system = (
        "You are a pipeline function, not a chat assistant. Return ONLY a JSON "
        "object, no prose, no markdown fences.")
    user = f"""These are the spoken lines of a short vertical video. They are FINAL and
must not be rewritten.

TITLE: {headline}
SERIES: {series}
{f"PLACE: {place}" if place else ""}

LINES:
{numbered}

For each line, give:
- "caption": the words that appear on screen while that line is spoken. It MUST
  be a CONTIGUOUS RUN OF WORDS COPIED FROM THAT LINE, at most {MAX_CAPTION_WORDS}
  words. Do not paraphrase, do not add a word, do not reorder. Choose the
  sharpest part of the line THAT STANDS ON ITS OWN — someone reading only those
  words, with the sound off, should get a statement, not the tail of one.
  "could not see it" is a bad caption; "astronauts could not see it" is a good
  one. If the part you quote is negative ("not", "never", "no"), your caption
  must keep that word.
- "scene": a symbolic editorial illustration for that line — objects, places and
  simple figures, no text, no letters, no logos, no real person's face. One
  sentence.

Also give "hashtags": 3-5 topical hashtags for the video, space separated.

Return exactly:
{{"beats": [{{"caption": "...", "scene": "..."}}, ...], "hashtags": "..."}}"""

    try:
        import requests
        from shared.nvidia import call_with_retry

        def _post():
            r = requests.post(
                _NVIDIA_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={"model": _NVIDIA_MODEL,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}],
                      "temperature": 0.4, "max_tokens": 1400},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()

        raw = call_with_retry(_post, what="belief reel dressing (NVIDIA)")
    except Exception as e:
        log.warning("belief reel dressing failed (%s) — deterministic captions", e)
        return fallback

    raw = raw.replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group(0) if m else raw)
        beats = data.get("beats") or []
    except Exception as e:
        log.warning("belief reel dressing was not JSON (%s) — deterministic captions", e)
        return fallback

    captions, scenes, rejected = [], [], 0
    for i, line in enumerate(lines):
        b = beats[i] if i < len(beats) and isinstance(beats[i], dict) else {}
        cap = (b.get("caption") or "").strip()
        if not caption_ok(cap, line):
            if cap:
                rejected += 1
                log.info("caption rejected (not a faithful span of the line): %r", cap)
            cap = clause_caption(line)
        captions.append(cap)
        scenes.append((b.get("scene") or "").strip())
    if rejected:
        log.warning("%d/%d captions fell back to the clause cut", rejected, len(lines))
    return captions, scenes, (data.get("hashtags") or "").strip()


def script_from_spine(lines, *, headline="", desk="", place="", captions=None,
                      scenes=None, hashtags=""):
    """Render the spine as a `video-script`-format script.

    Emitting the same labelled text the skill emits (rather than building the
    parsed structure directly) means `parse_script` stays the only reader of a
    script, and a belief reel can be hand-corrected in the command centre with
    the same box every other reel uses.
    """
    lines = [l for l in lines if l.strip()]
    if not lines:
        raise ValueError("no spoken lines in the spine")
    captions = captions or [clause_caption(l) for l in lines]
    scenes = scenes or ["" for _ in lines]

    def _cap(i):
        c = (captions[i] if i < len(captions) else "") or clause_caption(lines[i])
        return c
    def _img(i):
        return (scenes[i] if i < len(scenes) else "") or ""

    out = [f"TITLE: {headline or lines[0]}"]
    kicker = SERIES_KICKER.get(desk, "")
    if kicker:
        out.append(f"KICKER: {kicker}")
    if place:
        out.append(f"PLACE: {place}")
    out += ["", f"HOOK: {lines[0]}", f"HOOK_CAPTION: {_cap(0)}"]
    if _img(0):
        out.append(f"HOOK_IMAGE: {_img(0)}")

    middle = lines[1:-1] if len(lines) > 2 else []
    for n, line in enumerate(middle, start=1):
        i = n
        out += ["", f"BEAT {n}: {line}", f"BEAT {n} CAPTION: {_cap(i)}"]
        if _img(i):
            out.append(f"BEAT {n} IMAGE: {_img(i)}")

    if len(lines) > 1:
        i = len(lines) - 1
        out += ["", f"CLOSE: {lines[i]}", f"CLOSE_CAPTION: {_cap(i)}"]
        if _img(i):
            out.append(f"CLOSE_IMAGE: {_img(i)}")

    if hashtags:
        out += ["", f"HASHTAGS: {hashtags}"]
    return "\n".join(out) + "\n"


def spoken_matches_spine(script_text, lines):
    """Do the script's spoken lines still equal the spine, word for word?

    The gate this module exists to protect. Called after parsing, so it catches
    a spine that was mangled on the way through the script format as well as a
    hand-edited script whose words drifted from what was verified. Compares on
    word tokens, so punctuation and case are free but wording is not.
    """
    from publishing.reel import parse_script
    spoken = [sp for sp, _cap in parse_script(script_text)["beats"]]
    return [_words(s) for s in spoken] == [_words(l) for l in lines if l.strip()]
