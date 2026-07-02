import os

service = os.environ.get("RAILWAY_SERVICE_NAME", "thelivu")

if service == "thelivu-agent":
    from engine.agents.orchestrator import run_daily_cycle, process_recheck_requests, send_cost_report, run_source_scout, run_story_scout, run_story_tracker, run_meta_synthesis, _cost_report_due
    import time, logging, sys
    from datetime import datetime, timezone, timedelta
    from shared.config import ANTHROPIC_API_KEY, APPROVAL_MODE, TELEGRAM_BOT_TOKEN, TELEGRAM_DRAFT_CHAT_ID, CHECK_INTERVAL_HOURS
    from shared.db import init_db, kv_get, kv_set, update_run

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
    log = logging.getLogger("orchestrator")

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set."); sys.exit(1)
    if APPROVAL_MODE == "telegram" and (not TELEGRAM_BOT_TOKEN or not TELEGRAM_DRAFT_CHAT_ID):
        log.error("APPROVAL_MODE=telegram but Telegram vars not set."); sys.exit(1)

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
    TOPIC_POLL_SECONDS = 120  # check for owner topics every 2 minutes

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

        # Manual source scout signal (/scoutnow)
        try:
            if kv_get("force_scout_run"):
                kv_set("force_scout_run", "")
                log.info("Force scout run signalled — running source scout now")
                run_source_scout()
        except Exception as e:
            log.error("Forced scout run failed: %s", e)

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
                        log.error("RSS cycle failed: %s", e, exc_info=True)
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
