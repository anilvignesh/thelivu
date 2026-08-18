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

## Incident, 2026-08-16, minutes after first deploy (read before touching this file)

First live sweep posted run #120's Assam-floods reel to Instagram THREE TIMES
(reels #18/19/20 — three separate /remake versions, all left at status='ready'
by reel_worker.py, which the first cut of get_ready_reels() returned as three
independent candidates) — and separately, it reached back into a *pre-existing
backlog from 2026-07-30* to do it, not just new work from today. Two distinct
bugs, both fixed the same day:

1. `get_ready_reels()` now dedupes to the latest row per run_id (shared/db.py).
2. `TRIAL_START` below — nothing whose PARENT RUN predates the trial is
   autopublish-eligible, full stop, regardless of when its carousel/reel row
   was created. "Only new ones" (Anil, 2026-08-16) is the standing rule now,
   not just today's patch.

Both checks now live in ONE place (`_autopublish_eligible`) instead of being
repeated per call site — the duplicate-post bug was exactly the kind of thing
that happens when the same judgment call is written three times and drifts.
"""
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger("autopublish")

# Nothing with a parent run created before this is autopublish-eligible, ever —
# see the incident note above. Bump this only if Anil explicitly asks to widen
# the trial to cover backlog; do not creep it forward silently.
TRIAL_START = datetime(2026, 8, 16, 6, 45, 12, tzinfo=timezone.utc)


def _explicitly_legal_clear(review_text):
    """True only for an explicit 'LEGAL-FLAG: NO'. See module docstring — this is
    intentionally stricter than orchestrator._parse_legal_flag, which is fail-open
    by design for its own (banner-only) purpose and must not be reused here."""
    text = review_text or ""
    m = re.search(r"^\s*LEGAL-FLAG:\s*(YES|NO)\b", text, re.IGNORECASE | re.MULTILINE)
    return bool(m) and m.group(1).upper() == "NO"


# A narrow, explicit exception to the anti-backlog rule below — added
# 2026-08-18, Anil's go-ahead ("sure") on clearing the 26-reel pre-trial
# backlog found that day. NOT a loosening of TRIAL_START itself (that stays
# protecting against ever silently sweeping in unreviewed old backlog, per the
# 2026-08-16 incident note) — this is a specific, individually-vetted allowlist,
# each id actually read (throughline, legal_flag, legal_reason, and for two
# with no parseable review_text — runs 111/112 — the full draft_text itself)
# before being added. 11 of the 26 had explicit "requires legal read before
# publication" reviewer notes (a named CM, a head of state, a sitting Chief
# Justice, named CBI accused, Andrew Tate, among others) and were deliberately
# NOT added — those stay with Anil. Two more (runs 145, 148) were already
# claimed under the separate EK-desk backlog carve-out. One more (run 154) had
# a clean legal check but its own reviewer verdict was "Fix-then-publish" with
# two specific unresolved fixes (an unsourced "some called it a scam" line, and
# a reader-facing process-narration leak) — checked the live draft_text: both
# are STILL there, never fixed, despite the article already being published —
# so this run is excluded here and flagged to Anil separately, not silently
# posted with known unfixed issues.
#
# Bypasses BOTH checks below (not just TRIAL_START) for ids in this set: an id
# only landed here after a full manual read stood in for what the automated
# checks verify, so re-requiring the regex-parseable LEGAL-FLAG line on top
# would just fail runs 111/112 (no review_text survives from their build) that
# were already read in full and found clean.
_BACKLOG_CLEARED_RUN_IDS = {53, 87, 111, 112, 113, 126, 127, 130, 142}


def _autopublish_eligible(run):
    """The ONE gate: legal-clear AND (not backlog OR explicitly vetted backlog).
    Every call site uses this — see the incident note for why that matters."""
    if not run:
        return False
    if run.get("id") in _BACKLOG_CLEARED_RUN_IDS:
        return True
    created = run.get("created_at")
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < TRIAL_START:
            return False
    return _explicitly_legal_clear(run.get("review_text"))


def run_autopublish_sweep():
    """One pass: auto-publish eligible pending_human runs, then auto-post any
    pending_review carousel / ready reel for the SAME eligible runs whose posting
    timing looks right (engine.distribution.timing), capped by MAX_DELAY_HOURS so
    news freshness always wins over chasing a marginally better hour.

    Cheap no-op when nothing's eligible. Call once per orchestrator tick, same as
    process_queued_carousels()."""
    _autopublish_pending_runs()
    _autopost_ready_carousels()
    _autopost_ready_reels()


# Minimum spacing between two autoposted pieces, across reels AND carousels —
# added 2026-08-17 auditing why reach/followers had stalled. The sweep had no
# cap on how many eligible items it posted per tick, so a backlog of ready
# items posted back to back: 6 reels in 5 minutes on 2026-08-15, 6 more in 26
# minutes on 2026-08-16 (visible directly in ig_media_metrics' posted_at
# timestamps). On a 20-follower account that reads as spam to both Instagram's
# distribution and any real follower, and every burst reel measurably
# underperformed the account's single best post (the very first reel, posted
# alone, hit 603 reach — nothing burst-posted since has passed 250). Not
# formally tuned, just "clearly more human than 6-in-5-minutes" — revisit once
# there's enough audience data to optimize a real number.
AUTOPOST_MIN_GAP_HOURS = 3


def _autopost_cooldown_active():
    """True if something posted within AUTOPOST_MIN_GAP_HOURS — the caller
    should stop autoposting for this tick, not just skip one candidate. Fails
    open (False, i.e. no cooldown) on a DB error: a throttle that can silently
    wedge autopost entirely is worse than an occasional double-pace tick."""
    from datetime import datetime, timezone
    from shared.db import most_recent_ig_post_at
    try:
        last = most_recent_ig_post_at()
    except Exception as e:
        log.error("Could not check posting cooldown, proceeding without one: %s", e)
        return False
    if not last:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    gap_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    return gap_hours < AUTOPOST_MIN_GAP_HOURS


def _autopublish_pending_runs():
    from shared.db import get_runs_by_status, get_run
    from publishing.publish import publish_run

    # get_runs_by_status defaults to desk='news' — calling it bare here silently
    # excluded the belief desks (ek, gk) from autopublish entirely since the
    # feature launched. Caught 2026-08-16 when Anil asked why ek pieces weren't
    # moving. Same legal gate applies to every desk; this was never about
    # relaxing anything for ek, just not skipping it.
    for desk in ("news", "ek", "gk"):
        for run in get_runs_by_status("pending_human", limit=50, desk=desk):
            run_id = run["id"]
            full = get_run(run_id) or run
            if not _autopublish_eligible(full):
                continue  # needs the human tap — unchanged path (or is backlog)
            try:
                result = publish_run(run_id)
            except Exception as e:
                log.error("Autopublish failed for run #%s: %s", run_id, e, exc_info=True)
                _notify_safe(f"⚠️ Autopublish failed for run #{run_id}: {e}")
                continue
            if result.get("ok"):
                log.info("Autopublished run #%s (desk=%s, legal-clear)", run_id, desk)
                _notify_safe(f"🤖 Auto-published run #{run_id} ({desk}) — no named-person "
                             f"allegation, reviewer said LEGAL-FLAG: NO. "
                             f"{result.get('article_url', '')}")
            else:
                log.warning("Autopublish for run #%s (desk=%s) returned not-ok: %s",
                           run_id, desk, result)


def _autopost_ready_carousels():
    from shared.db import get_pending_carousels, get_run
    from publishing.publish import post_carousel_run
    from engine.distribution.timing import recommend_now

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
        if not _autopublish_eligible(run):
            continue  # not autopublish-eligible — waits for the human Post tap as before
        if not rec["post_now"]:
            continue  # holding for a better window, within the freshness cap
        if _autopost_cooldown_active():
            log.info("Autopost cooldown active — holding remaining carousels this tick")
            return  # something posted recently (this run or reels); space it out
        try:
            result = post_carousel_run(carousel["id"])
        except Exception as e:
            log.error("Autopost failed for carousel #%s: %s", carousel["id"], e, exc_info=True)
            continue
        if result.get("ok"):
            log.info("Autoposted carousel #%s (%s)", carousel["id"], rec["reason"])
            _notify_safe(f"🤖 Auto-posted carousel for run #{carousel['run_id']} — {rec['reason']}. "
                         f"{result.get('permalink', '')}")
            return  # one post per tick — let the cooldown space out the rest


def _autopost_ready_reels():
    from shared.db import get_ready_reels, get_run
    from publishing.publish import post_reel_run
    from engine.distribution.timing import recommend_now

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
        if not _autopublish_eligible(run):
            continue
        if not rec["post_now"]:
            continue
        if _autopost_cooldown_active():
            log.info("Autopost cooldown active — holding remaining reels this tick")
            return  # something posted recently (this run or carousels); space it out
        try:
            result = post_reel_run(reel["id"])
        except Exception as e:
            log.error("Autopost failed for reel #%s: %s", reel["id"], e, exc_info=True)
            continue
        if result.get("ok"):
            log.info("Autoposted reel #%s (%s)", reel["id"], rec["reason"])
            _notify_safe(f"🤖 Auto-posted reel for run #{run['id']} — {rec['reason']}. "
                         f"{result.get('permalink', '')}")
            return  # one post per tick — let the cooldown space out the rest
        # YouTube cross-post now happens inside post_reel_run itself (same beat,
        # covers the dashboard tap too) — no separate call needed here.


def _crosspost_youtube(reel_id, run):
    """Cross-post the same reel to YouTube Shorts, independent of the Instagram
    post above (own double-post guard on youtube_video_id, so a retry of this
    function never re-uploads). Same eligibility already checked by the caller —
    this is purely "which platforms", not a second legal/backlog gate."""
    from datetime import datetime, timezone
    from shared.db import get_reel, get_reel_bytes, update_reel
    from publishing.youtube import publish_short, YouTubeNotConfigured

    r = get_reel(reel_id)
    if not r or r.get("youtube_video_id"):
        return  # already cross-posted, or reel vanished — nothing to do
    video_bytes = get_reel_bytes(reel_id)
    if not video_bytes:
        return
    title = ((run.get("throughline") if run else None)
              or f"Thelivu — reel #{reel_id}")[:100]
    try:
        video_id, permalink = publish_short(
            video_bytes, title, description=r.get("caption") or "")
    except YouTubeNotConfigured:
        return  # not set up yet — silent, not an error; the Instagram post still landed
    except Exception as e:
        log.error("YouTube cross-post failed for reel #%s: %s", reel_id, e, exc_info=True)
        return
    update_reel(reel_id, youtube_video_id=video_id, youtube_permalink=permalink,
               youtube_posted_at=datetime.now(timezone.utc))
    log.info("Cross-posted reel #%s to YouTube Shorts: %s", reel_id, permalink)
    _notify_safe(f"🤖 Cross-posted to YouTube Shorts — {permalink}")


# Backfill, 2026-08-16 (Anil): every reel already posted to Instagram is, by
# definition, already through full editorial review + human approval — publishing
# to IG has always required the human tap, long before today's autopublish trial
# existed. So catching YouTube up on that history is a pure distribution decision,
# not a second legal/editorial gate. Paced deliberately: after posting 3 duplicate
# reels within 2 minutes earlier today (see the incident note above), a bulk dump
# is exactly what this project should not do again.
YOUTUBE_BACKFILL_DAILY_CAP = 2


def run_youtube_backfill_sweep():
    """Cross-post the oldest not-yet-on-YouTube Instagram reels, capped at
    YOUTUBE_BACKFILL_DAILY_CAP per day. Call once per tick alongside the main
    sweep — cheap no-op once the backlog is cleared or today's cap is spent."""
    from shared.db import get_youtube_backfill_candidates, count_youtube_crossposts_today, get_run

    remaining = YOUTUBE_BACKFILL_DAILY_CAP - count_youtube_crossposts_today()
    if remaining <= 0:
        return
    candidates = get_youtube_backfill_candidates(limit=remaining)
    for reel in candidates:
        run = get_run(reel.get("run_id")) if reel.get("run_id") else None
        if not run:
            continue
        _crosspost_youtube(reel["id"], run)


def _notify_safe(text):
    """_notify lives in orchestrator and imports half the module graph — import
    lazily to avoid a circular import, and never let a notification failure take
    down the sweep itself."""
    try:
        from engine.agents.orchestrator import _notify
        _notify(text)
    except Exception as e:
        log.warning("Could not send autopublish notification: %s", e)
