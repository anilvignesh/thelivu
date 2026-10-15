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
MIN_FINDINGS, MIN_AMOUNTS, AMOUNT_CAP_CR = 4, 2, 10_000
MAX_FINDINGS_SHOWN = 14
WORDS_MIN, WORDS_MAX, WPS_MAX = 95, 150, 3.3      # spoken words in the whole piece; words/second per line
_JUNK = re.compile(r"manual|guide|style|dictionary|recruit|holiday|vacanc|state financ|finance accounts|appropriation", re.I)
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
_SPOKEN_OK = {"I", "II", "III", "IV", "V"}


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
    cur.execute("select key from kv_store where key like 'animate_doc_%%'")
    done = {r[0] for r in cur.fetchall()}
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
- 4 or 5 beats, then nothing else (a source card and a sign-off are added automatically). Beat types: illustration (the first beat only),
  timeline, excerpt, compare, figure, list. Use at least 3 different types. Exactly one beat has "turn": true (the biggest fact).
- "say" lines are spoken aloud by a text-to-speech voice. Write numbers in words ("one lakh fifty-seven thousand", "twenty twenty-two"),
  never digits. Never write an acronym or abbreviation in speech: spell out the body ("the audit", "the state government").
  Plain, flat, factual sentences, in the form "the audit found ...". No adjectives of judgement, no motive, no "scandal".
  Total spoken words 95 to 150 across the whole piece. At most 22 words per line.
- Every figure, date, name and claim must come from the excerpts of the findings you cite in "refs" for that beat. Do not round up,
  infer, combine across years, or add context you were not given. If you compute a number (a difference or percentage), set it in
  data as derived and say "derived" on screen via the derived note; the two inputs must be in the cited excerpts.
- "numbers": every figure/date string, written exactly as it appears in the cited excerpts, that the beat shows or says.
- excerpt beats: data.excerpt_of is a finding id, data.mark is a list of exact substrings of that excerpt to highlight (1-2, short).
- timeline events: at "YYYY-MM", label short. compare: two values with the same unit, data.fmt "inr" for plain counts. list: 2-4 items, each short.
- illustration beat: data.image is "open.png" and data.prompt is ONE sentence describing a conceptual, non-photoreal, symbolic image with no
  people's faces, no text, no lettering, no numbers, no logos, no real people.
- head: 1-2 short on-screen headline lines per beat. stamp: "CAG AUDIT · <PLACE IN CAPS>".
- caption: 3-5 plain sentences for the post, ending "Source: <report>. Sources in bio." Any derived figure is labelled as derived.
- Output ONLY the JSON object, same shape as the example. Ids in "say" are short unique slugs. "after" is the pause after the line in seconds (0.5-2.4).
"""


def _client():
    import anthropic
    return anthropic.Anthropic()


def _ask(system, user, max_tokens=4000):
    from shared.config import CLAUDE_MODEL as MODEL
    r = _client().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if b.type == "text")


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model output")
    return json.loads(m.group(0), strict=False)


def author(sha, title, src, rows, feedback=None):
    example = json.loads(EXAMPLE.read_text())
    for k in ("approved",):
        example.pop(k, None)
    user = (f"EXAMPLE story file (shape and style only; its facts are about a different report):\n{json.dumps(example, ensure_ascii=False)}\n\n"
            f"REPORT: {title}\nsource_key: {src}\ndoc_sha256: {sha}\n\nFINDINGS:\n" +
            "\n".join(f"[{r['id']}] amount_cr={r['amount_cr']} category={r['category']}\n  claim: {r['claim']}\n  excerpt: {r['excerpt']}" for r in rows))
    if feedback:
        user += f"\n\nYour previous attempt was rejected: {feedback}\nFix exactly that and write the whole file again."
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


def shape_problems(story):
    out = []
    words = sum(len(l["text"].split()) for l in spoken(story))
    if not WORDS_MIN <= words <= WORDS_MAX:
        out.append(f"{words} spoken words, need {WORDS_MIN}-{WORDS_MAX}")
    for l in spoken(story):
        n = len(l["text"].split())
        if n > 22:
            out.append(f"line {l['id']} has {n} words (max 22)")
        if re.search(r"\d", l["text"]):
            out.append(f"line {l['id']} has digits; write numbers as words")
        bad = [a for a in _ACRONYM.findall(l["text"]) if a not in _SPOKEN_OK]
        if bad:
            out.append(f"line {l['id']} has acronyms {bad}")
    if sum(1 for b in story["beats"] if b.get("turn")) != 1:
        out.append("need exactly one turn beat")
    types = {b["type"] for b in story["beats"]}
    if len(types) < 3:
        out.append("use at least 3 scene types")
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
        parts.append("SPOKEN: " + " ".join(l["text"] for l in b["say"]) + "\nSHOWN: " + json.dumps(b.get("data", {}), ensure_ascii=False)
                     + "\nEXCERPTS:\n" + "\n".join(f"- {c['excerpt']}" for c in cited))
    sys_p = ("You are a strict fact checker. For each block, list every statement in SPOKEN or SHOWN that the EXCERPTS do not directly support: "
             f"The REPORT line is also known: {header}. A sentence that only names that report, its state or its period is supported. "
             "Flag: a number, date, name or place not in the excerpts, a causal or motive claim, a comparison or total the excerpts do not state "
             "(simple arithmetic on two stated numbers, labelled derived, is allowed), or any wording that says more than the excerpt does. "
             'Reply with ONLY JSON: {"unsupported": ["..."]}. Empty list if everything is supported.')
    res = _json(_ask(sys_p, "\n\n".join(parts), max_tokens=1500))
    return res.get("unsupported", [])


def make_image(story, folder):
    from publishing.illustrate import generate_beat_images
    beat = story["beats"][0]
    prompt = beat["data"].pop("prompt", None) or "an empty public office desk under one lamp at night"
    paths = generate_beat_images([prompt], folder / "assets", seed=11)
    if not paths or not paths[0]:
        raise RuntimeError("illustration failed")
    p = Path(paths[0]); target = folder / "assets" / "open.png"
    if p != target:
        p.replace(target)


def slug(src, title, sha):
    place = src.replace("cag-", "")
    return f"{place}-{re.sub(r'[^a-z0-9]+', '-', (title or 'report').lower())[:28].strip('-')}-{sha[:6]}"


def attempt(sha, title, src, dry=False):
    rows = findings_for(sha)
    feedback = None
    for n in (1, 2, 3):
        try:
            story = author(sha, title, src, rows, feedback)
        except ValueError as e:                                  # unparseable JSON: ask again, say why
            feedback = f"your output was not valid JSON ({e}); escape quotes inside strings and write one object"
            log.info("attempt %s unparseable: %s", n, e)
            continue
        story["name"] = slug(src, title, sha)
        try:
            problems = shape_problems(story)
            if not problems:
                from publishing.animate.build_piece import check_and_fill
                check_and_fill(json.loads(json.dumps(story)))
                problems = [f"unsupported: {u}" for u in verify_claims(story, rows, f"{title} ({src})")]
        except SystemExit as e:
            problems = [str(e)]
        except Exception as e:                                   # noqa: BLE001
            problems = [f"{type(e).__name__}: {e}"]
        if not problems:
            return story
        feedback = "; ".join(problems)[:900]
        log.info("%s attempt %s rejected: %s", story["name"], n, feedback)
    raise RuntimeError(feedback or "no valid story produced")


def run(dry=False, max_stories=1):
    from datetime import date
    today = date.today().isoformat()
    if not dry and _kv("animate_auto_last") == today:
        log.info("already authored a story today, nothing to do"); return 0
    made = 0
    for _, score, sha, title, src in candidates():
        if made >= max_stories:
            break
        log.info("candidate %s (%s) score %.2f", title[:60], src, score)
        try:
            story = attempt(sha, title, src)
        except Exception as e:                                   # noqa: BLE001
            _kv(f"animate_doc_{sha}", f"rejected: {str(e)[:200]}")
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
