"""Make a long-form (3 to 6 minute, 16:9) story file from a Thelivu article that is already published and verified.

    DATABASE_URL=... ANTHROPIC_API_KEY=... NVIDIA_API_KEY=... python -m publishing.animate.longform_story RUN_ID [--dry-run] [--outline-only]

Same evidence and same fact-check as the 90-second reel (articles.py): the article is cut into passages (a1, a2, ...), every spoken line
cites passages, every declared figure must occur in them, and the claim-verifier reads every line. What differs is the shape:

  1. An OUTLINE call splits the passages into 3 to 5 chapters (title, one-line subtitle, the passages each draws on, which chapter holds the payoff).
  2. Each chapter is written as a small story of its own and must pass the reel's checks with chapter-sized limits (auto.shape_problems(limits=...),
     check_and_fill, verify_claims). A chapter that fails is rewritten with the reasons; a chapter that cannot be fixed fails the whole video.
  3. The chapters are joined behind a spoken title card (the chapter title only) into one story with format "wide", rendered by build_piece with the
     landscape scenes (lib/scenes_wide.js). Say ids are prefixed per chapter so they stay unique; one turn beat is kept (the climax chapter's).

The story lands in ANIMATE_STORIES, `approved` false: a long video goes through the longform gates (script review, then the unlisted upload), never straight out.
"""
import argparse
from pathlib import Path
import json
import re
import sys

from publishing.animate import articles, auto
from publishing.animate.auto import log

PASSAGE_LIMIT = 100                     # a long video draws on much more of the article than a reel does
MIN_CHAPTERS, MAX_CHAPTERS = 3, 5
MIN_CHAPTER_PASSAGES = 6
CHAPTER_LIMITS = dict(words=(100, 210), beats=(5, 8), pics=(1, 2), turns=(0, 1), types=3, first_picture=False, meta=False)
ORD = ["one", "two", "three", "four", "five", "six"]
MOODS = ("grave", "tense", "urgent", "investigative", "cold", "reflective", "neutral", "hopeful")
MAX_TRIES = 5

_OUTLINE_RULES = f"""You plan a {MIN_CHAPTERS}-to-{MAX_CHAPTERS}-chapter explainer video (about four to five minutes) for Thelivu, a fact-checked news desk, from an article that has already been fact-checked.
Use ONLY the PASSAGES given (ids a1, a2, ...). Reply with ONLY one JSON object:
{{"title": "the video's title, plain and factual, at most 80 characters",
  "stamp": "a topic label in capitals, at most 24 characters, never starting with THELIVU",
  "mood": one of {list(MOODS)}  (chosen from the facts: grave = deaths, losses, shutdowns; tense = a pending decision or conflict; investigative = a trail of records; cold = process and paperwork; reflective = a long failure; neutral = a plain explainer; hopeful = a fix or a win),
  "climax": the number (1-based) of the chapter that holds the single biggest fact,
  "summary": "3 to 4 plain sentences describing the video for its description. Allegations are attributed to who alleges them. No motive, no adjectives of judgement.",
  "chapters": [{{"title": "at most 8 words, plain, no digits, no acronyms, states no unproven claim", "sub": "at most 12 words", "passages": ["a1", "a2", ...],
                 "picture": "ONE sentence: a concrete cinematic picture (an object or place, one light source, no people's faces, no text, no numbers, no logos) for this chapter's title card"}}]}}
Rules: the chapters follow the article's own order and together use every passage that matters; each chapter lists at least {MIN_CHAPTER_PASSAGES} passages; a passage may sit in only one chapter;
the first chapter says what happened and who says so; later chapters carry the evidence, the official record, the response of those named (or that there was none), and what is still open.
A claim that the verification report marks Allegation-only stays an allegation in every chapter. The last chapter ends on what is unresolved, never on a verdict."""

_CHAPTER_MODE = """

CHAPTER MODE (these override any conflicting rule above). You write ONLY chapter {n} of {total}, "{title}", from ONLY the passages given below.
- 5 to 8 beats. 110 to 200 spoken words in all (aim for about 150, never below 110), at most 26 words per line, numbers written in words.
- The chapter's title card is added automatically: do not write one. Do not write the source card, the sign-off, a stamp or a caption, and do not leave "stamp" or "caption" in the file.
- One or two picture beats (never next to each other); the first beat may be any scene type. At least 3 scene types.
- {turn_rule}
- Continue the story: these things were ALREADY SAID in earlier chapters, do not repeat them: {said}"""


RECAP_LIMITS = dict(words=(70, 150), beats=(4, 7), pics=(0, 1), turns=(0, 0), types=3, first_picture=False, meta=False)
RECAP_TITLE, RECAP_SUB = "The short version", "The facts that matter most, in one place"
RECAP_PICTURE = "A single lit desk lamp over a stack of folded papers with one red thread across them, dark ink background, no people, no text, no numbers"
_RECAP_MODE = """

RECAP MODE (these override any conflicting rule above). You write the closing chapter, "{title}", of a {total}-chapter video. The viewer should leave remembering the few facts that matter most.
- 4 to 7 beats, 70 to 140 spoken words in all, at most 22 words per line, numbers written in words.
- Pick the FOUR or FIVE most important facts of the whole video, the ones at the heart of the story, most important first. Each is one short plain line that carries its attribution (who alleges it, or what the record shows). Use ONLY facts already said below; add nothing new.
- Show them: one LIST beat whose items are those facts, one spoken line per item (the screen shows each item as it is spoken). The other beats may be a short opening line and a closing line.
- The last beat is what is still unresolved, never a verdict, never a motive. No "in conclusion", no "to sum up".
- The chapter's title card is added automatically: do not write one. Do not write a source card, a sign-off, a stamp or a caption.
- No beat has "turn": true.
- EVERYTHING THE VIDEO ALREADY SAID: {said}"""


def recap_chapter(chapters, o):
    """The closing chapter drawn from what the others cite: its passages are every passage the earlier chapters' beats cite."""
    refs = sorted({i for c in chapters for b in c["beats"] for i in b.get("refs", [])}, key=lambda x: int(x[1:]))
    return {"title": RECAP_TITLE, "sub": RECAP_SUB, "passages": refs, "picture": o.get("closing_picture") or RECAP_PICTURE, "recap": True}


def _passages(a):
    return {f"a{k}": p for k, p in enumerate(a["passages"], 1)}


def _bad_words(text):
    return bool(re.search(r"\d", text)) or [x for x in auto._ACRONYM.findall(text) if x not in auto._SPOKEN_OK]


def outline(a):
    user = (f"HEADLINE: {a['headline']}\n\nPASSAGES:\n" + "\n".join(f"[{k}] {p}" for k, p in _passages(a).items()) +
            f"\n\nVERIFICATION REPORT:\n{a['report'][:3500]}")
    feedback = None
    for n in range(1, MAX_TRIES + 1):
        ask = user + (f"\n\nYour previous outline was rejected: {feedback}. Write the whole outline again." if feedback else "")
        try:
            o = auto._json(auto._ask(_OUTLINE_RULES, ask, max_tokens=3000))
        except ValueError as e:
            feedback = f"not valid JSON ({e})"; continue
        bad = []
        ids = set(_passages(a))
        chs = o.get("chapters") or []
        if not MIN_CHAPTERS <= len(chs) <= MAX_CHAPTERS:
            bad.append(f"{len(chs)} chapters, need {MIN_CHAPTERS}-{MAX_CHAPTERS}")
        seen = set()
        for k, c in enumerate(chs, 1):
            ps = [p for p in c.get("passages", []) if p in ids]
            if len(ps) < MIN_CHAPTER_PASSAGES:
                bad.append(f"chapter {k} has {len(ps)} valid passages, need {MIN_CHAPTER_PASSAGES}")
            if seen & set(ps):
                bad.append(f"chapter {k} reuses passages {sorted(seen & set(ps))}")
            seen |= set(ps); c["passages"] = ps
            if _bad_words(c.get("title", "")):
                bad.append(f"chapter {k} title has digits or acronyms")
            if not (c.get("picture") or "").strip():
                bad.append(f"chapter {k} has no picture")
        if o.get("mood") not in MOODS:
            bad.append(f"mood must be one of {list(MOODS)}")
        if not isinstance(o.get("climax"), int) or not 1 <= o["climax"] <= max(1, len(chs)):
            bad.append("climax must be a chapter number")
        st = o.get("stamp", "")
        if not st or len(st) > auto.STAMP_MAX or st.upper().startswith("THELIVU"):
            bad.append("stamp must be a short topic label that does not repeat the wordmark")
        if len((o.get("title") or "")) > 80 or not (o.get("summary") or "").strip():
            bad.append("title over 80 characters or no summary")
        if not bad:
            return o
        feedback = "; ".join(bad)[:900]
        log.info("outline attempt %s rejected: %s", n, feedback)
    raise RuntimeError("no valid outline: " + (feedback or ""))


def write_chapter(run_id, a, o, k, said, header, prev=None, feedback=None):
    ch = o["chapters"][k - 1]
    ps = _passages(a)
    example = json.loads(auto.EXAMPLE.read_text()); example.pop("approved", None)
    turn_rule = ('Exactly ONE beat has "turn": true: the biggest fact of the whole story is in this chapter.' if k == o["climax"]
                 else 'No beat in this chapter has "turn": true.')
    if ch.get("recap"):
        system = articles._RULES + _RECAP_MODE.format(total=len(o["chapters"]), title=ch["title"], said=" | ".join(said))
    else:
        system = articles._RULES + _CHAPTER_MODE.format(n=k, total=len(o["chapters"]), title=ch["title"], turn_rule=turn_rule,
                                                        said="; ".join(said) if said else "(nothing yet: this is the opening chapter)")
    user = (f"EXAMPLE story file (shape and style only; its facts are about a different story):\n{json.dumps(example, ensure_ascii=False)}\n\n"
            f"HEADLINE: {a['headline']}\nCHAPTER {k}: {ch['title']} ({ch.get('sub', '')})\n\nPASSAGES:\n" + "\n".join(f"[{i}] {ps[i]}" for i in ch["passages"]) +
            f"\n\nVERIFICATION REPORT:\n{a['report'][:3500]}")
    if feedback:
        user += (f"\n\nYOUR PREVIOUS FILE:\n{json.dumps(prev, ensure_ascii=False) if prev else '(none)'}\n\nIt was rejected for ALL of these reasons: {feedback}\n"
                 "Change only what is needed to fix every one of them (delete a statement the passages do not support rather than rephrasing it), and write the whole file again.")
    chap = auto._json(auto._ask(system, user, max_tokens=6000))
    for key in ("stamp", "caption", "doc_sha256", "approved"):
        chap.pop(key, None)
    chap["run_id"] = run_id; chap["passage_limit"] = PASSAGE_LIMIT
    chap["source"] = {"publisher": "Thelivu", "title": a["headline"], "report": "Claims checked against primary sources", "place": "Sources in the description"}
    chap["name"] = f"chapter-{k}"
    return chap


def attempt_chapter(run_id, a, o, k, said, header, rows):
    from publishing.animate.build_piece import check_and_fill
    ch = o["chapters"][k - 1]
    own = [r for r in rows if r["id"] in set(ch["passages"])]
    feedback, prev = None, None
    for n in range(1, MAX_TRIES + 1):
        try:
            chap = write_chapter(run_id, a, o, k, said, header, prev, feedback)
        except ValueError as e:
            feedback = f"your output was not valid JSON ({e}); escape quotes inside strings and write one object"; continue
        problems = []
        try:
            problems += auto.shape_problems(dict(chap, stamp="X", caption="X"), RECAP_LIMITS if ch.get("recap") else CHAPTER_LIMITS)
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"shape check could not run: {type(e).__name__}: {e}")
        outside = sorted({i for b in chap.get("beats", []) for i in b.get("refs", []) if i not in set(ch["passages"])})
        if outside:
            problems.append(f"cites passages {outside} that are not in this chapter")
        try:
            check_and_fill(json.loads(json.dumps(chap)))
        except SystemExit as e:
            problems.append(str(e))
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"{type(e).__name__}: {e}")
        try:
            problems += [f"unsupported: {u}" for u in auto.verify_claims(chap, own, header)]
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"verifier could not run: {type(e).__name__}: {e}")
        if not problems:
            return chap
        feedback, prev = "; ".join(problems)[:1600], chap
        log.info("chapter %s attempt %s rejected: %s", k, n, feedback)
    raise RuntimeError(f"chapter {k} ({ch['title']}): {feedback}")


def add_chapter(beats, k, total, chap, ch, climax):
    """Append chapter k to the beat list: a spoken title card, then its beats with say ids prefixed c{k}_ and one turn beat kept."""
    card = {"type": "chapter", "title": f"chapter {k}", "head": [], "refs": [],
            "say": [{"id": f"c{k}_card", "text": f"{ch['title']}.", "after": 0.8}],
            "data": {"n": k, "of": total, "title": ch["title"], "sub": ch.get("sub", ""), "bg_prompt": ch["picture"], "motion": "push",
                     **({"label": "SUMMARY", "recap": True} if ch.get("recap") else {})}}
    beats.append(card)
    ids = {s["id"] for b in chap["beats"] for s in b["say"]}
    def fix(x):
        if isinstance(x, dict):
            return {kk: (f"c{k}_{v}" if kk == "line" and v in ids else fix(v)) for kk, v in x.items()}
        if isinstance(x, list):
            return [fix(v) for v in x]
        return x
    for b in chap["beats"]:
        for s in b["say"]:
            s["id"] = f"c{k}_{s['id']}"
        b["data"] = fix(b.get("data", {}))
        if k != climax:
            b.pop("turn", None)
        beats.append(b)


def assemble(run_id, a, o, chapters):
    """One story file: for each chapter a spoken title card, then its beats. Say ids are prefixed per chapter, one turn beat is kept."""
    beats, total = [], len(chapters)
    for k, chap in enumerate(chapters, 1):
        add_chapter(beats, k, total, chap, o["chapters"][k - 1], o["climax"])
    name = f"long-{run_id}-{re.sub(r'[^a-z0-9]+', '-', a['headline'].lower())[:28].strip('-')}"
    return {"name": name, "title": o["title"], "format": "wide", "run_id": run_id, "passage_limit": PASSAGE_LIMIT, "stamp": o["stamp"],
            "mood": o["mood"], "caption": o["summary"], "approved": False,
            "source": {"publisher": "Thelivu", "title": a["headline"], "report": "Claims checked against primary sources", "place": "Sources in the description"},
            "beats": beats}


def _describe(a, spoken, prev, bad):
    """Rewrite the description using only what the narration itself says; unsupported statements are cut."""
    system = ("You write the description of a fact-checked news video. Use ONLY facts that appear in the NARRATION below. 3 to 4 plain sentences, "
              "each allegation attributed to who alleges it, no motive, no judgement, no statement that goes beyond the narration. Reply with ONLY the text.")
    user = (f"NARRATION:\n{spoken}\n\nYOUR PREVIOUS DESCRIPTION:\n{prev}\n\nThe fact-checker rejected these statements as unsupported: {'; '.join(bad)[:800]}\n"
            "Rewrite the description without them.")
    return auto._ask(system, user, max_tokens=500).strip()


def author(run_id, outline_only=False):
    a = articles.load(run_id, PASSAGE_LIMIT)
    if len(a["passages"]) < 3 * MIN_CHAPTER_PASSAGES:
        raise RuntimeError(f"article has only {len(a['passages'])} usable passages; a long video needs at least {3 * MIN_CHAPTER_PASSAGES}")
    o = outline(a)
    log.info("outline: %s | %s", o["title"], [c["title"] for c in o["chapters"]])
    if outline_only:
        return o, None
    rows = [dict(id=i, claim=p, excerpt=p) for i, p in _passages(a).items()]
    header = (f"{a['headline']} (a Thelivu article). Its verification report says: {a['report'][:1800]}. "
              "A claim the report marks Allegation-only must be attributed to who alleges it; stating it as plain fact is unsupported")
    chapters, said = [], []
    for k in range(1, len(o["chapters"]) + 1):
        try:
            chap = attempt_chapter(run_id, a, o, k, said, header, rows)
        except RuntimeError as e:                                  # one fresh round: the writer is nondeterministic
            log.info("chapter %s failed (%s), one more round", k, str(e)[:160])
            chap = attempt_chapter(run_id, a, o, k, said, header, rows)
        chapters.append(chap)
        said.append(f"chapter {k} ({o['chapters'][k - 1]['title']}): " + " ".join(s["text"] for b in chap["beats"] for s in b["say"])[:500])
        log.info("chapter %s ok: %s beats", k, len(chap["beats"]))
    o["chapters"].append(recap_chapter(chapters, o))
    recap_said = [" ".join(s["text"] for b in c["beats"] for s in b["say"]) for c in chapters]
    try:
        chapters.append(attempt_chapter(run_id, a, o, len(o["chapters"]), recap_said, header, rows))
    except RuntimeError as e:                                  # one fresh round, then the video goes without a recap rather than not at all
        log.info("recap failed (%s), one more round", str(e)[:160])
        try:
            chapters.append(attempt_chapter(run_id, a, o, len(o["chapters"]), recap_said, header, rows))
        except RuntimeError as e2:
            log.info("recap failed twice (%s): the video has no recap", str(e2)[:160]); o["chapters"].pop()
    story = assemble(run_id, a, o, chapters)
    used = sorted({i for b in story["beats"] for i in b.get("refs", [])})
    spoken = " ".join(x["text"] for b in story["beats"] for x in b["say"])
    for n in range(1, MAX_TRIES + 1):
        bad = auto.verify_claims({"beats": [{"refs": used, "say": []}], "caption": story["caption"]}, rows, header)
        if not bad:
            break
        log.info("description attempt %s rejected: %s", n, "; ".join(bad)[:300])
        story["caption"] = _describe(a, spoken, story["caption"], bad)
    else:
        # The model keeps adding detail the passages do not carry; a plain description with no claims
        # in it is better than a failed video. Chapter titles are labels, not statements.
        log.info("description never passed the check; using the claim-free description")
        titles = "; ".join(f"{i}. {c['title']}" for i, c in enumerate(o["chapters"], 1))
        story["caption"] = (f"{o['title']}. A fact-checked Thelivu report in {len(o['chapters'])} parts: {titles}. "
                            "Allegations are attributed to who makes them, with any response recorded. The full article with its sources is on Thelivu.")
    return o, story


def readable(o, story):
    """The script as the gate-1 reader sees it (publishing/longform.parse_script format): title, description, then each chapter's narration."""
    out = [f"TITLE: {story['title']}", f"DESCRIPTION: {story['caption']}"]
    for k, ch in enumerate(o["chapters"], 1):
        out.append(f"CHAPTER {k} TITLE: {ch['title']}")
        lines = [x["text"] for b in story["beats"] for x in b["say"] if x["id"].startswith(f"c{k}_") and not x["id"].endswith("_card")]
        out.append(f"CHAPTER {k}: " + " ".join(lines))
    return "\n".join(out) + "\n"


def youtube_description(story, slug):
    """The upload description: the summary, the article that carries every source, and the document labels the video itself shows."""
    wheres = []
    for b in story["beats"]:
        w = (b.get("data") or {}).get("where")
        if w and w not in wheres:
            wheres.append(w)
    parts = [story["caption"].strip(), f"Full article with every source: https://thelivu.up.railway.app/a/{slug}"]
    if wheres:
        parts.append("Documents shown in the video:\n" + "\n".join(f"- {w}" for w in wheres))
    return "\n\n".join(parts)


def chapter_marks(piece_dir, story):
    """[(seconds, title)] for YouTube chapters, from the aligned narration: each chapter starts where its spoken title card starts."""
    vj = json.loads((Path(piece_dir) / "voice.json").read_text())
    start = {l["id"]: l["t0"] for l in vj["lines"]}
    marks = []
    for b in story["beats"]:
        if b["type"] == "chapter":
            marks.append([int(start.get(b["say"][0]["id"], 0)), b["data"]["title"]])
    if marks:
        marks[0][0] = 0                                    # YouTube wants the first chapter at 0:00
    return marks


def materialise(story):
    """Pictures and the story file on disk, ready for worker.render. Returns the story.json path."""
    folder = auto.OUT / story["name"]
    (folder / "assets").mkdir(parents=True, exist_ok=True)
    auto.make_image(story, folder)
    import subprocess
    for b in story["beats"]:                                 # a picture the image service never made (daily cap, filter) must not break the build
        d = b.get("data") or {}
        for key in ("image", "bg", "bg2"):
            if d.get(key) and not (folder / "assets" / d[key]).exists():
                if key == "image":                           # the scene needs a file: a plain ink card
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x17140D:s=1920x1080", "-frames:v", "1",
                                    str(folder / "assets" / d[key])], check=True)
                else:
                    d.pop(key)
    (folder / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n")
    return folder / "story.json"


def run(run_id, dry=False, outline_only=False):
    o, story = author(run_id, outline_only)
    if outline_only:
        print(json.dumps(o, indent=2, ensure_ascii=False)); return 0
    words = sum(len(s["text"].split()) for b in story["beats"] for s in b["say"])
    log.info("long-form story %s: %s beats, %s spoken words (about %.1f minutes)", story["name"], len(story["beats"]), words, words / 2.2 / 60)
    if dry:
        print(json.dumps(story, indent=2, ensure_ascii=False)); return 0
    log.info("wrote %s", materialise(story))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("run_id", type=int)
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--outline-only", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a.run_id, a.dry_run, a.outline_only))
