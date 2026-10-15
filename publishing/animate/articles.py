"""Make a story file from a Thelivu article that is already published and verified.

    DATABASE_URL=... ANTHROPIC_API_KEY=... NVIDIA_API_KEY=... python -m publishing.animate.articles [--dry-run] [--max N]

The article is the evidence. Its body is cut into passages (ids a1, a2, ...) that play the part audit findings play in auto.py:
the writer cites passages in `refs`, every declared figure must occur in the cited passages, an excerpt beat copies a passage from
the database at build, and the claim-verifier reads every spoken line against them. The article's verification report supplies the
verdict of each claim: a claim that is only an allegation must be spoken as one ("the agency alleges"), never as fact.

A story from here carries `run_id` (the article's pipeline run) instead of `doc_sha256`. The reel is saved against that run, which
also keeps reel_worker's own candidate query from building a second reel for the same article.

Selection: published `news` runs from the last WINDOW_DAYS, not legally flagged, with no reel yet (including ones reel_worker parked after repeated failures). The article desk already judged
impact and under-coverage when it chose the topic (CHARTER section 3), so this picks the newest. Same daily cap, pass cap and
rejection counter as auto.py. Stories land in ANIMATE_STORIES, held for the Telegram Post tap like every animate reel.
"""
import argparse
import json
import logging
import re
import sys

from publishing.animate import auto
from publishing.animate.auto import _kv, _db, _tries, log

WINDOW_DAYS = 30
MIN_PASSAGES = 8
MAX_PASSAGES = 40
PASSAGE_MAX = 380
_ABBR = r"(?:Ltd|Pvt|Rs|No|Dr|Mr|Mrs|Ms|St|Sec|Cr|vs|etc|Inc|Co|Govt|Dept|Hon|Jr|Sr|Mt|U\.S|a\.m|p\.m)"


def _plain(s):
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`>]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def split_article(draft):
    """(headline, passages) from the article markdown. Disclosure line, DRAFT banner and section headings are dropped."""
    headline, paras = "", []
    for block in re.split(r"\n\s*\n", draft or ""):
        block = block.strip()
        if not block or block.startswith("# DRAFT"):
            continue
        if block.startswith("# "):
            headline = headline or _plain(block[2:])
            continue
        if block.startswith("#") or block.startswith("*From Thelivu") or block.startswith("---"):
            continue
        paras.append(_plain(block))
    out = []
    for p in paras:
        sents = []
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z‘“\"'₹])", p):
            if sents and re.search(rf"\b{_ABBR}\.$", sents[-1]):     # "Ltd." / "No." end a name, not a sentence
                sents[-1] += " " + piece
            else:
                sents.append(piece)
        cur = ""
        for s in sents:
            cur = f"{cur} {s}".strip() if cur else s
            if len(cur) >= 60:
                out.append(cur); cur = ""
        if cur:
            if out and len(cur) < 60 and len(out[-1]) + len(cur) < PASSAGE_MAX:
                out[-1] += " " + cur
            else:
                out.append(cur)
    out = [p for p in out if len(p) <= PASSAGE_MAX] or out
    return headline, out[:MAX_PASSAGES]


def load(run_id):
    conn = _db(); cur = conn.cursor()
    cur.execute("select draft_text, verification_report, slug from pipeline_runs where id = %s", (run_id,))
    row = cur.fetchone(); conn.close()
    if not row:
        raise ValueError(f"no run {run_id}")
    headline, passages = split_article(row[0])
    return dict(headline=headline, passages=passages, report=row[1] or "", slug=row[2])


def rows_for(run_id):
    """Evidence rows keyed by passage id, the shape build_piece.check_and_fill and auto.verify_claims read."""
    a = load(run_id)
    return {f"a{k}": {"claim": p, "excerpt": p} for k, p in enumerate(a["passages"], 1)}, a["headline"]


def candidates(limit=5):
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""
        select r.id from pipeline_runs r join publications p on p.run_id = r.id
        where r.status = 'published' and r.desk = 'news' and coalesce(r.legal_flag, false) = false
          and p.published_at > now() - interval '{int(WINDOW_DAYS)} days'
          and not exists (select 1 from reels x where x.run_id = r.id)
        order by r.id desc""")
    ids = [r[0] for r in cur.fetchall()]
    cur.execute("select key, value from kv_store where key like 'animate_run_%%'")
    done = {k for k, v in cur.fetchall() if not str(v).startswith("rejected") or _tries(v) >= auto.MAX_TRIES}
    conn.close()
    return [i for i in ids if f"animate_run_{i}" not in done][:limit]     # includes runs the old reel worker parked: it gave up on them


_RULES = auto._RULES.replace(
    "Use ONLY the findings given. Each has an id, a claim and a verbatim excerpt from the audit report. Nothing else is known.",
    "Use ONLY the PASSAGES given, from a Thelivu article that has already been fact-checked. Each has an id (a1, a2, ...) and its text. "
    "Nothing else is known. Write about the story, not about the article: never say 'the article' or 'Thelivu reports'.\n"
    "VERDICTS: the verification report lists which claims are Verified and which are Allegation-only. A claim that is only an allegation, "
    "or a denial, is spoken and captioned with its source ('the agency alleges', 'the company denies'), never as established fact.") \
    .replace("the form \"the audit found ...\"", "the form \"the agency alleges ...\" / \"records show ...\" (name who says it)") \
    .replace("excerpt beats: data.excerpt_of is a finding id,", "excerpt beats: data.excerpt_of is a passage id (a1, a2, ...),") \
    .replace("stamp: \"CAG AUDIT · <PLACE IN CAPS>\" (at most 26 characters)", "stamp: a topic label in capitals, at most 24 characters, never starting with THELIVU (the wordmark is already on screen)") \
    .replace("ending \"Source: <report>. Sources in bio.\"", "ending \"Sources in bio.\"") \
    .replace("the excerpt", "the passage").replace("excerpts", "passages").replace("findings", "passages")


def author(run_id, a, feedback=None, prev=None):
    example = json.loads(auto.EXAMPLE.read_text())
    example.pop("approved", None)
    user = (f"EXAMPLE story file (shape and style only; its facts are about a different story):\n{json.dumps(example, ensure_ascii=False)}\n\n"
            f"HEADLINE: {a['headline']}\n\nPASSAGES:\n" + "\n".join(f"[a{k}] {p}" for k, p in enumerate(a["passages"], 1)) +
            f"\n\nVERIFICATION REPORT:\n{a['report'][:3500]}")
    if feedback:
        user += (f"\n\nYOUR PREVIOUS FILE:\n{json.dumps(prev, ensure_ascii=False) if prev else '(none)'}\n\nIt was rejected for ALL of these reasons: {feedback}\n"
                 "Change only what is needed to fix every one of them (delete a statement the passages do not support rather than rephrasing it), "
                 "and write the whole file again.")
    story = auto._json(auto._ask(_RULES, user, max_tokens=6000))
    story.pop("doc_sha256", None); story.pop("approved", None)
    story["run_id"] = run_id
    story["source"] = {"publisher": "Thelivu", "title": a["headline"], "report": "Claims checked against primary sources", "place": "Sources in bio"}
    return story


def attempt(run_id):
    a = load(run_id)
    if len(a["passages"]) < MIN_PASSAGES:
        raise RuntimeError(f"article has only {len(a['passages'])} usable passages")
    rows = [dict(id=f"a{k}", claim=p, excerpt=p) for k, p in enumerate(a["passages"], 1)]
    header = (f"{a['headline']} (a Thelivu article). Its verification report says: {a['report'][:1800]}. "
              "A claim the report marks Allegation-only must be attributed to who alleges it; stating it as plain fact is unsupported")
    feedback, prev = None, None
    for n in (1, 2, 3, 4):
        try:
            story = author(run_id, a, feedback, prev)
        except ValueError as e:
            feedback = f"your output was not valid JSON ({e}); escape quotes inside strings and write one object"
            log.info("attempt %s unparseable: %s", n, e)
            continue
        story["name"] = f"article-{run_id}-{re.sub(r'[^a-z0-9]+', '-', a['headline'].lower())[:28].strip('-')}"
        problems = []
        try:
            problems += auto.shape_problems(story)
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"shape check could not run: {type(e).__name__}: {e}")
        try:
            from publishing.animate.build_piece import check_and_fill
            check_and_fill(json.loads(json.dumps(story)))
        except SystemExit as e:
            problems.append(str(e))
        except Exception as e:                                   # noqa: BLE001
            problems.append(f"{type(e).__name__}: {e}")
        try:
            problems += [f"unsupported: {u}" for u in auto.verify_claims(story, rows, header)]
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
    if not dry and _kv("animate_article_last") == today:
        log.info("already authored a story today, nothing to do"); return 0
    if not dry:
        tries = int(_kv(f"animate_article_tries_{today}") or 0)
        if tries >= auto.MAX_PASSES_PER_DAY:
            log.info("already ran %s authoring passes today without a story, stopping for the day", tries); return 0
        _kv(f"animate_article_tries_{today}", str(tries + 1))
    made = 0
    for run_id in candidates():
        if made >= max_stories:
            break
        log.info("article candidate run %s", run_id)
        try:
            story = attempt(run_id)
        except Exception as e:                                   # noqa: BLE001
            _kv(f"animate_run_{run_id}", f"rejected:{_tries(_kv(f'animate_run_{run_id}') or 'rejected:0') + 1}: {str(e)[:200]}")
            log.warning("rejected run %s: %s", run_id, e)
            continue
        if dry:
            print(json.dumps(story, indent=2, ensure_ascii=False)); made += 1; continue
        folder = auto.OUT / story["name"]
        (folder / "assets").mkdir(parents=True, exist_ok=True)
        auto.make_image(story, folder)
        story["approved"] = True
        (folder / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n")
        _kv(f"animate_run_{run_id}", f"authored: {story['name']}"); _kv("animate_article_last", today)
        log.info("wrote %s", folder / "story.json"); made += 1
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--max", type=int, default=1)
    a = ap.parse_args()
    sys.exit(0 if run(a.dry_run, a.max) >= 0 else 1)
