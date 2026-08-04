"""One-time: move the spine out of draft_text on belief runs written before the
split existed (#136-#140).

Those drafts are the writer's raw output — HEADLINE/DEK/ARTICLE/SOURCES/SPOKEN
SPINE in one blob. Left alone, `/a/<slug>` takes its title from the `## ARTICLE`
heading and prints the reel's narration under the sources. This rewrites
draft_text into the reader-facing page and stores the spine on belief_pieces,
which is exactly what the pipeline now does at write time.

Idempotent: a draft with no `## SPOKEN SPINE` section is already split and is
skipped. Nothing here touches a published run's text without saying so — run it
with --dry-run first.

    python -m engine.desks.ek.backfill_drafts --dry-run
    python -m engine.desks.ek.backfill_drafts
"""
import argparse
import sys

from engine.desks.ek import draft as draft_mod
from shared.db import (get_belief, init_db, save_belief_parts, update_run,
                       _conn, _fetchall)


def _belief_runs():
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, status, desk, draft_text FROM pipeline_runs "
                    "WHERE desk IN ('ek','gk') ORDER BY id")
        return _fetchall(cur)
    finally:
        conn.close()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    # belief_pieces.spine/.label are new columns; init_db's migrations add them
    # to an existing database. Run it here so the backfill works on a prod DB
    # that hasn't been through an engine boot since.
    init_db()

    for run in _belief_runs():
        rid, raw = run["id"], run.get("draft_text") or ""
        if not raw:
            print(f"#{rid}: no draft (parked before the writer) — skip")
            continue
        parts = draft_mod.split(raw)
        if not parts["spine"]:
            print(f"#{rid}: already split — skip")
            continue
        bel = get_belief(rid) or {}
        shape = bel.get("shape") or ""
        page = draft_mod.to_markdown(parts, shape=shape)
        label = draft_mod.view_label(dict(parts, shape=shape))
        print(f"#{rid}: {run['desk']}/{run['status']} shape={shape or '?'} "
              f"draft {len(raw)}→{len(page)} chars, "
              f"spine {len(draft_mod.spine_lines(parts['spine']))} lines"
              f"{', view label' if label else ''}")
        if a.dry_run:
            continue
        save_belief_parts(rid, spine=parts["spine"], label=label)
        update_run(rid, draft_text=page)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
