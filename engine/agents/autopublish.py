"""Autonomous publish sweep — the human gate, narrowed to where it matters.

Autonomy grant, 2026-08-16 (Anil): the standing human-gate rule ("only publish
is gated, everything else runs free" — 2026-07-15 grant) is refined further.
Publish itself now splits by what the story is ABOUT:

  - No real person named in connection with an allegation → publishes AND posts
    autonomously, no tap. This is most of the institutional/systemic-story volume.
  - Names a real person alongside an allegation → still requires the human tap in
    Telegram, exactly as before. This is the one category where a week without
    review doesn't reduce the actual exposure (defamation liability isn't
    proportional to trial length), and the media-lawyer read this project has
    always meant to get (PROJECT-STATUS.md, pre-launch, never done) still hasn't
    happened. NOT covered by this autonomy grant. Do not extend it here without
    Anil explicitly revisiting this file.

One-week trial, review scheduled for the following Saturday. This file is where
that trial's mechanics live — read this docstring before loosening anything.

## The fail-closed rule (the one thing that must never invert)

`pipeline_runs.legal_flag` (the DB column) is fail-OPEN by construction: it is
only ever set to `True` (see `orchestrator._send_via_telegram`) — a run whose
review_text never got a parseable LEGAL-FLAG line at all also reads as
`legal_flag=False`. That's fine for its original purpose (a banner on top of
review a human does regardless). It is NOT fine as the gate for "skip human
review entirely" — a parsing miss must not silently mean "no review needed."

So this module does NOT trust the stored column for its own decision. It
re-derives eligibility straight from `review_text`, and only an EXPLICIT
`LEGAL-FLAG: NO` counts as clear — anything else (YES, missing, unparseable)
routes to the normal human-gated path, unchanged.
"""
import logging
import re

log = logging.getLogger("autopublish")


def _explicitly_legal_clear(review_text):
    """True only for an explicit 'LEGAL-FLAG: NO'. See module docstring — this is
    intentionally stricter than orchestrator._parse_legal_flag, which is fail-open
    by design for its own (banner-only) purpose and must not be reused here."""
    text = review_text or ""
    m = re.search(r"^\s*LEGAL-FLAG:\s*(YES|NO)\b", text, re.IGNORECASE | re.MULTILINE)
    return bool(m) and m.group(1).upper() == "NO"


def run_autopublish_sweep():
    """One pass: auto-publish eligible pending_human runs, then auto-post any
    pending_review carousel / ready reel for the SAME eligible runs whose posting
    timing looks right (engine.agents.posting_time), capped by MAX_DELAY_HOURS so
    news freshness always wins over chasing a marginally better hour.

    Cheap no-op when nothing's eligible. Call once per orchestrator tick, same as
    process_queued_carousels()."""
    _autopublish_pending_runs()
    _autopost_ready_carousels()
    _autopost_ready_reels()


def _autopublish_pending_runs():
    from shared.db import get_runs_by_status, get_run
    from publishing.publish import publish_run

    for run in get_runs_by_status("pending_human", limit=50):
        run_id = run["id"]
        full = get_run(run_id) or run
        if not _explicitly_legal_clear(full.get("review_text")):
            continue  # needs the human tap — unchanged path
        try:
            result = publish_run(run_id)
        except Exception as e:
            log.error("Autopublish failed for run #%s: %s", run_id, e, exc_info=True)
            _notify_safe(f"⚠️ Autopublish failed for run #{run_id}: {e}")
            continue
        if result.get("ok"):
            log.info("Autopublished run #%s (no real-person allegation; legal-clear)", run_id)
            _notify_safe(f"🤖 Auto-published run #{run_id} — no named-person allegation, "
                         f"reviewer said LEGAL-FLAG: NO. {result.get('article_url', '')}")
        else:
            log.warning("Autopublish for run #%s returned not-ok: %s", run_id, result)


def _autopost_ready_carousels():
    from shared.db import get_pending_carousels, get_run
    from publishing.publish import post_carousel_run
    from engine.agents.posting_time import recommend_now

    pending = get_pending_carousels()
    if not pending:
        return
    # Computed ONCE per sweep, not once per candidate — recommend_now() recomputes
    # the full priors query over all of ig_media/ig_media_metrics every call; doing
    # that per-candidate turned a handful of carousels into a 50s+ tick (measured
    # 2026-08-16 testing this). The recommendation doesn't change within one sweep.
    rec = recommend_now("FEED")
    for carousel in pending:
        run = get_run(carousel.get("run_id")) if carousel.get("run_id") else None
        if not run or not _explicitly_legal_clear(run.get("review_text")):
            continue  # not autopublish-eligible — waits for the human Post tap as before
        if not rec["post_now"]:
            continue  # holding for a better window, within the freshness cap
        try:
            result = post_carousel_run(carousel["id"])
        except Exception as e:
            log.error("Autopost failed for carousel #%s: %s", carousel["id"], e, exc_info=True)
            continue
        if result.get("ok"):
            log.info("Autoposted carousel #%s (%s)", carousel["id"], rec["reason"])
            _notify_safe(f"🤖 Auto-posted carousel for run #{carousel['run_id']} — {rec['reason']}. "
                         f"{result.get('permalink', '')}")


def _autopost_ready_reels():
    from shared.db import get_ready_reels, get_run
    from publishing.publish import post_reel_run
    from engine.agents.posting_time import recommend_now

    ready = get_ready_reels()
    if not ready:
        return
    # One query for every ready reel (get_ready_reels), not one query per published
    # run (get_runs_by_status + get_reel_for_run per row) — the latter is an N+1
    # that took 40s+ scanning 100 runs over Railway's Postgres link. See db.py's
    # get_ready_reels() docstring. recommend_now() hoisted out of the loop for the
    # same reason as the carousel sweep above.
    rec = recommend_now("REELS")
    for reel in ready:
        run = get_run(reel.get("run_id")) if reel.get("run_id") else None
        if not run or not _explicitly_legal_clear(run.get("review_text")):
            continue
        if not rec["post_now"]:
            continue
        try:
            result = post_reel_run(reel["id"])
        except Exception as e:
            log.error("Autopost failed for reel #%s: %s", reel["id"], e, exc_info=True)
            continue
        if result.get("ok"):
            log.info("Autoposted reel #%s (%s)", reel["id"], rec["reason"])
            _notify_safe(f"🤖 Auto-posted reel for run #{run['id']} — {rec['reason']}. "
                         f"{result.get('permalink', '')}")


def _notify_safe(text):
    """_notify lives in orchestrator and imports half the module graph — import
    lazily to avoid a circular import, and never let a notification failure take
    down the sweep itself."""
    try:
        from engine.agents.orchestrator import _notify
        _notify(text)
    except Exception as e:
        log.warning("Could not send autopublish notification: %s", e)
