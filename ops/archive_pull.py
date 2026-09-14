"""Move staged documents into the permanent archive, and record them.

Run by ops/pull-archive.sh, which has already rsynced the digger's spool into a
staging directory. Kept as a separate module rather than inlined in the shell
script because it does the part that must not be got wrong: verify the bytes,
store them, record them, and only then delete the original.

Order matters and is the whole design:

    verify hash -> store bytes -> record row -> delete from spool

Any earlier step failing leaves the document on the digger for the next run. A
crash between store and record costs a re-store (content-addressed, so it is a
no-op). A crash between record and delete costs a re-pull. Neither loses a
document, which is the only outcome that actually matters — the archive exists
because the source may be gone by the time anyone looks again.
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from shared import archive, db

log = logging.getLogger("archive-pull")


def _record(meta, path, wayback):
    db.record_archived_doc(
        sha256=meta["sha256"],
        url=meta["url"],
        final_url=meta.get("final_url"),
        content_type=meta.get("content_type"),
        byte_size=meta.get("byte_size"),
        fetched_at=meta.get("fetched_at"),
        ocr_used=bool(meta.get("ocr_used")),
        wayback_url=wayback,
        pulled_at=datetime.now(timezone.utc).isoformat(),
    )
    log.info("archived %s (%s, %.1fKB)%s -> %s",
             meta["sha256"][:12], meta["url"][:70],
             (meta.get("byte_size") or 0) / 1024,
             " [OCR]" if meta.get("ocr_used") else "", path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("--vm")
    ap.add_argument("--key")
    ap.add_argument("--spool")
    ap.add_argument("--no-wayback", action="store_true",
                    help="skip the Internet Archive submission")
    args = ap.parse_args(argv)

    stage = Path(args.stage)
    stored = skipped = failed = 0
    collected = []

    for side in sorted(stage.glob("*.json")):
        blob = side.with_suffix("")          # a1b2....pdf.json -> a1b2....pdf
        if not blob.exists():
            log.warning("no bytes beside %s — leaving it on the spool", side.name)
            failed += 1
            continue
        try:
            meta = json.loads(side.read_text())
            data = blob.read_bytes()
        except (OSError, ValueError) as e:
            log.warning("unreadable staged entry %s: %s", blob.name, e)
            failed += 1
            continue

        try:
            path = archive.store(data, meta)
        except ValueError as e:
            # A hash mismatch is NOT a transient error and must not be retried
            # forever: the bytes are not what they claim to be, so storing them
            # would put something in the archive we cannot vouch for.
            log.error("%s — dropping this copy", e)
            failed += 1
            continue

        # The copy we do not host. Looked up before being requested: a snapshot
        # that predates us is better evidence than one we triggered, and it
        # spares the Archive a capture it already has.
        wayback = None
        if not args.no_wayback:
            wayback = (archive.wayback_lookup(meta["url"])
                       or archive.wayback_save(meta["url"]))

        try:
            _record(meta, path, wayback)
        except Exception as e:                              # noqa: BLE001
            # Stored but unrecorded. Safe: the next run re-stores (a no-op) and
            # tries the row again, and the spool copy is deliberately still there.
            log.warning("stored %s but could not record it (%s) — "
                        "leaving it on the spool for the next run",
                        meta["sha256"][:12], e)
            failed += 1
            continue

        collected.append(meta["filename"])
        stored += 1

    if collected and args.vm and args.spool:
        _drop_from_spool(args.vm, args.key, args.spool, collected)

    log.info("== %d stored, %d already held, %d left for next time ==",
             stored, skipped, failed)
    return 0


def _drop_from_spool(vm, key, spool, filenames):
    """Delete only the files that made it all the way into the archive."""
    names = "\n".join(filenames)
    cmd = ["ssh", "-i", key, "-o", "StrictHostKeyChecking=accept-new",
           f"opc@{vm}",
           f"cd {spool} && while read -r f; do rm -f -- \"$f\" \"$f.json\"; done"]
    try:
        subprocess.run(cmd, input=names, text=True, check=True, timeout=120)
        log.info("cleared %d file(s) from the digger's spool", len(filenames))
    except (subprocess.SubprocessError, OSError) as e:
        # Not fatal. A document left on the spool is re-pulled next run and
        # skipped as already held; the only cost is bandwidth.
        log.warning("could not clear the spool (%s) — it will be re-pulled", e)


if __name__ == "__main__":
    sys.exit(main())
