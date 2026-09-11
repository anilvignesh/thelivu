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

# From engine/skills/long-form-script/SKILL.md. TARGETS, not limits.
#
# There is deliberately NO hard word ceiling. A cap on length is what the reel
# format already has, and forcing a story to fit it by cutting load-bearing
# material is the exact failure long-form exists to fix — imposing a second
# ceiling one level up would recreate it.
#
# What is real is machine time. Narration synthesises at ~7.2x realtime on the
# reel-worker's single voice server, so a 2,500-word piece occupies it for over
# two hours. That is a SCHEDULING constraint, not a writing one: the question is
# never "is this script too long" but "does its narration fit the window before
# the slot". See fits_window().
LONGFORM_TARGET_MIN = 750
LONGFORM_TARGET_MAX = 1200

# Chatterbox on the reel-worker measured at ~7.2x realtime (2026-09-10): 108
# words of narration took 247s to produce 34.3s of audio. Kept here so the cost
# of a script is knowable before an hour of CPU is spent discovering it.
SYNTH_REALTIME_FACTOR = 7.2
SPOKEN_WORDS_PER_MINUTE = 150

# ALLOWLIST, not a denylist. The previous version counted every line except
# those matching a list of known non-spoken fields, which meant any new field —
# or any continuation line of a multi-line one — silently counted as narration.
# A DESCRIPTION carrying a numbered source list pushed a 1,298-word script to
# 1,661 and over the hard ceiling (2026-09-11). Only lines that ARE narration
# count, and anything unrecognised counts as nothing.
_SPOKEN_LINE = re.compile(
    r"^(HOOK|CLOSE|COLD_OPEN|BEAT\s+\d+|CHAPTER\s+\d+)\s*:\s*(.*)$", re.I)


def spoken_words(script_text):
    """Count only the words a viewer hears.

    CAPTION and IMAGE lines are on-screen or generation instructions, TITLE and
    DESCRIPTION are metadata, and none are read aloud. Counting them would
    inflate every script and could graduate a story that fits the reel format
    fine, or fail one that fits long-form.
    """
    total = 0
    for line in (script_text or "").splitlines():
        m = _SPOKEN_LINE.match(line.strip())
        if m:
            total += len(m.group(2).split())
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
    """Does this material need more than 90 seconds to be explained?

    NOT "reel or long-form". Those are not alternatives, and treating them as
    alternatives was wrong: a topic can have both. Anil, 2026-09-10 — "we are
    not gonna say, the reel is done, no long video." A reel that shipped is a
    reel that fit 225 words; it says nothing about whether the material behind
    it needed more. See also_warrants_longform().

    So a True here means the material exceeds what 90 seconds can carry. The
    reel still gets made if there is a reel in it — this decides whether a long
    video is owed as well.

    Returns (bool, reason). The reason is recorded rather than just the verdict:
    a story taking the long-form slot is an editorial event worth auditing, and
    "it was 240 words" is a better record than "True".
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


def also_warrants_longform(reel_script, additional_material_words=0,
                           ceiling=REEL_HARD_CEILING_WORDS):
    """Does a topic ALREADY covered by a reel still owe a long video?

    A published reel does not close a topic. The reel format's own overflow
    rule — cut a middle beat — means every reel built from dense material threw
    something away to fit, and what it threw away is exactly the qualification,
    the second data point or the counter-case that long-form exists to carry.

    Two ways a topic qualifies:
      * the reel script was over the ceiling before it was cut down, so the
        cutting itself is the evidence; or
      * more material has since been established than 90 seconds can hold —
        a dig that kept going after the reel shipped, an RTI that came back.

    Returns (bool, reason).
    """
    reel_words = spoken_words(reel_script)
    total = reel_words + max(0, additional_material_words)

    if total > ceiling:
        if additional_material_words:
            return True, (
                f"the reel carries {reel_words} words; {additional_material_words} "
                f"further words of established material exist ({total} total). "
                "That does not fit 90 seconds and should not be compressed into it."
            )
        return True, (
            f"the reel script ran to {reel_words} words against a {ceiling} "
            "ceiling — it shipped by cutting, and what was cut is what long-form "
            "carries"
        )
    return False, (
        f"{total} words of material — the reel already holds it; a long video "
        "would be the same story said more slowly"
    )


def parse_script(text):
    """Parse long-form-script output into {title, place, why, chapters, ...}.

    Tolerant by design — the same reasoning as the digger's extractor: a model
    that fences its output or reorders two fields should not cost a script that
    took real money to write.
    """
    out = {
        "title": "", "place": "", "why_long_form": "", "cold_open": "",
        "cold_open_image": "", "open_loop": "", "close": "", "close_image": "",
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
        "open_loop": r"^OPEN_LOOP:\s*(.+)$",
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

    # The cold open and the close are units like any other and were the only
    # ones that could hold exactly one frame. The close of the NH script runs 46
    # seconds — a frame held that long is the "audio book" failure by itself, on
    # the two units a viewer is most likely to judge the video by. So they take
    # the same repeatable vocabulary as a chapter.
    for bookend in ("cold_open", "close"):
        out[f"{bookend}_figures"] = []
        out[f"{bookend}_images"] = []
        for line in text.splitlines():
            m = re.match(rf"^\s*{bookend}_FIGURE\s*:\s*(.+)$", line, re.I)
            if m:
                bits = [b.strip() for b in m.group(1).split("|")]
                if bits and bits[0]:
                    out[f"{bookend}_figures"].append({
                        "value": bits[0],
                        "label": bits[1] if len(bits) > 1 else "",
                        "source": bits[2] if len(bits) > 2 else ""})
                continue
            m = re.match(rf"^\s*{bookend}_IMAGE(?:\s+\d+)?\s*:\s*(.+)$", line, re.I)
            if m:
                out[f"{bookend}_images"].append(m.group(1).strip())
        # The singular field stays, so anything already reading it keeps working.
        if out[f"{bookend}_images"] and not out.get(f"{bookend}_image"):
            out[f"{bookend}_image"] = out[f"{bookend}_images"][0]

    chapters = {}
    for line in text.splitlines():
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+TITLE\s*:\s*(.+)$", line, re.I)
        if m:
            chapters.setdefault(int(m.group(1)), {})["title"] = m.group(2).strip()
            continue
        # "CHAPTER 2 IMAGE 3:" as well as "CHAPTER 2 IMAGE:" — long-form runs
        # 2-3 images per chapter, because one per chapter leaves each on screen
        # for ~58s against a reel's ~15s.
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+IMAGE(?:\s+(\d+))?\s*:\s*(.+)$", line, re.I)
        if m:
            ch = chapters.setdefault(int(m.group(1)), {})
            ch.setdefault("images", []).append(m.group(3).strip())
            ch["image"] = ch["images"][0]
            continue
        # "CHAPTER 3 FIGURE: 2,732 crore | imposed in penalties, 2022-25 | LS Q843"
        #
        # The number goes on screen as TYPE, drawn by us, not as a generated
        # picture. Anil, 2026-09-11, after watching the first sample: "generated
        # images like these won't work... we need to print out numbers, facts,
        # screenshots, evidences."
        #
        # Explicit rather than scraped out of the narration on purpose. A figure
        # lifted from prose by a regex is a figure nobody checked, rendered at
        # 200pt in the middle of the screen — the single worst place in the whole
        # system to be wrong. The writer states it, and it is reviewable at gate 1
        # against the source named in the same line.
        # "CHAPTER 5 CLIP: <what it shows> | <url or local path> | <licence> | <when and where>"
        #
        # Real footage. Anil, 2026-09-11: "what is the possibility of stitching
        # in short videos also into the video... if a video of the nh actually
        # breaking up".
        #
        # The LICENCE FIELD IS REQUIRED and the renderer refuses a clip without
        # one. Stitching video is the easy half; the half that ends the channel
        # is a clip pulled off social media with no licence (a Content ID claim
        # or a strike) and no guarantee it is the right road on the right day.
        # See BRAND.md — licence and verification are separate requirements and
        # both are mandatory, because a correctly licensed clip of the wrong
        # flyover is still a false claim.
        # "CHAPTER 3 PHOTO: <what it shows> | <url> | <licence, author> | <when>"
        #
        # A real photograph, from a repository that publishes a licence as
        # structured data (publishing/photos.py — Wikimedia Commons). Same four
        # fields and the same licence rules as CLIP, because it is the same
        # question: what it shows, where it came from, under what permission,
        # and when.
        #
        # The first field is the one no API can supply. Searching "Indian
        # highway construction" on Commons returns, correctly licensed, 1900s
        # photographs of the Wind River Indian Reservation in Wyoming. The
        # machine establishes what is PERMITTED; a person establishes what is
        # TRUE, at gate 1.
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+PHOTO\s*:\s*(.+)$", line, re.I)
        if m:
            bits = [b.strip() for b in m.group(2).split("|")]
            if len(bits) >= 2:
                chapters.setdefault(int(m.group(1)), {}).setdefault("photos", []).append({
                    "shows": bits[0],
                    "src": bits[1],
                    "licence": bits[2] if len(bits) > 2 else "",
                    "provenance": bits[3] if len(bits) > 3 else "",
                })
            continue
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+CLIP\s*:\s*(.+)$", line, re.I)
        if m:
            bits = [b.strip() for b in m.group(2).split("|")]
            if len(bits) >= 2:
                chapters.setdefault(int(m.group(1)), {}).setdefault("clips", []).append({
                    "shows": bits[0],
                    "src": bits[1],
                    "licence": bits[2] if len(bits) > 2 else "",
                    "provenance": bits[3] if len(bits) > 3 else "",
                })
            continue
        # "CHAPTER 3 TABLE: <title> | <source> | Arunachal = 87% | ... | *Kerala = 22%"
        #
        # A rank is not a number. "Kerala is 23rd of 26" told as a single figure
        # asks the viewer to take it on trust; the same claim as a short ranked
        # list with one row lit up is something they can check with their eyes
        # in four seconds. Anil, 2026-09-11: "there should be things valid on
        # the screen, its a video at the end of the day."
        #
        # A row prefixed `*` is the highlighted one. A row that is just `...` is
        # an elision — say so on screen rather than implying the list is whole.
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+TABLE\s*:\s*(.+)$", line, re.I)
        if m:
            bits = [b.strip() for b in m.group(2).split("|")]
            if len(bits) >= 3:
                chapters.setdefault(int(m.group(1)), {}).setdefault("tables", []).append({
                    "title": bits[0],
                    "source": bits[1],
                    "rows": [{"text": r.lstrip("*").strip(),
                              "highlight": r.startswith("*"),
                              "elision": r.strip() == "..."}
                             for r in bits[2:] if r],
                })
            continue
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+FIGURE\s*:\s*(.+)$", line, re.I)
        if m:
            bits = [b.strip() for b in m.group(2).split("|")]
            if bits and bits[0]:
                chapters.setdefault(int(m.group(1)), {}).setdefault("figures", []).append({
                    "value": bits[0],
                    "label": bits[1] if len(bits) > 1 else "",
                    "source": bits[2] if len(bits) > 2 else "",
                })
            continue
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s+RECORD\s*:\s*(.+)$", line, re.I)
        if m:
            # "description | url | phrase the page must contain"
            bits = [b.strip() for b in m.group(2).split("|")]
            chapters.setdefault(int(m.group(1)), {}).setdefault("records", []).append({
                "description": bits[0] if bits else "",
                "url": bits[1] if len(bits) > 1 else "",
                "quote": bits[2] if len(bits) > 2 else "",
            })
            continue
        m = re.match(r"^\s*CHAPTER\s+(\d+)\s*:\s*(.+)$", line, re.I)
        if m:
            chapters.setdefault(int(m.group(1)), {})["text"] = m.group(2).strip()

    out["chapters"] = [
        {"n": n, "title": c.get("title", f"Chapter {n}"),
         "text": c.get("text", ""), "image": c.get("image", ""),
         "images": c.get("images", []), "records": c.get("records", []),
         "figures": c.get("figures", []), "tables": c.get("tables", []),
         "clips": c.get("clips", []), "photos": c.get("photos", [])}
        for n, c in sorted(chapters.items()) if c.get("text")
    ]
    out["word_count"] = spoken_words(text)
    return out


def request_longform(run_id, why="", by="owner"):
    """Put a story into the long-form queue by hand. Returns (ok, message).

    The other door, and until 2026-09-11 the only one was
    `make_reel.queue_longform()` — fired when a reel is STILL over the seconds
    ceiling after a shorter rewrite. That condition is narrow by design and, in
    production, has never once been true: `longform_queue` was empty the whole
    time this pipeline existed.

    Which makes it the wrong and only trigger. Anil, 2026-09-11: "if we find
    something substantial which needs a long video we do that" — the signal is
    editorial judgement about the material, and a reel that happened to fit 90
    seconds says nothing about whether the material behind it did. He had a
    candidate for the first long video and no way to say so.

    So: a person names a run. Everything downstream is unchanged — the script is
    written automatically, and both human gates still stand.
    """
    from shared.db import get_run, queue_longform, longform_item, longform_queue

    run = get_run(run_id)
    if not run:
        return False, f"run #{run_id} not found"
    if (run.get("draft_text") or "").strip() == "":
        return False, (f"run #{run_id} has no draft text — long-form is written "
                       f"from the verified article, so there is nothing to work from")

    existing = [r for r in (longform_queue(status=QUEUED)
                            + longform_queue(status=SCRIPTED)
                            + longform_queue(status=SCRIPT_OK)
                            + longform_queue(status=RENDERED))
                if r.get("run_id") == run_id]
    if existing:
        e = existing[0]
        return False, (f"run #{run_id} is already long-form #{e['id']} "
                       f"({e.get('status')})")

    queue_longform(run_id=run_id,
                   title=(run.get("throughline") or f"run #{run_id}")[:200],
                   reason=(why or "requested by hand — editorial judgement that "
                                  "the material needs more than 90 seconds"),
                   reel_seconds=None)
    row = [r for r in longform_queue(status=QUEUED) if r.get("run_id") == run_id]
    qid = row[0]["id"] if row else None
    return True, (f"run #{run_id} queued as long-form #{qid}. The script is "
                  f"written on the next engine tick and comes back here to read.")


def build_description(parsed):
    """The YouTube description: the writer's blurb, then EVERY source used.

    Anil, 2026-09-11: "always make sure to leave the sources in the video
    description for the youtube long videos."

    Derived from the frames rather than trusted to the writer. Every FIGURE,
    TABLE and RECORD line carries the source it came from, because that source
    is printed on screen beside the number — so the description is assembled
    from the same fields, deduplicated, in the order they appear. A hand-written
    source list drifts the moment a chapter is edited; this one cannot, and a
    source that reaches the screen with no citation would have failed at the
    parser long before it reached here.

    RECORD lines contribute their URL, which is the strongest kind: a viewer who
    doubts the video can open the document itself.
    """
    parts = [(parsed.get("description") or "").strip()]

    # The same document is cited two ways: a FIGURE line says "Lok Sabha
    # Unstarred Question 843, 23 July 2026" and the RECORD line for the page on
    # screen says "...answered 23 July 2026" with the URL. Exact-string dedup
    # keeps both and the list reads as padded.
    #
    # So identity is the DISTINCTIVE NUMBERS — a question number, a PIB release
    # id, a year — taken from the text and its URL together. Two citations whose
    # numbers are the same document are the same document, whatever words wrap
    # them. Numbers rather than fuzzy text matching because a citation's numbers
    # are the part nobody paraphrases.
    def _ident(text, url=""):
        # Years are excluded: nearly every citation carries one, so counting
        # them as identity merged "Ministry reply reported August 2026" into
        # "Government figures, as reported 2026" — two different sources whose
        # only common number was the year. A question number or a release id
        # identifies a document; a year identifies nothing.
        nums = re.findall(r"\d{3,}", f"{text} {url}")
        return frozenset(n for n in nums if not (len(n) == 4 and 1900 <= int(n) <= 2099))

    seen_text, idents, sources = set(), [], []

    def add(text, url=""):
        text = (text or "").strip()
        if not text or text.lower() in seen_text:
            return
        mine = _ident(text, url)
        if mine and any(mine <= prior or prior <= mine for prior in idents):
            return
        seen_text.add(text.lower())
        if mine:
            idents.append(mine)
        sources.append(f"{text} — {url}" if url else text)

    # RECORDs first: they carry the URL, which is the citation a viewer can
    # actually open, so when two forms collapse into one the URL-bearing form
    # is the one that should survive.
    for c in parsed.get("chapters", []):
        for r in c.get("records") or []:
            add(r.get("description"), r.get("url", ""))
    for c in parsed.get("chapters", []):
        for f in c.get("figures") or []:
            add(f.get("source"))
        for t in c.get("tables") or []:
            add(t.get("source"))

    if sources:
        parts.append("Sources")
        parts += [f"{i}. {src}" for i, src in enumerate(sources, 1)]
        parts.append("Every figure on screen carries its source in the frame. "
                     "If something here is wrong, tell us and we will correct it "
                     "on the record.")
    return "\n\n".join(p for p in parts if p).strip()


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


# The reel-worker sits idle overnight (load 0.00 for 28 days when measured), so
# this is the window long-form narration can have without competing with the
# daily reel builds.
OVERNIGHT_HOURS = 8


def fits_window(word_count, hours=OVERNIGHT_HOURS):
    """(fits, message) — does this script's narration fit an idle window?

    The only length question worth asking. A script is never "too long"; its
    narration either fits the machine time available before the slot or it does
    not, and if it does not the answer is to start earlier or split it across
    two nights — not to cut the story.
    """
    _, synth = synthesis_estimate(word_count)
    budget = hours * 3600
    if synth <= budget:
        return True, f"{synth/60:.0f} min of narration fits a {hours}h window"
    return False, (
        f"{synth/60:.0f} min of narration exceeds a {hours}h window. This is a "
        "scheduling problem, not a length problem: start the render a night "
        "earlier, or split the narration. Do not cut the story to fit the box.")


def budget_check(parsed_or_words):
    """(ok, message). Length is advisory; only machine time can actually fail."""
    words = (parsed_or_words if isinstance(parsed_or_words, int)
             else parsed_or_words.get("word_count", 0))
    audio, synth = synthesis_estimate(words)
    human = f"{words} words ≈ {audio/60:.1f} min audio ≈ {synth/60:.0f} min to synthesise"
    fits, why = fits_window(words)
    if not fits:
        return False, f"{human} — {why}"
    if words < LONGFORM_TARGET_MIN:
        return True, (f"{human}. Under the usual range; if it fits a reel, it "
                      "should have been one.")
    if words > LONGFORM_TARGET_MAX:
        return True, (f"{human}. Longer than usual, which is fine if every "
                      "chapter still changes what the viewer believes.")
    return True, human


# ---------------------------------------------------------------------------
# The pipeline, and where a human stands in it
#
# Anil, 2026-09-11: "all research, digging, validation should run automated,
# once a script or report is reviewed and validated, we create the long videos
# once that is reviewed we post it."
#
# So the trigger is APPROVAL, not a calendar. Long-form is occasional by design
# — it happens when something substantial turns up, not every Saturday.
#
#   queued          the reel pipeline said this outgrew 90 seconds
#   scripted        a long-form script exists and cleared the evidence bar
#   -- GATE 1: a human reads the script ------------------------------------
#   script_ok       approved; this is what releases the render
#   rendered        an MP4 exists
#   -- GATE 2: a human watches the video -----------------------------------
#   posted          published to YouTube
#   dropped         rejected at either gate, with a reason
#
# Two gates rather than one because they fail differently. A script can be
# wrong about a fact, which no amount of watching the video will reveal — you
# have to read it against the record. A video can be right and still unwatchable.
# Collapsing them into one "approve" would let a factual error through on the
# strength of the pictures looking fine.
#
# Rendering sits BETWEEN the gates on purpose: narration costs about an hour of
# the reel-worker's only voice server, and spending that on a script nobody has
# read yet is how the box ends up busy with something that gets thrown away.

QUEUED = "queued"
SCRIPTED = "scripted"
SCRIPT_OK = "script_ok"
RENDERED = "rendered"
POSTED = "posted"
DROPPED = "dropped"

# Which transitions are legal. Anything else is a bug, and a state machine that
# silently accepts an illegal move is how a video reaches YouTube without
# passing a gate.
TRANSITIONS = {
    QUEUED:    {SCRIPTED, DROPPED},
    SCRIPTED:  {SCRIPT_OK, DROPPED},
    SCRIPT_OK: {RENDERED, DROPPED},
    RENDERED:  {POSTED, DROPPED},
    POSTED:    set(),
    DROPPED:   set(),
}

# The states a human must move it out of. Nothing automated may advance these.
HUMAN_GATES = {SCRIPTED, RENDERED}


def can_advance(current, nxt):
    """(ok, why_not) for a proposed state change."""
    if current not in TRANSITIONS:
        return False, f"unknown state {current!r}"
    if nxt not in TRANSITIONS[current]:
        return False, (f"{current} -> {nxt} is not a legal move; "
                       f"allowed: {sorted(TRANSITIONS[current]) or 'none (terminal)'}")
    return True, ""


def requires_human(current):
    """Is this state waiting on a person?"""
    return current in HUMAN_GATES


def advance(queue_id, current, nxt, by="system"):
    """Move an item, refusing illegal moves and machine-made gate decisions."""
    ok, why = can_advance(current, nxt)
    if not ok:
        raise ValueError(why)
    if requires_human(current) and by == "system":
        raise PermissionError(
            f"{current} is a human gate — {nxt} needs a person, not the pipeline. "
            "Rendering an unread script wastes an hour of the voice server; "
            "posting an unwatched video is worse.")
    from shared.db import set_longform_status
    set_longform_status(queue_id, nxt)
    return nxt


# ---------------------------------------------------------------------------
# Weekly cadence — at most one, Saturday morning
#
# "At most" is doing the work in that sentence. A weekly slot that must be
# filled will eventually publish something that did not clear the evidence bar,
# because the alternative is an empty slot — and that is precisely the pressure
# shared/evidence.py exists to remove. Skipping a week is a normal outcome
# here, not a failure state, and the code says so rather than leaving it to
# whoever is looking at the queue on a Friday night.
#
# The point of a week is that a story has time to become provable. If it has
# not, the honest thing is to let it keep digging and take the following slot.
# ---------------------------------------------------------------------------

PUBLISH_WEEKDAY = 5          # Saturday (Monday=0)
PUBLISH_HOUR = 8             # local morning
REVIEW_BUFFER_HOURS = 12     # a human should be able to read it before it ships
RENDER_OVERHEAD_MIN = 25     # illustration + assembly, on top of narration


def next_slot(now):
    """The next Saturday-morning publication slot at or after `now`."""
    from datetime import datetime, timedelta
    target = now.replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
    days = (PUBLISH_WEEKDAY - target.weekday()) % 7
    target = target + timedelta(days=days)
    if target <= now:
        target = target + timedelta(days=7)
    return target


def build_deadline(slot, word_count):
    """When rendering must START to make a slot.

    Narration is the dominant cost and it is not small: at ~7.2x realtime a
    1,200-word script is about an hour of the reel-worker's only voice server.
    Working backwards from the slot — rather than starting on Friday and hoping
    — is what keeps long-form from colliding with the daily reel builds.
    """
    from datetime import timedelta
    _, synth_seconds = synthesis_estimate(word_count)
    lead = timedelta(seconds=synth_seconds) + timedelta(minutes=RENDER_OVERHEAD_MIN) \
        + timedelta(hours=REVIEW_BUFFER_HOURS)
    return slot - lead


def queued_candidates():
    """Stories the reel pipeline said outgrew the format.

    Written by make_reel at the moment the reel's own overflow rule runs out,
    so the queue is the reel format reporting on itself rather than a second
    judgement. Each still has to clear the evidence bar before it can take a
    slot — outgrowing a reel makes a story ELIGIBLE for long-form, not ready.
    """
    try:
        from shared.db import longform_queue
        rows = longform_queue(status="queued")
    except Exception:
        return []
    return [{
        "id": r["id"],
        "run_id": r.get("run_id"),
        "title": r.get("title") or f"run #{r.get('run_id')}",
        "reason": r.get("reason") or "",
        "queued_since": str(r.get("queued_at") or ""),
        "reel_seconds": r.get("reel_seconds"),
        "claims": [],      # filled by whoever assembles the script
        "word_count": 0,
    } for r in rows]


def slot_decision(candidates, now, assess=None):
    """Choose what fills the next slot, or decide to skip it.

    `candidates` are dicts with at least {title, claims, word_count}. `assess`
    defaults to shared.evidence.assess so the publication gate and the
    investigation rule are the same rule.

    Returns (chosen_or_None, reason). A skip always carries why, because
    "nothing published this week" should be auditable rather than inferred from
    silence.
    """
    if assess is None:
        from shared.evidence import assess as _assess
        assess = _assess

    slot = next_slot(now)
    if not candidates:
        return None, f"skip {slot.date()}: nothing in the queue"

    ready, blocked = [], []
    for c in candidates:
        ok, blockers = assess(c.get("claims", []))
        (ready if ok else blocked).append((c, blockers))

    if not ready:
        detail = "; ".join(
            f"{c['title'][:40]} ({len(b)} unmet)" for c, b in blocked[:3])
        return None, (f"skip {slot.date()}: {len(blocked)} candidate(s), none clearing "
                      f"the evidence bar — {detail}. They keep digging and take a "
                      "later slot; publishing one early is the failure this "
                      "cadence exists to avoid.")

    # Among stories that clear, prefer the one that has been waiting longest —
    # a piece that has held up for two weeks of digging is more certain, not
    # more stale.
    chosen = sorted(ready, key=lambda cb: cb[0].get("queued_since", ""))[0][0]
    deadline = build_deadline(slot, chosen.get("word_count", 0))
    return chosen, (f"publish {slot.date()}: {chosen['title'][:60]} — "
                    f"rendering must start by {deadline:%Y-%m-%d %H:%M}")


# ---------------------------------------------------------------------------
# Review surfaces
#
# Both gates reach Anil the same way the reel pipeline already does — a
# Telegram card with buttons, and a row the dashboard can list. Reusing that
# shape rather than inventing a surface means there is one place to look for
# "what is waiting on me", not two.
# ---------------------------------------------------------------------------

def notify_script_for_review(queue_id, parsed, blockers=None):
    """GATE 1 card: the script, its trigger, its sources, and what is unproven.

    The blockers matter more than the script here. A reviewer reading 1,300
    words of confident prose will not spontaneously remember that one figure
    came from a newspaper rather than the record — so the card says it, above
    the fold, every time.
    """
    from engine.agents.orchestrator import _notify_card
    words = parsed.get("word_count", 0)
    audio, synth = synthesis_estimate(words)
    chapters = parsed.get("chapters", [])

    lines = [
        f"📝 <b>Long-form script #{queue_id} — ready to read</b>",
        f"<b>{parsed.get('title','(untitled)')}</b>",
        "",
        f"Why long-form: {parsed.get('why_long_form','(not stated)')}",
        f"{words} words · ~{audio/60:.0f} min · ~{synth/60:.0f} min to narrate",
        f"{len(chapters)} chapters:",
    ]
    lines += [f"  {c['n']}. {c['title']}" for c in chapters]
    if parsed.get("open_loop"):
        lines += ["", f"Opens: {parsed['open_loop']}"]
    if blockers:
        lines += ["", "⚠️ <b>Not fully sourced:</b>"]
        lines += [f"  • {b}" for b in blockers[:5]]
    else:
        lines += ["", "✅ Every claim meets its evidence bar."]
    lines += ["", "Approving releases ~an hour of narration. Read it first."]
    _notify_card("📝", f"Long-form script #{queue_id} — ready to read",
                 body="\n".join(lines[1:]),
                 reply_markup={"inline_keyboard": [[
                     {"text": "✅ Script OK — render it",
                      "callback_data": f"lfscript_{queue_id}"},
                     {"text": "✗ Drop", "callback_data": f"lfdrop_{queue_id}"},
                 ]]})


def notify_video_for_review(queue_id, title, video_url, minutes=None):
    """GATE 2 card: the finished video, before anything reaches YouTube."""
    from engine.agents.orchestrator import _notify_card
    dur = f" · ~{minutes:.0f} min" if minutes else ""
    _notify_card("🎬", f"Long-form #{queue_id} rendered",
                 body=(f"<b>{title}</b>{dur}\n\n{video_url}\n\n"
                       "Watch it before posting. This is the only path to YouTube."),
                 reply_markup={"inline_keyboard": [[
                     {"text": "📤 Post to YouTube",
                      "callback_data": f"lfpost_{queue_id}"},
                     {"text": "✗ Drop", "callback_data": f"lfdrop_{queue_id}"},
                 ]]})


def awaiting_review():
    """Everything sitting on a human, for the dashboard's 'waiting on me' view."""
    from shared.db import longform_queue
    out = []
    for state, what in ((SCRIPTED, "read the script"), (RENDERED, "watch the video")):
        for r in longform_queue(status=state):
            out.append({"id": r["id"], "title": r.get("title") or f"run #{r.get('run_id')}",
                        "state": state, "action": what,
                        "since": str(r.get("queued_at") or "")})
    return out
