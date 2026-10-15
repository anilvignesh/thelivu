"""Story file -> an animate piece folder, ready for the animate skill's voice/build/export/review tools.

    python -m publishing.animate.build_piece publishing/animate/stories/<name>/story.json OUT_DIR [--no-check]

A story is a list of beats; each beat is one scene type (see lib/scenes.js), one or more spoken lines, and the data that scene
draws. Nothing on screen is scraped from the narration: dates, figures and excerpts are declared, and this refuses to build
unless every declared figure and date is found in the findings the beat cites, and every excerpt is the finding's own text.
That is BRAND.md "any video" rule 2, enforced. The check needs DATABASE_URL (production); --no-check skips it for layout work.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGO = HERE.parent.parent / "branding" / "assets" / "logo-hires.png"
TAIL = 1.8 + 3.5 + 3.2   # the hold after the last line, the silent source card, the sign-off card


def _squash(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _fetch(ids):
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("select id, claim, excerpt from findings where id = any(%s)", (list(ids),))
    rows = {r[0]: {"claim": _squash(r[1]), "excerpt": _squash(r[2])} for r in cur.fetchall()}
    conn.close()
    return rows


def _year(s):
    y, m = s.split("-")
    return round(int(y) + (int(m) - 1) / 12, 3)


def check_and_fill(story, check=True):
    drafts = [b.get("title", "?") for b in story["beats"] if b.get("_draft")]
    if drafts:
        raise SystemExit(f"draft beats not yet approved (remove _draft): {drafts}")
    ids = {i for b in story["beats"] for i in b.get("refs", [])}
    ids |= {b["data"]["excerpt_of"] for b in story["beats"] if "excerpt_of" in b.get("data", {})}
    if check and story.get("run_id"):                       # an article story: the evidence is the article's own passages
        from publishing.animate import articles
        rows, headline = articles.rows_for(story["run_id"])
        rows = {i: {"claim": _squash(r["claim"]), "excerpt": _squash(r["excerpt"])} for i, r in rows.items()}
    else:
        headline = None
        rows = _fetch(ids) if (check and ids) else {}
    problems = []
    if headline is not None and _squash(story["source"]["title"]) != _squash(headline):
        problems.append("source.title is not the article's headline")
    if check and story.get("doc_sha256"):
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"]); cur = conn.cursor()
        cur.execute("select title from documents where sha256=%s", (story["doc_sha256"],))
        r = cur.fetchone(); conn.close()
        if not r or _squash(r[0]).replace("&amp;", "&").find(story["source"]["title"]) < 0:
            problems.append("source.title is not in the cited document's title")
    for n, b in enumerate(story["beats"], 1):
        d = b.setdefault("data", {})
        if check and b.get("refs"):
            missing = [i for i in b["refs"] if i not in rows]
            if missing:
                problems.append(f"beat {n}: finding(s) {missing} not found")
            hay = " ".join(rows[i]["excerpt"] + " " + rows[i]["claim"] for i in b["refs"] if i in rows).replace("–", "-")
            for num in b.get("numbers", []):
                if num not in hay:
                    problems.append(f"beat {n}: declared '{num}' not in findings {b['refs']}")
        elif check and b.get("numbers"):
            problems.append(f"beat {n}: numbers declared but no refs")
        if "excerpt_of" in d:
            if check:
                d["text"] = rows[d["excerpt_of"]]["excerpt"]
                for m in d.get("mark", []):
                    if m not in d["text"]:
                        problems.append(f"beat {n}: mark '{m}' not in the excerpt")
            elif "text" not in d:
                d["text"] = "(excerpt text is filled from the findings table at build)"
        if b["type"] == "timeline":
            d["events"] = [dict(e, at=_year(e["at"]) if isinstance(e["at"], str) else e["at"]) for e in d["events"]]
            d["spans"] = [dict(s, **{"from": _year(s["from"]), "to": _year(s["to"])}) for s in d.get("spans", [])]
    if problems:
        sys.exit("story does not check out:\n  " + "\n  ".join(problems))
    return story


def build(story_path, out, check=True):
    story_path, out = Path(story_path), Path(out)
    story = check_and_fill(json.loads(story_path.read_text(encoding="utf-8")), check)
    (out / "src").mkdir(parents=True, exist_ok=True); (out / "voice").mkdir(exist_ok=True); (out / "assets").mkdir(exist_ok=True)
    head = (HERE / "lib" / "head.html").read_text(encoding="utf-8")
    head = head.replace("__TITLE__", story["title"]).replace("__STORY__", json.dumps(story, ensure_ascii=False))
    (out / "src" / "head.html").write_text(head, encoding="utf-8")
    for f in ("scenes.js", "bridges.js", "score.js"):
        shutil.copy(HERE / "lib" / f, out / "src" / f)
    shutil.copy(LOGO, out / "assets" / "logo.png")
    for b in story["beats"]:
        for key in ("image", "bg", "bg2"):
            img = b.get("data", {}).get(key)
            if img:   # jpeg keeps the single-file page small
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(story_path.parent / "assets" / img), "-q:v", "3",
                                str(out / "assets" / (Path(img).stem + ".jpg"))], check=True)
                b["data"][key] = Path(img).stem + ".jpg"
    # the image names changed to .jpg: rewrite the head's copy of the story
    head = (HERE / "lib" / "head.html").read_text(encoding="utf-8")
    head = head.replace("__TITLE__", story["title"]).replace("__STORY__", json.dumps(story, ensure_ascii=False))
    (out / "src" / "head.html").write_text(head, encoding="utf-8")
    lines = [{"id": s["id"], "text": s["text"], "after": s.get("after", 0.5)} for b in story["beats"] for s in b["say"]]
    (out / "voice" / "script.json").write_text(json.dumps({"lead": 0.6, "tail": TAIL, "lines": lines}, indent=1), encoding="utf-8")
    (out / "piece.json").write_text(json.dumps({
        "name": story["name"], "title": story["title"],
        "format": {"width": 1080, "height": 1920, "fps": 24, "bpm": 120, "duration": 60.0, "frames": 1440},
        "storyFormat": "chronology, hard cuts on the 8th grid", "style": "math",
        "voice": {"file": "voice/voice.wav", "music": -12},
        "review": {"safe": {"top": 240, "bottom": 420, "right": 140}, "refs": {}}}, indent=1), encoding="utf-8")
    print(f"built piece {out} ({len(story['beats'])} beats, {len(lines)} spoken lines)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    build(args[0], args[1], check="--no-check" not in sys.argv)
