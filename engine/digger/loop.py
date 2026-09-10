"""Tier-0 digger loop — the service entrypoint.

    python -m engine.digger.loop            # run forever (systemd)
    python -m engine.digger.loop --once     # one cycle, then exit
    python -m engine.digger.loop --once --target cag-reports --dry-run

Design constraints that are not negotiable on this host (945MB burstable VM):
  * one target per cycle, one document set, hard caps on bytes and findings;
  * nothing is held in memory between cycles;
  * a failure in any single cycle is logged and slept off, never fatal — a
    service that dies on a transient free-provider 429 is worse than useless.
"""

import argparse
import logging
import os
import random
import sys
import time

from engine.digger import extract, fetch, freellm, targets
from shared import db

log = logging.getLogger("digger")

CYCLE_SECONDS = int(os.environ.get("DIGGER_CYCLE_SECONDS", "3600"))
MAX_DOCS_PER_CYCLE = int(os.environ.get("DIGGER_MAX_DOCS", "1"))
# Jitter so a restart storm doesn't align every cycle onto the same minute.
JITTER_FRAC = 0.15

_LAST_KEY = "digger_last_target"


def _kv_get(key, default=""):
    try:
        return db.kv_get(key) or default
    except Exception:
        return default


def _kv_set(key, value):
    try:
        db.kv_set(key, value)
    except Exception as e:
        log.warning("could not persist %s: %s", key, e)


def run_cycle(target=None, dry_run=False):
    """One target, fetched and read. Returns the candidate dicts recorded."""
    if target is None:
        target = targets.next_target(_kv_get(_LAST_KEY) or None)
    if target is None:
        log.warning("no targets configured")
        return []

    log.info("cycle start: %s (%s)", target["key"], target["index_url"])
    run_id = None if dry_run else db.start_digger_run(target["key"])
    docs = calls = 0
    recorded = []

    try:
        seen = set() if dry_run else db.digger_seen_urls(target["key"])

        # 1. Index -> candidate document URLs. The index is never extracted from;
        #    it exists only to choose a document (see targets.py).
        items = fetch.fetch_index(target["index_url"], target.get("link_pattern"))
        log.info("index: %d candidate document(s)", len(items))

        fresh = [i for i in items if i["url"] not in seen]
        if not fresh:
            log.info("nothing new at %s", target["key"])
            if not dry_run:
                db.finish_digger_run(run_id, ok=True, docs_fetched=0,
                                     candidates_found=0, model_calls=0)
                _kv_set(_LAST_KEY, target["key"])
            return []

        # 2. Fetch the actual documents, newest first, up to the per-cycle cap.
        candidates = []
        for item in fresh[:MAX_DOCS_PER_CYCLE]:
            try:
                doc = fetch.fetch(item["url"])
            except fetch.FetchError as e:
                # A dead link or a PDF is normal, not a cycle failure.
                log.info("skip %s: %s", item["url"][:80], e)
                continue
            docs += 1
            log.info("fetched %s (%d chars%s)", doc["final_url"], len(doc["text"]),
                     ", truncated" if doc["truncated"] else "")
            found, c = extract.cross_check(doc, target["brief"])
            calls += c
            candidates.extend(found)

        log.info("%d grounded finding(s) from %d doc(s), %d model call(s)",
                 len(candidates), docs, calls)

        for c in candidates:
            if c["source_url"] in seen:
                log.info("skip (already recorded): %s", c["title"][:80])
                continue
            if dry_run:
                log.info("[dry-run] %s | %s | %s",
                         c["agreement"], c["title"][:80], c["finding"][:120])
            else:
                db.record_digger_candidate(
                    target_key=target["key"],
                    title=c["title"],
                    finding=c["finding"],
                    source_url=c["source_url"],
                    excerpt=c["excerpt"],
                    model_a=c["model_a"],
                    model_b=c["model_b"],
                    answer_a=c["answer_a"],
                    answer_b=c["answer_b"],
                    agreement=c["agreement"],
                    fetched_at=c["fetched_at"],
                )
            recorded.append(c)

        if not dry_run:
            db.finish_digger_run(run_id, ok=True, docs_fetched=docs,
                                 candidates_found=len(recorded), model_calls=calls)
            _kv_set(_LAST_KEY, target["key"])
        return recorded

    except (fetch.FetchError, freellm.FreeLLMError) as e:
        # Expected, recoverable: a source is down, a PDF, a rate limit. Record
        # and move on to the next target next cycle.
        log.warning("cycle failed (%s): %s", target["key"], e)
        if not dry_run:
            db.finish_digger_run(run_id, ok=False, docs_fetched=docs,
                                 candidates_found=0, model_calls=calls, error=str(e)[:500])
            _kv_set(_LAST_KEY, target["key"])
        return []
    except Exception as e:
        log.exception("unexpected error in cycle %s", target["key"])
        if not dry_run:
            db.finish_digger_run(run_id, ok=False, docs_fetched=docs,
                                 candidates_found=0, model_calls=calls, error=str(e)[:500])
            _kv_set(_LAST_KEY, target["key"])
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="Thelivu Tier-0 digger")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("--target", help="target key (default: round-robin)")
    ap.add_argument("--dry-run", action="store_true",
                    help="do not write to the database")
    ap.add_argument("--list-targets", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.list_targets:
        for t in targets.TARGETS:
            print(f"{t['key']:22s} {t['url']}")
        return 0

    target = None
    if args.target:
        target = targets.BY_KEY.get(args.target)
        if target is None:
            print(f"unknown target: {args.target}", file=sys.stderr)
            print(f"known: {', '.join(targets.BY_KEY)}", file=sys.stderr)
            return 2

    if not freellm.ping():
        # Not fatal in --once (useful error), but worth shouting about.
        log.error("freellmapi is not answering at %s", freellm.base_url())
        if args.once:
            return 1

    if args.once:
        found = run_cycle(target=target, dry_run=args.dry_run)
        log.info("done: %d candidate(s)", len(found))
        return 0

    log.info("digger starting: cycle=%ss, targets=%d",
             CYCLE_SECONDS, len(targets.TARGETS))
    while True:
        run_cycle(target=target, dry_run=args.dry_run)
        nap = CYCLE_SECONDS * (1 + random.uniform(-JITTER_FRAC, JITTER_FRAC))
        log.info("sleeping %.0fs", nap)
        time.sleep(nap)


if __name__ == "__main__":
    raise SystemExit(main())
