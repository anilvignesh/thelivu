#!/bin/bash
# Auto-update for the Oracle VM's reel-building services.
#
# Added 2026-08-30 after discovering this VM had been running 11-day-old
# code (last manually deployed 2026-08-19) with NO auto-deploy mechanism at
# all -- unlike Railway, which auto-deploys on every push to `main`. Every
# fix committed in that window (two caption-leak fixes, the reveal-pacing
# fix, the FLUX-outage alert) was live in the repo but never reached the
# machine that actually builds reels, so "fixed" bugs kept recurring because
# they were never actually fixed in production here.
#
# Secrets (Railway variables -> this VM's reel-worker.env) are a SEPARATE
# concern, synced from the laptop via ops/oracle-vm/deploy-secrets.sh on its
# own scheduled task there -- deliberately not from this VM, so an
# internet-facing box never holds a Railway credential. See that script's
# own header for why.
#
# Idempotent and safe to run frequently: each half does nothing if nothing
# changed. Restarts reel-worker/chatterbox only when something actually did,
# so this can briefly interrupt an in-flight render on an update -- accepted
# trade-off, same resilience class as everything else in this pipeline (a
# lost render attempt costs one cycle, never data).
set -u

REPO=/home/ubuntu/thelivu
LOG_TAG="thelivu-auto-update"

cd "$REPO"

# --- Code sync ---
git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    logger -t "$LOG_TAG" "updating $LOCAL -> $REMOTE"
    REQS_CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE" -- requirements.txt)
    if git pull --ff-only origin main >>/tmp/thelivu-auto-update.log 2>&1; then
        if [ -n "$REQS_CHANGED" ]; then
            logger -t "$LOG_TAG" "requirements.txt changed -- reinstalling"
            "$REPO/venv/bin/pip" install -r requirements.txt >>/tmp/thelivu-auto-update.log 2>&1 || \
                logger -t "$LOG_TAG" "pip install failed -- restarting services anyway, they may fail to start"
        fi
        sudo systemctl restart reel-worker chatterbox
        logger -t "$LOG_TAG" "restarted reel-worker + chatterbox on $REMOTE"
    else
        logger -t "$LOG_TAG" "git pull --ff-only FAILED (local commit? diverged history?) -- not restarting services on a bad pull"
    fi
fi

