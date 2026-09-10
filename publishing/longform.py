"""Long-form video: the graduation decision, and parsing the script.

New code sitting BESIDE the reel pipeline. Nothing here modifies `reel.py`,
`reel_illustrated.py`, `make_reel.py` or the `video-script` skill — long-form is
an additional output for the few stories the 90s ceiling would damage, not a
change to how reels are made.

The graduation trigger is deliberately derived from a rule the reel skill already
states, rather than being a new editorial judgement: *"If you are over budget, cut
a middle beat. Never cut the hook, the close, or the attribution that makes a
claim checkable."* A story graduates when obeying that rule would require
breaking it — when the script is still over budget after every middle beat is
gone. That keeps one definition of "too long" in the system instead of two that
can drift apart.
"""

import re

# From engine/skills/video-script/SKILL.md. Mirrored, not imported, because the
# skill file is prose — but if that ceiling ever moves, this must move with it.
REEL_HARD_CEILING_WORDS = 225

# From engine/skills/long-form-script/SKILL.md.
LONGFORM_TARGET_MIN = 750
LONGFORM_TARGET_MAX = 1200
LONGFORM_HARD_CEILING = 1500

# Chatterbox on the reel-worker measured at ~7.2x realtime (2026-09-10): 108
# words of narration took 247s to produce 34.3s of audio. Kept here so the cost
# of a script is knowable before an hour of CPU is spent discovering it.
SYNTH_REALTIME_FACTOR = 7.2
SPOKEN_WORDS_PER_MINUTE = 150

_SPOKEN_PREFIXES = ("HOOK:", "BEAT", "CLOSE:", "COLD_OPEN:", "CHAPTER")
# The character class MUST include digits: the reel format labels these
# "BEAT 1 CAPTION" / "BEAT 1 IMAGE", and a class of [A-Z_ ] silently fails to
# match them. That counted every caption and image line as spoken, inflating a
# six-beat reel by a dozen words and graduating stories that fit the format
# fine — a bug whose only symptom is long-form videos nobody asked for.
_NON_SPOKEN = re.compile(
    r"^(TITLE|PLACE|HASHTAGS|DESCRIPTION|WORD_COUNT|WHY_LONG_FORM"
    r"|[A-Z0-9_ ]*CAPTION|[A-Z0-9_ ]*IMAGE|CHAPTER\s+\d+\s+TITLE)\s*:", re.I
)


def spoken_words(script_text):
    """Count only the words a viewer hears.

    CAPTION and IMAGE lines are on-screen or generation instructions and are not
    read aloud — counting them would inflate every script by roughly a third and
    graduate stories that fit the reel format fine.
    """
    total = 0
    for line in (script_text or "").splitlines():
        line = line.strip()
        if not line or _NON_SPOKEN.match(line):
            continue
        if ":" in line and line.split(":", 1)[0].isupper():
            line = line.split(":", 1)[1]
        total += len(line.split())
    return total


def _beat_lines(script_text):
    """Spoken BEAT lines in order, as (label, text)."""
    out = []
    for line in (script_text or "").splitlines():
        line = line.strip()
        m = re.match(r"^(BEAT\s+\d+)\s*:\s*(.+)$", line, re.I)
        if m:
            out.append((m.group(1).upper(), m.group(2)))
    return out


def words_after_cutting_middle_beats(script_text):
    """What the reel would weigh with every middle beat removed.

    "Middle" means every beat that is not the first or the last: the reel rule
    protects the hook, the close, and attribution, and the first and last beats
    are what carry a story's shape once the hook and close are fixed. If the
    script is STILL over budget after that, the only remaining cuts are the ones
    the rule forbids.
    """
    beats = _beat_lines(script_text)
    if len(beats) <= 2:
        return spoken_words(script_text)
    droppable = {label for label, _ in beats[1:-1]}
    kept = []
    for line in script_text.splitlines():
        m = re.match(r"^\s*(BEAT\s+\d+)\s*(?:CAPTION|IMAGE)?\s*:", line, re.I)
        if m and m.group(1).upper() in droppable:
            continue
        kept.append(line)
    return spoken_words("\n".join(kept))


def should_graduate(script_text, ceiling=REEL_HARD_CEILING_WORDS):
    """Should this story become long-form instead of a reel?

    Returns (bool, reason). The reason is recorded rather than just the verdict:
    a story graduating is an editorial event worth being able to audit later,
    and "it was 240 words" is a much better record than "True".
    """
    total = spoken_words(script_text)
    if total <= ceiling:
        return False, f"fits the reel budget ({total} <= {ceiling} words)"

    after = words_after_cutting_middle_beats(script_text)
    if after <= ceiling:
        return False, (
            f"{total} words, but {after} after cutting middle beats — "
            "the reel rule handles this without losing the hook, close or attribution"
        )
    return True, (
        f"{total} words, still {after} after cutting every middle beat: "
        f"anything further would take the hook, the close, or an attribution"
    )


def parse_script(text):
    """Parse long-form-script output into {title, place, why, chapters, ...}.

    Tolerant by design — the same reasoning as the digger's extractor: a model
    that fences its output or reorders two fields should not cost a script that
    took real money to write.
    """
    out = {
        "title": "", "place": "", "why_long_form": "", "cold_open": "",
        "cold_open_image": "", "close": "", "close_image": "",
        "description": "", "hashtags": [], "chapters": [],
    }
    if not text:
        return out
    text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text.strip())

    simple = {
        "title": r"^TITLE:\s*(.+)$",
        "place": r"^PLACE:\s*(.*)$",
        "why_long_form": r"^WHY_LONG_FORM:\s*(.+)$",
        "cold_open": r"^COLD_OPEN:\s*(.+)$",
        "cold_open_image": r"^COLD_OPEN_IMAGE:\s*(.+)$",
        "close": r"^CLOSE:\s*(.+)$",
        "close_image": r"^CLOSE_IMAGE:\s*(.+)$",
        "description": r"^DESCRIPTION:\s*(.+)$",
    }
    for key, pat in simple.items():
        m = re.search(pat, text, re.I | re.M)
        if m:
            out[key] = m.group(1).strip()

    m = re.search(r"^HASHTAGS:\s*(.+)$", text, re.I | re.M)
    if m:
        out["hashtags"] = [t.lstrip("#") for t in m.group(1).split() if t.strip()]

    chapters = {}
    for line in text.splitlines():
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+TITLE\s*:\s*(.+)$", line, re.I)
        if m:
            chapters.setdefault(int(m.group(1)), {})["title"] = m.group(2).strip()
            continue
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+IMAGE\s*:\s*(.+)$", line, re.I)
        if m:
            chapters.setdefault(int(m.group(1)), {})["image"] = m.group(2).strip()
            continue
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s*:\s*(.+)$", line, re.I)
        if m:
            chapters.setdefault(int(m.group(1)), {})["text"] = m.group(2).strip()

    out["chapters"] = [
        {"n": n, "title": c.get("title", f"Chapter {n}"),
         "text": c.get("text", ""), "image": c.get("image", "")}
        for n, c in sorted(chapters.items()) if c.get("text")
    ]
    out["word_count"] = spoken_words(text)
    return out


def estimate_chapter_timestamps(parsed, wpm=SPOKEN_WORDS_PER_MINUTE):
    """[(seconds, title)] for YouTube chapters, estimated from word counts.

    Estimates only. The renderer should correct these against real audio
    durations before publishing — a chapter mark that drifts is worse than none,
    because a viewer who clicks it lands mid-sentence.
    """
    marks, running = [], 0.0
    open_words = len((parsed.get("cold_open") or "").split())
    marks.append((0, "Introduction"))
    running += open_words / wpm * 60.0
    for ch in parsed.get("chapters", []):
        marks.append((int(running), ch["title"]))
        running += len(ch["text"].split()) / wpm * 60.0
    return marks


def synthesis_estimate(word_count, factor=SYNTH_REALTIME_FACTOR,
                       wpm=SPOKEN_WORDS_PER_MINUTE):
    """(audio_seconds, synthesis_seconds) for a script of this length.

    Long-form narration occupies the reel-worker's single Chatterbox instance
    for its whole duration, so knowing the cost before starting is the
    difference between scheduling a job and discovering one.
    """
    audio = word_count / wpm * 60.0
    return audio, audio * factor


def budget_check(parsed_or_words):
    """(ok, message) against the long-form budget."""
    words = (parsed_or_words if isinstance(parsed_or_words, int)
             else parsed_or_words.get("word_count", 0))
    audio, synth = synthesis_estimate(words)
    human = f"{words} words ≈ {audio/60:.1f} min audio ≈ {synth/60:.0f} min to synthesise"
    if words > LONGFORM_HARD_CEILING:
        return False, (f"over the hard ceiling: {human}. Cut a whole chapter — "
                       "thinning every chapter makes the script read rushed throughout.")
    if words < LONGFORM_TARGET_MIN:
        return True, (f"under target but allowed: {human}. If it fits a reel, "
                      "it should have been one.")
    return True, human
