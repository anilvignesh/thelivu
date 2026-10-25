"""Find a story worth telling in the corpus, write it as a story file, and prove it before it can render.

    DATABASE_URL=... ANTHROPIC_API_KEY=... NVIDIA_API_KEY=... python -m publishing.animate.auto [--dry-run] [--max N]

Selection follows the charter (impact x under-coverage), applied mechanically to what the corpus can actually tell us:
  * A primary-source audit report, not a state-finances roll-up: the aggregates in those are totals, not acts.
  * At least MIN_FINDINGS grounded findings caused by the state, at least MIN_AMOUNTS of them carrying a rupee figure.
  * Place priority Kerala, then the rest of India (impact within a place: findings with a stated amount, each capped so
    one aggregate cannot outrank a report full of specific acts).
  * Not already told: one story per document.
  * Under-coverage is NOT measured here. CAG state audits are primary documents that the press rarely walks through, which is the
    working assumption; it is a selection signal, never a credibility one (CHARTER section 3). A later check against news
    search can veto a pick.
Hard topic exclusions in CHARTER section 3 cannot match a state audit report, so none is needed here.

Authoring (the writing model, CLAUDE_MODEL) then three proofs. Any failure rejects the document and nothing is written as approved:
  1. build_piece's grounding gate: every declared figure/date is in the cited findings, every excerpt is copied from the DB.
  2. A second model pass reads each spoken line against the cited excerpts and lists any claim they do not support.
  3. Shape: spoken words and pace fit the reel, no bare acronyms in speech, a derived figure is labelled derived.
Passing all three sets "approved": true. The reel is still stored `held` for the Telegram Post tap (worker.py).

Stories are written to ANIMATE_STORIES (default ~/animate-stories), outside the repo, and the worker reads both places.
"""
import argparse
import json
import logging
import math
import os
import re
import sys
from pathlib import Path

log = logging.getLogger("animate_auto")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [animate_auto] %(message)s")

OUT = Path(os.environ.get("ANIMATE_STORIES", os.path.expanduser("~/animate-stories")))
EXAMPLE = Path(__file__).parent / "stories" / "gujarat-bocw" / "story.json"
LINE_MAX = 26
MIN_FINDINGS, MIN_AMOUNTS, AMOUNT_CAP_CR = 4, 2, 10_000
MAX_FINDINGS_SHOWN = 14
WORDS_MIN, WORDS_MAX = 95, 170      # spoken words in the whole piece; words/second per line
_JUNK = re.compile(r"manual|guide|style|dictionary|recruit|holiday|vacanc|state financ|finance accounts|appropriation", re.I)
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
_SPOKEN_OK = {"I", "II", "III", "IV", "V"}


MAX_PASSES_PER_DAY = 3   # each pass can spend ~20 model calls; a failing writer must not burn a day's budget
MAX_TRIES = 3          # a document the writer cannot ground in this many authoring runs is left alone


def _tries(v):
    m = re.match(r"rejected:(\d+)", str(v))
    return int(m.group(1)) if m else 1


def _db():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _kv(key, val=None):
    from shared.db import kv_get, kv_set
    if val is None:
        return kv_get(key)
    kv_set(key, val)


def candidates(limit=5):
    """Documents that qualify, best first. Pure SQL over grounded rows."""
    conn = _db(); cur = conn.cursor()
    cur.execute("""
        select d.sha256, d.title, f.source_key, count(*) n,
               count(f.amount_cr) filter (where f.amount_cr > 0) na,
               coalesce(sum(least(f.amount_cr, %s)), 0) amt
        from findings f join documents d on d.sha256 = f.doc_sha256
        where f.cause = 'state' and f.excerpt is not null and f.excerpt <> ''
        group by d.sha256, d.title, f.source_key""", (AMOUNT_CAP_CR,))
    rows = cur.fetchall()
    cur.execute("select key, value from kv_store where key like 'animate_doc_%%'")
    done = {k for k, v in cur.fetchall() if not str(v).startswith("rejected") or _tries(v) >= MAX_TRIES}
    conn.close()
    out = []
    for sha, title, src, n, na, amt in rows:
        if _JUNK.search(title or "") or n < MIN_FINDINGS or na < MIN_AMOUNTS:
            continue
        if f"animate_doc_{sha}" in done:
            continue
        place = 2 if src == "cag-kerala" else 1
        out.append((place, math.log10(1 + float(amt)) + 0.1 * n, sha, title, src))
    out.sort(reverse=True)
    return out[:limit]


def findings_for(sha):
    conn = _db(); cur = conn.cursor()
    cur.execute("""select id, claim, excerpt, amount_cr, category from findings
                   where doc_sha256 = %s and cause = 'state' and excerpt is not null and excerpt <> ''
                   order by coalesce(least(amount_cr, %s), 0) desc, id limit %s""", (sha, AMOUNT_CAP_CR, MAX_FINDINGS_SHOWN))
    rows = [dict(id=r[0], claim=re.sub(r"\s+", " ", r[1] or ""), excerpt=re.sub(r"\s+", " ", r[2] or ""),
                 amount_cr=float(r[3]) if r[3] is not None else None, category=r[4]) for r in cur.fetchall()]
    conn.close()
    return rows


_RULES = """You write a 55-65 second explainer video as a STORY FILE (JSON), for Thelivu, a fact-checked news desk.
Use ONLY the findings given. Each has an id, a claim and a verbatim excerpt from the audit report. Nothing else is known.

Rules, all enforced by code after you write:
- 6 to 8 beats, then nothing else (a source card and a sign-off are added automatically). Beat types: illustration (the first beat only),
  timeline, excerpt, compare, figure, share, list. Use at least 4 different types. Exactly one beat has "turn": true (the biggest fact).
- THE SCREEN MUST CHANGE WITH EVERY FACT. The viewer sees each fact as it is spoken. So: a beat has ONE spoken line, except compare (two lines,
  one per bar), timeline (one line per event, events >= lines) and list (items >= lines, each item cued on its own words). Every number, date, name
  and quantity you say must also be drawn in that beat's data (a figure's value, a share's value, a compare bar, a timeline event, a list item, a
  marked excerpt phrase). Never say a fact the screen does not show. Never leave the same picture up while a new fact is spoken: give it a new beat.
- Scene guide: figure = one count or rupee amount (data: value, prefix, suffix, decimals, label, cue). share = one percentage of a whole
  (data: value 0-100, decimals, label like "of interception cases had no online report", cue). compare = two values of the SAME unit and kind (two rupee amounts, two counts of the same thing, two shares), within 50 times of each other; never years against rupees or a count against an amount. Set data.derived (e.g. "derived: the difference between the two") only when the change between them is itself a stated or plainly computed fact.
  list = 2-4 short items that went wrong. timeline = dated events. excerpt = the report's own sentence, marked phrase 1-2, one line spoken about it.
- "say" lines are spoken aloud by a text-to-speech voice. Write numbers in words ("one lakh fifty-seven thousand", "twenty twenty-two"),
  never digits. Never write an acronym or abbreviation in speech: spell out the body ("the audit", "the state government").
  Plain, flat, factual sentences, in the form "the audit found ...". No adjectives of judgement, no motive, no "scandal".
  Total spoken words 95 to 150 across the whole piece. At most 26 words per line.
- Every figure, date, name and claim must come from the excerpts of the findings you cite in "refs" for that beat. Do not round up,
  infer, combine across years, or add context you were not given. If you compute a number (a difference or percentage), set it in
  data as derived and say "derived" on screen via the derived note; the two inputs must be in the cited excerpts.
- LENGTH: 100 to 165 spoken words in total over 6-8 beats, so about 15-20 words per line and NEVER more than 26. Count them.
- "numbers" holds digit strings only, exactly as printed in the excerpt ("3,16,000", "June 2024", "69.33"), never number words. Words belong only in "say".
- Do not total, add or restate: say a figure only as the excerpt states it. A stated percentage is shown as a share; a count as a figure.
- "numbers": every figure/date string, written exactly as it appears in the cited excerpts, that the beat shows or says.
- excerpt beats: data.excerpt_of is a finding id, data.mark is a list of exact substrings of that excerpt to highlight (1-2, short).
- timeline events: at "YYYY-MM", label short. compare: two values with the same unit, data.fmt "inr" for plain counts. list: 2-4 items, each short.
- illustration beat: data.image is "open.png" and data.prompt is ONE sentence describing a conceptual, non-photoreal, symbolic image with no
  people's faces, no text, no lettering, no numbers, no logos, no real people.
- EVERY beat except the first also has data.bg_prompt: one sentence describing the picture that fills the screen behind that beat, so it must be
  bright, richly coloured, well lit and cinematic, with one clear subject that shows what the beat is about (a place, objects, machinery, documents,
  weather, a landscape; no faces, no text, no numbers, no logos). Each beat's picture is different and fits THIS story, not a generic symbol.
  Add data.bg_prompt2 (a second picture of the same subject changed to match the beat's turn: after, later, emptier, fuller) on the turn beat and
  on one or two others, so the picture itself changes as the facts land.
- data.motion on every beat except the first: how the picture moves, chosen from the content: push (closing in on a subject), pull (opening out to
  show scale), pan_l or pan_r (a place, a journey, a line of things), rise (growth, a climb, a tower), sway (something unsettled or waiting). Vary it.
- head: 1-2 short on-screen headline lines per beat. stamp: "CAG AUDIT · <PLACE IN CAPS>" (at most 26 characters).
- caption: 3-5 plain sentences for the post, written with digits ("258", "2018-19", "₹40 lakh"), not number words, ending "Source: <report>. Sources in bio." Any derived figure is labelled as derived.
- MOOD (picks the background music, so it must fit the story): put "mood" at the top level of the file, one of "grave" (deaths, losses, shutdowns, money gone), "tense" (a deadline, a pending decision, a conflict), "neutral" (process, records, an explainer), "hopeful" (a fix, a recovery, a win). Choose from the facts, not from how dramatic the story sounds.
- Output ONLY the JSON object, same shape as the example. Ids in "say" are short unique slugs. "after" is the pause after the line in seconds (0.5-2.4).
"""


def _client():
    import anthropic
    return anthropic.Anthropic()


def _ask(system, user, max_tokens=4000):
    from shared.config import CLAUDE_MODEL as MODEL
    r = _client().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                  thinking={"type": "disabled"},
                                  messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if b.type == "text")


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model output")
    return json.JSONDecoder(strict=False).raw_decode(text[m.start():])[0]


def author(sha, title, src, rows, feedback=None, prev=None):
    example = json.loads(EXAMPLE.read_text())
    for k in ("approved",):
        example.pop(k, None)
    user = (f"EXAMPLE story file (shape and style only; its facts are about a different report):\n{json.dumps(example, ensure_ascii=False)}\n\n"
            f"REPORT: {title}\nsource_key: {src}\ndoc_sha256: {sha}\n\nFINDINGS:\n" +
            "\n".join(f"[{r['id']}] amount_cr={r['amount_cr']} category={r['category']}\n  claim: {r['claim']}\n  excerpt: {r['excerpt']}" for r in rows))
    if feedback:
        user += (f"\n\nYOUR PREVIOUS FILE:\n{json.dumps(prev, ensure_ascii=False) if prev else '(none)'}\n\nIt was rejected for ALL of these reasons: {feedback}\n"
                 "Change only what is needed to fix every one of them (delete a statement the excerpts do not support rather than rephrasing it), "
                 "and write the whole file again.")
    raw = _ask(_RULES, user, max_tokens=6000)
    if os.environ.get("ANIMATE_DEBUG"):
        print("RAW>>>", raw[:1500], "<<<")
    story = _json(raw)
    story["doc_sha256"] = sha
    story.setdefault("source", {})["title"] = re.sub(r"\s+", " ", title).strip()
    story["source"].setdefault("publisher", "Comptroller and Auditor General of India")
    story.pop("approved", None)
    return story


def spoken(story):
    return [l for b in story["beats"] for l in b.get("say", [])]


def _shown_items(b):
    d, t = b.get("data", {}), b["type"]
    return {"compare": 2, "timeline": len(d.get("events", [])), "list": len(d.get("items", []))}.get(t, 1)


STAMP_MAX = 26
MOTIONS = {"push", "pull", "pan_l", "pan_r", "rise", "sway"}


def shape_problems(story):
    out = []
    stamp = story.get("stamp", "")
    if not stamp or len(stamp) > STAMP_MAX or stamp.upper().startswith("THELIVU"):
        out.append(f"stamp must be a short topic label of at most {STAMP_MAX} characters that does not repeat the wordmark ('THELIVU'); got '{stamp}'")
    for b in story["beats"]:
        d = b.get("data", {})
        if b["type"] == "compare":
            try:
                lo, hi = sorted([float(d["a"]["value"]), float(d["b"]["value"])])
            except (KeyError, TypeError, ValueError):
                out.append("compare beat needs numeric a.value and b.value"); continue
            if lo <= 0 or hi / lo > 50:
                out.append(f"compare beat '{b.get('title')}' sets {d['a']['value']} against {d['b']['value']}: two bars that far apart are not the same kind of quantity; use a figure beat for each instead")
    for b in story["beats"][1:]:
        if b.get("data", {}).get("motion") not in MOTIONS:
            out.append(f"beat '{b.get('title')}' needs data.motion, one of {sorted(MOTIONS)}")
    if not 6 <= len(story["beats"]) <= 8:
        out.append(f"{len(story['beats'])} beats, need 6-8")
    for b in story["beats"]:
        if b["type"] not in ("illustration", "timeline", "excerpt", "compare", "figure", "share", "list"):
            out.append(f"unknown beat type {b['type']}")
        elif len(b.get("say", [])) > _shown_items(b):
            out.append(f"beat '{b.get('title')}' speaks {len(b['say'])} lines but shows {_shown_items(b)} item(s): the screen would stay still while new facts are spoken")
    words = sum(len(l["text"].split()) for l in spoken(story))
    if not WORDS_MIN <= words <= WORDS_MAX:
        out.append(f"{words} spoken words, need {WORDS_MIN}-{WORDS_MAX}")
    for l in spoken(story):
        n = len(l["text"].split())
        if n > LINE_MAX:
            out.append(f"line {l['id']} has {n} words (max {LINE_MAX})")
        if re.search(r"\d", l["text"]):
            out.append(f"line {l['id']} has digits; write numbers as words")
        bad = [a for a in _ACRONYM.findall(l["text"]) if a not in _SPOKEN_OK]
        if bad:
            out.append(f"line {l['id']} has acronyms {bad}")
    if sum(1 for b in story["beats"] if b.get("turn")) != 1:
        out.append("need exactly one turn beat")
    types = {b["type"] for b in story["beats"]}
    if len(types) < 4:
        out.append("use at least 4 scene types")
    if story["beats"][0]["type"] != "illustration" or any(b["type"] == "illustration" for b in story["beats"][1:]):
        out.append("illustration must be the first beat and only there")
    if not (story.get("caption") or "").strip():
        out.append("no caption")
    return out


def verify_claims(story, rows, header=""):
    """Second pass: every spoken statement must follow from the cited excerpts."""
    by_id = {r["id"]: r for r in rows}
    parts = []
    for b in story["beats"]:
        cited = [by_id[i] for i in b.get("refs", []) if i in by_id]
        if b.get("data", {}).get("excerpt_of") in by_id and by_id[b["data"]["excerpt_of"]] not in cited:
            cited.append(by_id[b["data"]["excerpt_of"]])
        if not b.get("say"):
            continue
        parts.append("SPOKEN: " + " ".join(l["text"] for l in b["say"]) + "\nSHOWN: " + json.dumps({k: v for k, v in b.get("data", {}).items() if k not in ("bg_prompt", "prompt", "bg", "image")}, ensure_ascii=False)
                     + "\nEXCERPTS:\n" + "\n".join(f"- {c['excerpt']}" for c in cited))
    allx = {r["id"]: r for b in story["beats"] for r in [by_id.get(i) for i in b.get("refs", [])] if r}
    parts.append("SPOKEN: " + story.get("caption", "") + "\nSHOWN: {}\nEXCERPTS:\n" + "\n".join(f"- {c['excerpt']}" for c in allx.values()))
    sys_p = ("You are a strict fact checker. For each block, list every statement in SPOKEN or SHOWN that the EXCERPTS do not directly support: "
             f"The REPORT line is also known: {header}. A sentence that only names that report, its state or its period is supported. "
             "Flag: a compare beat whose two bars are not the same kind of quantity in the same unit, a number, date, name or place not in the excerpts, any number, date, name or quantity in SPOKEN that is not drawn in SHOWN (the viewer must see every fact as it is spoken), a causal or motive claim, a comparison or total the excerpts do not state "
             "(simple arithmetic on two stated numbers, labelled derived, is allowed), or any wording that says more than the excerpt does. "
             'Reply with ONLY JSON: {"unsupported": ["..."]}. Empty list if everything is supported.')
    res = _json(_ask(sys_p, "\n\n".join(parts), max_tokens=1500))
    return res.get("unsupported", [])


def make_image(story, folder):
    """One generated picture per beat: the opening illustration, then a faint backdrop (data.bg) for every data scene."""
    from publishing.illustrate import generate_beat_images
    jobs = []                                           # (beat, key, prompt, file)
    for k, b in enumerate(story["beats"]):
        d = b["data"]
        if k == 0:
            jobs.append((b, "image", d.pop("prompt", None) or "an empty public office desk under one lamp at night", "open.png"))
        else:
            has_bg = bool(d.get("bg_prompt"))
            if has_bg:
                jobs.append((b, "bg", d.pop("bg_prompt"), f"b{k}.png"))
            if d.get("bg_prompt2") and has_bg:
                jobs.append((b, "bg2", d.pop("bg_prompt2"), f"b{k}b.png"))
    for b in story["beats"][1:]:
        b["data"].pop("bg_prompt", None); b["data"].pop("bg_prompt2", None)
    paths = generate_beat_images([j[2] for j in jobs], folder / "assets", seed=11)
    for (b, key, _, name), p in zip(jobs, paths):
        if not p:
            if key == "image":
                raise RuntimeError("opening illustration failed")
            continue                                    # a missing backdrop only costs that beat its atmosphere
        target = folder / "assets" / name
        if Path(p) != target:
            Path(p).replace(target)
        b["data"][key] = name


def slug(src, title, sha):
    from datetime import date
    place = src.replace("cag-", "")
    return f"{place}-{re.sub(r'[^a-z0-9]+', '-', (title or 'report').lower())[:24].strip('-')}-{sha[:6]}-{date.today():%m%d}"


def attempt(sha, title, src, dry=False):
    rows = findings_for(sha)
    feedback, prev = None, None
    for n in (1, 2, 3, 4):
        try:
            story = author(sha, title, src, rows, feedback, prev)
        except ValueError as e:                                  # unparseable JSON: ask again, say why
            feedback = f"your output was not valid JSON ({e}); escape quotes inside strings and write one object"
            log.info("attempt %s unparseable: %s", n, e)
            continue
        story["name"] = slug(src, title, sha)
        problems = []
        try:
            problems += shape_problems(story)
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"shape check could not run: {type(e).__name__}: {e}")
        try:
            from publishing.animate.build_piece import check_and_fill
            check_and_fill(json.loads(json.dumps(story)))
        except SystemExit as e:
            problems.append(str(e))
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"{type(e).__name__}: {e}")
        try:                                                     # all checks every time, so one retry can fix every class of problem
            problems += [f"unsupported: {u}" for u in verify_claims(story, rows, f"{title} ({src})")]
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"verifier could not run: {type(e).__name__}: {e}")
        if not problems:
            return story
        feedback, prev = "; ".join(problems)[:1600], story
        log.info("%s attempt %s rejected: %s", story["name"], n, feedback)
    raise RuntimeError(feedback or "no valid story produced")


def run(dry=False, max_stories=1):
    from datetime import date
    today = date.today().isoformat()
    if not dry and _kv("animate_auto_last") == today:
        log.info("already authored a story today, nothing to do"); return 0
    if not dry:
        tries = int(_kv(f"animate_auto_tries_{today}") or 0)
        if tries >= MAX_PASSES_PER_DAY:
            log.info("already ran %s authoring passes today without a story, stopping for the day", tries); return 0
        _kv(f"animate_auto_tries_{today}", str(tries + 1))
    made = 0
    for _, score, sha, title, src in candidates():
        if made >= max_stories:
            break
        log.info("candidate %s (%s) score %.2f", title[:60], src, score)
        try:
            story = attempt(sha, title, src)
        except Exception as e:                                   # noqa: BLE001
            _kv(f"animate_doc_{sha}", f"rejected:{_tries(_kv(f'animate_doc_{sha}') or 'rejected:0') + 1}: {str(e)[:200]}")
            log.warning("rejected %s: %s", title[:60], e)
            continue
        if dry:
            print(json.dumps(story, indent=2, ensure_ascii=False)); made += 1; continue
        folder = OUT / story["name"]
        (folder / "assets").mkdir(parents=True, exist_ok=True)
        make_image(story, folder)
        story["approved"] = True
        (folder / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n")
        _kv(f"animate_doc_{sha}", f"authored: {story['name']}"); _kv("animate_auto_last", today)
        log.info("wrote %s", folder / "story.json"); made += 1
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--max", type=int, default=1)
    a = ap.parse_args()
    sys.exit(0 if run(a.dry_run, a.max) >= 0 else 1)
