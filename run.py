import os

service = os.environ.get("RAILWAY_SERVICE_NAME", "thelivu")

if service == "thelivu-agent":
    from engine.agents.orchestrator import run_daily_cycle, process_recheck_requests, process_queued_carousels, cleanup_finished_carousels, send_cost_report, run_source_scout, run_story_scout, run_story_tracker, run_meta_synthesis, run_dig_advance, promote_dig, run_chief_of_staff, _cost_report_due
    import time, logging, sys
    from datetime import datetime, timezone, timedelta
    from shared.config import ANTHROPIC_API_KEY, APPROVAL_MODE, TELEGRAM_BOT_TOKEN, TELEGRAM_DRAFT_CHAT_ID, CHECK_INTERVAL_HOURS, REPO_ROOT, SLIDE_SERVER_BASE_URL, SLIDE_SERVER_PORT
    from shared.db import init_db, kv_get, kv_set, update_run, get_due_digs
    from shared import quota

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
    log = logging.getLogger("orchestrator")

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set."); sys.exit(1)
    if APPROVAL_MODE == "telegram" and (not TELEGRAM_BOT_TOKEN or not TELEGRAM_DRAFT_CHAT_ID):
        log.error("APPROVAL_MODE=telegram but Telegram vars not set."); sys.exit(1)

    if SLIDE_SERVER_BASE_URL:
        from publishing.fileserver import start as start_fileserver
        start_fileserver(REPO_ROOT / "articles" / "slides", SLIDE_SERVER_PORT)
    else:
        log.info("SLIDE_SERVER_BASE_URL not set — slide images will fall back to Telegram's CDN URL.")

    from shared.db import clear_stale_agents, clear_stale_topics, get_held_runs
    init_db()
    clear_stale_agents()
    n = clear_stale_topics()
    if n:
        log.warning("Startup: reset %d stuck pending_topic(s) to queued", n)
    log.info("Thelivu agent starting | Approval: %s | Interval: %dh", APPROVAL_MODE, CHECK_INTERVAL_HOURS)

    _cost_report_sent_date = None

    from shared.db import pop_next_topic, finish_topic

    _last_rss_run = None
    _cost_report_sent_date = None
    _breaker_logged_at = None  # throttle the "paused" log to twice an hour
    TOPIC_POLL_SECONDS = 120  # check for owner topics every 2 minutes

    # How long a FAILED rss cycle waits before retrying. The full interval would
    # be too long for a blip; retrying immediately is what produced the 2026-07-21
    # crash loop, because _last_rss_run was only stamped on success.
    RSS_RETRY_MINUTES = 30

    def _tg_notify(text):
        """Send a plain-text notification to the draft chat from run.py."""
        try:
            import requests as _req
            _req.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": str(TELEGRAM_DRAFT_CHAT_ID), "text": text[:4096]},
                timeout=10,
            )
        except Exception as e:
            log.warning("Notification send failed: %s", e)

    while True:
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        # Daily cost report — time configurable via /setcost HH:MM (kv: cost_report_utc)
        if _cost_report_due(now_utc) and _cost_report_sent_date != today:
            try:
                send_cost_report()
                _cost_report_sent_date = today
            except Exception as e:
                log.error("Cost report failed: %s", e)

        # ── Work that needs no model ──────────────────────────────────────────
        # Deliberately ABOVE the quota breaker: when the APIs run dry the
        # publishing surface must stay alive. Anil can still approve drafts and
        # post carousels from Telegram/the dashboard with no model reachable.

        # Delete rendered slide files for carousels that finished (posted/killed/failed) —
        # keeps the volume from filling up with images nobody needs anymore.
        try:
            cleanup_finished_carousels()
        except Exception as e:
            log.error("Carousel file cleanup failed: %s", e, exc_info=True)

        # Auto-recheck held stories older than 3 days (once per day)
        try:
            last_auto = kv_get("last_auto_recheck_at")
            auto_due = (not last_auto) or (now_utc - datetime.fromisoformat(last_auto)).total_seconds() >= 20 * 3600
            if auto_due:
                kv_set("last_auto_recheck_at", now_utc.isoformat())
                stale = get_held_runs(older_than_days=3)
                for run in stale:
                    update_run(run["id"], status="recheck_requested")
                    log.info("Auto-queued recheck for held run #%d (>3 days held)", run["id"])
                if stale:
                    log.info("Auto-recheck: queued %d held story/stories", len(stale))
        except Exception as e:
            log.error("Auto-recheck failed: %s", e)

        # ── Quota breaker ─────────────────────────────────────────────────────
        # Both providers ran dry on 2026-07-21 and the tick spent 22 hours
        # crashing on a 429 every 2 minutes. While the breaker is open we skip
        # every model stage instead. It auto-expires (60 min) so a top-up or a
        # midnight quota reset recovers on its own. There is deliberately NO
        # fallback to another engine — the work parks and Anil runs the cycle
        # attended. See docs/attended-mode.md.
        try:
            blocked_reason = quota.is_blocked()
        except Exception as e:
            log.warning("Breaker check failed (assuming clear): %s", e)
            blocked_reason = None

        if blocked_reason:
            if _breaker_logged_at is None or (now_utc - _breaker_logged_at).total_seconds() >= 1800:
                _breaker_logged_at = now_utc
                until = quota.blocked_until()
                log.warning("LLM stages paused — %s (retrying after %s)",
                            blocked_reason, until.strftime("%H:%M UTC") if until else "expiry")
            time.sleep(TOPIC_POLL_SECONDS)
            continue
        _breaker_logged_at = None

        # Weekly: source scout + story scout + story tracker
        try:
            last_scout = kv_get("last_scout_at")
            if not last_scout:
                kv_set("last_scout_at", now_utc.isoformat())
                log.info("Weekly jobs scheduled for 7 days from now.")
            elif (now_utc - datetime.fromisoformat(last_scout)).days >= 7:
                # Stamp BEFORE running so a mid-way failure can't retry-storm
                # (re-posting source proposals + re-calling models every 2 min).
                kv_set("last_scout_at", now_utc.isoformat())
                run_source_scout()
                run_story_scout()
                run_story_tracker()
        except Exception as e:
            log.error("Weekly jobs failed: %s", e)

        # Monthly: meta-synthesis
        try:
            last_meta = kv_get("last_meta_at")
            if not last_meta:
                kv_set("last_meta_at", now_utc.isoformat())
            elif (now_utc - datetime.fromisoformat(last_meta)).days >= 30:
                kv_set("last_meta_at", now_utc.isoformat())
                run_meta_synthesis()
        except Exception as e:
            log.error("Meta-synthesis failed: %s", e)

        # Owner /recheck requests — pick up promptly (cheap when none pending).
        try:
            process_recheck_requests()
        except Exception as e:
            log.error("Recheck processing failed: %s", e, exc_info=True)

        # Carousels queued by an article approval — compose + render + send for review.
        try:
            process_queued_carousels()
        except Exception as e:
            log.error("Carousel processing failed: %s", e, exc_info=True)

        # Manual source scout signal (/scoutnow)
        try:
            if kv_get("force_scout_run"):
                kv_set("force_scout_run", "")
                log.info("Force scout run signalled — running source scout now")
                run_source_scout()
        except Exception as e:
            log.error("Forced scout run failed: %s", e)

        # Manual story-tracker signal (command center "Run now")
        try:
            if kv_get("force_tracker_run"):
                kv_set("force_tracker_run", "")
                log.info("Force story-tracker signalled")
                run_story_tracker()
        except Exception as e:
            log.error("Forced tracker run failed: %s", e)

        # Manual meta-synthesis signal (command center "Run now")
        try:
            if kv_get("force_meta_run"):
                kv_set("force_meta_run", "")
                log.info("Force meta-synthesis signalled")
                run_meta_synthesis()
        except Exception as e:
            log.error("Forced meta run failed: %s", e)

        # Targeted dig signal (/dig [theme]) — story-scout on that theme now
        try:
            dig_theme = kv_get("dig_request")
            if dig_theme:
                kv_set("dig_request", "")
                log.info("Dig signalled — running targeted story scout: %s", dig_theme)
                run_story_scout(theme_hint=dig_theme)
        except Exception as e:
            log.error("Targeted dig failed: %s", e)

        # Persistent dig — manual advance signal (dashboard/bot button)
        try:
            adv_id = kv_get("advance_dig_id")
            if adv_id:
                kv_set("advance_dig_id", "")
                log.info("Advancing dig #%s (signalled)", adv_id)
                run_dig_advance(int(adv_id))
        except Exception as e:
            log.error("Manual dig advance failed: %s", e)

        # Persistent dig — manual promote signal (dashboard/bot button)
        try:
            promo_id = kv_get("promote_dig_id")
            if promo_id:
                kv_set("promote_dig_id", "")
                log.info("Promoting dig #%s (signalled)", promo_id)
                promote_dig(int(promo_id))
        except Exception as e:
            log.error("Manual dig promote failed: %s", e)

        # Persistent digs — daily auto-advance of due threads (next_action_at passed).
        # One per tick to keep model cost bounded; the rest wait for the next tick.
        try:
            last_dig = kv_get("last_dig_sweep_at")
            dig_due = (not last_dig) or (now_utc - datetime.fromisoformat(last_dig)).total_seconds() >= 6 * 3600
            if dig_due:
                due = get_due_digs(limit=1)
                if due:
                    kv_set("last_dig_sweep_at", now_utc.isoformat())
                    log.info("Auto-advancing due dig #%s", due[0]["id"])
                    run_dig_advance(due[0]["id"])
        except Exception as e:
            log.error("Auto dig advance failed: %s", e)

        # Chief of staff — manual signal (dashboard/bot "Run now").
        try:
            if kv_get("run_chief_of_staff"):
                kv_set("run_chief_of_staff", "")
                log.info("Chief-of-staff sweep signalled")
                run_chief_of_staff()
        except Exception as e:
            log.error("Chief-of-staff (manual) failed: %s", e)

        # Chief of staff — daily proactive backlog sweep.
        try:
            last_cos = kv_get("last_cos_at")
            cos_due = (not last_cos) or (now_utc - datetime.fromisoformat(last_cos)).total_seconds() >= 24 * 3600
            if cos_due:
                # Stamp BEFORE running so a mid-way failure can't retry-storm the
                # sweep (and its web-search cost) every 2 min. run_chief_of_staff
                # re-stamps on success.
                kv_set("last_cos_at", now_utc.isoformat())
                run_chief_of_staff()
        except Exception as e:
            log.error("Chief-of-staff (daily) failed: %s", e)

        # Owner topics — check every 2 minutes, run immediately if queued
        try:
            pending = pop_next_topic()
            if pending:
                log.info("Owner topic found: %s", pending["topic"][:80])
                from engine.agents.orchestrator import _run_topic_intake
                _run_topic_intake(pending)
            else:
                # RSS cycle — on schedule or when /runnow signals it
                force = kv_get("force_rss_run")
                interval_h = int(kv_get("check_interval_hours") or CHECK_INTERVAL_HOURS)
                due = _last_rss_run is None or (now_utc - _last_rss_run).total_seconds() >= interval_h * 3600
                if due or force:
                    if force:
                        kv_set("force_rss_run", "")
                    try:
                        run_daily_cycle()
                        _last_rss_run = now_utc
                    except Exception as e:
                        # Stamp on failure too, backdated so the retry comes in
                        # RSS_RETRY_MINUTES rather than on the very next tick.
                        # Without this a persistent failure re-ran every 2 minutes
                        # forever (2026-07-21: 22 hours of it).
                        _last_rss_run = (now_utc
                                         - timedelta(hours=interval_h)
                                         + timedelta(minutes=RSS_RETRY_MINUTES))
                        log.error("RSS cycle failed (retrying in ~%dm): %s",
                                  RSS_RETRY_MINUTES, e, exc_info=True)
        except Exception as e:
            log.error("Topic check failed: %s", e, exc_info=True)

        # Idle alert — if no RSS cycle has completed in >8h, ping once per 12h
        try:
            last_cycle = kv_get("last_cycle_at")
            last_alert = kv_get("last_idle_alert_at")
            if last_cycle:
                idle_secs = (now_utc - datetime.fromisoformat(last_cycle)).total_seconds()
                alerted_recently = last_alert and (now_utc - datetime.fromisoformat(last_alert)).total_seconds() < 12 * 3600
                if idle_secs > 8 * 3600 and not alerted_recently:
                    kv_set("last_idle_alert_at", now_utc.isoformat())
                    idle_h = int(idle_secs / 3600)
                    _tg_notify(
                        f"⚠️ Thelivu has been idle for {idle_h}h — no cycle completed since "
                        f"{last_cycle[:16]} UTC.\n\nCheck Railway logs or use /runnow to trigger a cycle."
                    )
        except Exception as e:
            log.error("Idle check failed: %s", e)

        log.info("Sleeping %ds...", TOPIC_POLL_SECONDS)
        time.sleep(TOPIC_POLL_SECONDS)

else:
    from thelivu_bot.bot import main
    main()
