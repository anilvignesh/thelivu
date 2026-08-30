"""Autonomous publish sweep — full autonomy, notify-only.

Autonomy grant, 2026-08-16 (Anil): the standing human-gate rule ("only publish
is gated, everything else runs free" — 2026-07-15 grant) is refined further.
For one week, publish split by what the story was ABOUT — no-named-person
stories autopublished, named-person-plus-allegation stories still needed a
Telegram tap — pending a Saturday review.

## Made permanent AND extended, 2026-08-29 (Anil, explicit)

Two changes, both deliberate, both confirmed after Anil was told exactly what
they mean:

1. **The 2026-08-16 trial is over — it's the permanent policy, not provisional.**
   No further "Saturday review" checkpoint.
2. **The named-person/allegation carve-out is REMOVED.** Every run that clears
   normal editorial review (draft → verify → review) autopublishes and posts,
   full stop — including stories naming a real person alongside an allegation.
   There is no legal/defamation human gate left in this pipeline. Anil was
   told, in these terms, before confirming: this exposes him personally to
   defamation liability on content no lawyer has ever reviewed (the
   media-lawyer read this project always meant to get, PROJECT-STATUS.md
   pre-launch, still never happened), and a bad post can't be un-published
   once it's out — his call was "yes, remove it fully," with the explicit
   fallback being he watches Telegram and deletes anything he judges
   unnecessary after the fact, not before.

`send_for_approval` / `_send_via_telegram` (orchestrator.py) still fires for
every run and still shows the ⚠️ LEGAL banner when `LEGAL-FLAG: YES` parses —
that stays as a heads-up Anil reads after the fact, per his own framing. It is
no longer a gate anything waits on.

## History below, kept for context — do not use it to re-derive today's gate

The subsections below (fail-closed rule, first incident) describe the
2026-08-16–29 design, where `_explicitly_legal_clear` genuinely gated
publish. It no longer does — see above. Left in place so the reasoning that
produced `_BACKLOG_CLEARED_RUN_IDS` and `TRIAL_START` (both still real, both
still enforced) is still legible.

### The fail-closed rule (historical — no longer wired to a gate)

`pipeline_runs.legal_flag` (the DB column) is fail-OPEN by construction: it is
only ever set to `True` (see `orchestrator._send_via_telegram`) — a run whose
review_text never got a parseable LEGAL-FLAG line at all also reads as
`legal_flag=False`. That was fine for its original purpose (a banner on top of
review a human does regardless) and NOT fine as a gate for "skip human review
entirely" — which is exactly why, while it was still a gate, this module never
trusted the stored column and re-derived eligibility straight from
`review_text` via `_explicitly_legal_clear`. That helper is unused by
`_autopublish_eligible` now; kept only in case a future gate needs the same
strict parse.

### Incident, 2026-08-16, minutes after first deploy (read before touching this file)

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

from shared import content_safety

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
_BACKLOG_CLEARED_RUN_IDS = {53, 87, 112, 113, 126, 127, 130, 142}
# 111 removed 2026-08-18: it already had a reel posted weeks ago (reel #9,
# 2026-07-26) that this allowlist didn't check for — only the run/article was
# vetted, not whether the reel TABLE already had a posted row for it. Two
# leftover 'ready' rows from old remake history (#4, #7) both posted as
# duplicates before this was caught. Real posts already live; can't be
# undone via API (see publish.py's reset_run_for_review note — a bad post on
# the channel needs deleting there by hand). Not re-adding without also
# fixing the vetting to check reels-per-run, not just runs.


def _autopublish_eligible(run):
    """The ONE gate: not backlog OR explicitly vetted backlog.

    2026-08-29: the legal/defamation carve-out that used to sit here
    (`_explicitly_legal_clear(run.get("review_text"))`) is gone — see the
    module docstring's "Made permanent AND extended" section for the explicit
    decision behind that. Every editorially-reviewed run is eligible now;
    `TRIAL_START` and the backlog allowlist are the only remaining checks, and
    both predate and are independent of the legal gate that was removed.
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
    return True


def run_autopublish_sweep():
    """One pass: auto-publish eligible pending_human runs, then auto-post
    whichever of (ready reel, pending carousel) is best inside the fixed
    10:00/18:00 IST windows — see POST_SLOTS_IST above. At most one post per
    window, reel preferred over carousel, and only if something eligible is
    actually ready — engine.distribution.timing's learned-priors approach is
    no longer used by either format as of 2026-08-30.

    Cheap no-op when nothing's eligible. Call once per orchestrator tick, same as
    process_queued_carousels()."""
    _autopublish_pending_runs()
    _autopost_ready_slot()


# Fixed posting schedule (Anil, 2026-08-30) — replaces the learned
# posting-time priors / freshness-cap approach (engine.distribution.timing)
# for BOTH reels and carousels (carousels folded in the same day, after
# Anil clarified "just apply the same fixed schedule" rather than dropping
# the format). Reasoning, verbatim: "we are not trying to be a breaking news
# channel... so for us, time is fine" — the 6h MAX_DELAY_HOURS freshness cap
# in timing.py existed specifically to avoid holding "stale" news, which Anil
# says isn't a real cost here. Two fixed daily windows instead: 10:00 and
# 18:00 IST.
#
# Format choice within a slot, per Anil ("where you think carousel is
# better, publish that, but if reels is better use that"): REELS ARE
# PREFERRED BY DEFAULT. This isn't a coin flip — timing.py's own docstring
# documents reels and carousels ~10x apart in reach in the actual data, so
# "reels is better" is the empirically common case, not a guess. Carousel
# only posts when NO eligible reel is ready this window, which gives it a
# real job (filling the slot when video isn't ready) instead of running a
# second, redundant, permanently-losing posting system alongside reels.
#
# Also NOT mandatory (Anil, explicit): a window firing with nothing eligible
# ready in EITHER format posts nothing — no forced/filler content just to
# hit the slot. Desk priority when something IS ready: news desk first,
# EK/GK belief desk as fallback — "if we don't have anything as news, we
# will publish the other desk." Belief-desk QUALITY is a separate follow-up
# Anil flagged for later, not addressed by this scheduling change.
POST_SLOTS_IST = [(10, 0), (18, 0)]
POST_SLOT_WINDOW_MINUTES = 10  # comfortably >1 tick (ticks are every 2 min)
LAST_POST_SLOT_KEY = "last_post_slot"


def _current_post_slot(now_utc=None):
    """The IST slot key ('YYYY-MM-DD:HHMM') if `now_utc` falls inside one of
    POST_SLOTS_IST's windows, else None. A window, not an instant, so a
    tick landing a few minutes after the mark still catches it."""
    from datetime import timedelta
    from engine.distribution.timing import IST_OFFSET
    now_utc = now_utc or datetime.now(timezone.utc)
    ist_now = now_utc + IST_OFFSET
    for hour, minute in POST_SLOTS_IST:
        start = ist_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= ist_now < start + timedelta(minutes=POST_SLOT_WINDOW_MINUTES):
            return f"{ist_now.date()}:{hour:02d}{minute:02d}"
    return None


def _eligible_ranked(items, get_run_fn):
    """Shared filter+sort for both formats: drop non-eligible runs, then rank
    news desk ahead of EK/GK, oldest id first within a desk."""
    out = []
    for item in items:
        run = get_run_fn(item.get("run_id")) if item.get("run_id") else None
        if not _autopublish_eligible(run):
            continue
        out.append((run, item))
    out.sort(key=lambda pair: (0 if ((pair[0] or {}).get("desk") or "news") == "news" else 1,
                                pair[1]["id"]))
    return out


# Minimum spacing between two autoposted pieces, across reels AND carousels —
# added 2026-08-17 auditing why reach/followers had stalled (a ready-item
# backlog posted back to back: 6 reels in 5 minutes on 2026-08-15, 6 more in
# 26 minutes on 2026-08-16). REMOVED 2026-08-30: moot now that posting only
# happens inside POST_SLOTS_IST's two windows, which are 8h/16h apart —
# always well past any burst-spacing threshold that made sense here. If a
# THIRD slot is ever added closer than a few hours to another, revisit
# whether a cooldown is needed again; git history has the old
# AUTOPOST_MIN_GAP_HOURS / _autopost_cooldown_active implementation.


def _autopublish_pending_runs():
    from shared.db import get_runs_by_status, get_run
    from publishing.publish import publish_run
    from engine.agents.orchestrator import _parse_legal_flag

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
                # 2026-08-29: legal_flag no longer gates anything (see module
                # docstring), but it still says something true about the run,
                # and Anil's own stated fallback is watching this notification
                # and deleting anything he judges unnecessary — so the heads-up
                # says plainly when a run carries a legal flag instead of
                # implying every autopublish was legal-clear.
                legal_flag, legal_reason = _parse_legal_flag(full.get("review_text"))
                flag_note = (f"⚠️ reviewer flagged LEGAL-FLAG: YES ({legal_reason})"
                             if legal_flag else "reviewer: LEGAL-FLAG clear or unparsed")
                # Content-safety guardrail (shared/content_safety.py, added
                # 2026-08-29) — a DIFFERENT, narrower check than legal_flag:
                # policy-violation content (hate/violence/self-harm framing),
                # not defamation. Advisory only, same as the legal banner
                # above and for the same reason — a hard gate here would be a
                # step MORE restrictive than what Anil just explicitly chose
                # for the more serious defamation risk the same day, and a
                # generic safety classifier flags real crime/violence
                # journalism as a false positive often enough that blocking
                # on it would silently stall legitimate stories. None (check
                # unavailable — no key, network error) says nothing, quietly.
                safety_verdict = content_safety.check(full.get("draft_text"))
                safety_note = ("" if safety_verdict is None else
                               "" if safety_verdict else
                               " ⚠️ content-safety guardrail flagged this UNSAFE — read it")
                log.info("Autopublished run #%s (desk=%s, legal_flag=%s, content_safety=%s)",
                         run_id, desk, legal_flag, safety_verdict)
                _notify_safe(f"🤖 Auto-published run #{run_id} ({desk}) — {flag_note}."
                             f"{safety_note} {result.get('article_url', '')}")
            else:
                log.warning("Autopublish for run #%s (desk=%s) returned not-ok: %s",
                           run_id, desk, result)


AUTOPOST_PAUSE_KEY = "autopost_paused"


def _autopost_ready_slot():
    """Fixed-schedule poster for BOTH reels and carousels (2026-08-30) — see
    POST_SLOTS_IST's comment above. One post per window, reel preferred over
    carousel (empirically ~10x the reach), news desk preferred over EK/GK
    within whichever format wins, nothing posted if nothing eligible is
    ready in either format — not mandatory.

    Manual kill switch (AUTOPOST_PAUSE_KEY, 2026-08-30): Anil, after a reel
    posted with no illustrations (FLUX outage, fell back to text-slides) and
    another with a caption-reveal pacing problem — "I would rather stop
    posting rather than posting this shit." This only pauses POSTING to
    Instagram/YouTube; drafting, editorial review, and reel rendering keep
    running underneath so nothing is lost, and whatever's ready is still
    there once resumed. Toggle via the Telegram bot: /pauseposting,
    /resumeposting. Does NOT touch _autopublish_pending_runs (publishing the
    article to the website) — that's text, unaffected by either bug."""
    from shared.db import get_ready_reels, get_pending_carousels, get_run, kv_get, kv_set

    if kv_get(AUTOPOST_PAUSE_KEY):
        return  # posting paused — see docstring above

    from publishing.publish import post_reel_run, post_carousel_run

    now = datetime.now(timezone.utc)
    slot = _current_post_slot(now)
    if not slot:
        return  # outside the 10:00/18:00 IST windows — wait, don't force a post
    if kv_get(LAST_POST_SLOT_KEY) == slot:
        return  # already handled this window (posted, or confirmed nothing ready)

    # One query for every ready reel/carousel, not one query per published run
    # (get_runs_by_status + a per-row lookup) — the latter is an N+1 that took
    # 40s+ scanning 100 runs over Railway's Postgres link. See db.py's
    # get_ready_reels() docstring.
    reel_candidates = _eligible_ranked(get_ready_reels(), get_run)
    if reel_candidates:
        run, reel = reel_candidates[0]
        try:
            result = post_reel_run(reel["id"])
        except Exception as e:
            log.error("Autopost failed for reel #%s: %s", reel["id"], e, exc_info=True)
            return  # don't stamp the slot — worth another try later this window
        if result.get("ok"):
            kv_set(LAST_POST_SLOT_KEY, slot)
            desk = (run or {}).get("desk") or "news"
            log.info("Autoposted reel #%s (desk=%s, slot=%s)", reel["id"], desk, slot)
            _notify_safe(f"🤖 Auto-posted reel for run #{run['id']} ({desk} desk) — "
                         f"{slot} slot. {result.get('permalink', '')}")
            # YouTube cross-post happens inside post_reel_run itself (same
            # beat, covers the dashboard tap too) — no separate call needed.
        return

    carousel_candidates = _eligible_ranked(get_pending_carousels(), get_run)
    if carousel_candidates:
        run, carousel = carousel_candidates[0]
        try:
            result = post_carousel_run(carousel["id"])
        except Exception as e:
            log.error("Autopost failed for carousel #%s: %s", carousel["id"], e, exc_info=True)
            return  # don't stamp the slot — worth another try later this window
        if result.get("ok"):
            kv_set(LAST_POST_SLOT_KEY, slot)
            desk = (run or {}).get("desk") or "news"
            log.info("Autoposted carousel #%s (desk=%s, slot=%s, no reel ready)",
                     carousel["id"], desk, slot)
            _notify_safe(f"🤖 Auto-posted carousel for run #{run['id']} ({desk} desk) — "
                         f"{slot} slot, no reel was ready. {result.get('permalink', '')}")
        return

    # Nothing eligible in either format this window — skip, not an error.
    kv_set(LAST_POST_SLOT_KEY, slot)
    log.info("Slot %s: nothing eligible ready (reel or carousel), posting nothing", slot)


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
