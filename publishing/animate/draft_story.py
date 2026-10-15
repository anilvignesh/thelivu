"""Draft a story file from finding IDs, for a human to edit and approve before anything renders.

    DATABASE_URL=... python -m publishing.animate.draft_story <finding_id> [<finding_id> ...] [-o story.json]

All findings must come from one document. Output is a skeleton, not a script: each beat carries `"_draft": true`
and its spoken text is the finding's claim verbatim. build_piece refuses to build while any `_draft` remains. The editor
rewrites each line for the ear (numbers in words, no bare acronyms), picks the scene type, adds the opening illustration,
and deletes the `_draft` flags. The grounding gate in build_piece then checks every figure and date.
"""
import json
import os
import re
import sys
from pathlib import Path


def _squash(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def draft(ids):
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(
        "select f.id, f.doc_sha256, f.claim, f.excerpt, f.amount_cr, f.category, d.title, d.url "
        "from findings f join documents d on d.sha256 = f.doc_sha256 where f.id = any(%s)", (list(ids),))
    rows = {r[0]: r for r in cur.fetchall()}
    conn.close()
    missing = [i for i in ids if i not in rows]
    if missing:
        raise SystemExit(f"no such findings: {missing}")
    docs = {rows[i][1] for i in ids}
    if len(docs) != 1:
        raise SystemExit("findings span more than one document; a story cites one source")
    first = rows[ids[0]]
    beats = [{"type": "illustration", "_draft": True, "title": "open", "head": ["TODO headline"],
              "say": [{"id": "open", "text": "TODO one plain sentence naming the audit.", "after": 1.8}],
              "data": {"image": "open.png"}}]
    for n, i in enumerate(ids, 1):
        _, _, claim, excerpt, amt, cat, _, _ = rows[i]
        beat = {"type": "excerpt", "_draft": True, "title": f"finding {i}", "head": ["TODO"], "refs": [i],
                "say": [{"id": f"f{n}", "text": _squash(claim), "after": 2.4}],
                "data": {"excerpt_of": i, "mark": [], "where": "CAG audit report"}}
        if amt:
            beat["_note"] = f"finding {i} carries amount_cr={amt}; consider a figure or compare beat, declare it in `numbers`"
        beats.append(beat)
    return {"name": "TODO-slug", "title": "TODO", "stamp": "CAG AUDIT · TODO", "doc_sha256": first[1],
            "source": {"publisher": "Comptroller and Auditor General of India", "title": first[6], "report": "TODO", "place": "TODO"},
            "beats": beats}


if __name__ == "__main__":
    args = sys.argv[1:]
    out = None
    if "-o" in args:
        k = args.index("-o"); out = args[k + 1]; del args[k:k + 2]
    story = draft([int(a) for a in args])
    text = json.dumps(story, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n"); print(f"draft written to {out}: edit, then remove every _draft flag")
    else:
        print(text)
