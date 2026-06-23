import os

service = os.environ.get("RAILWAY_SERVICE_NAME", "thelivu")

if service == "thelivu-agent":
    from engine.agents.orchestrator import run_daily_cycle, retry_held, send_cost_report, run_source_scout
    import time, logging, sys
    from datetime import datetime, timezone, timedelta
    from shared.config import ANTHROPIC_API_KEY, APPROVAL_MODE, TELEGRAM_BOT_TOKEN, TELEGRAM_DRAFT_CHAT_ID, CHECK_INTERVAL_HOURS
    from shared.db import init_db, kv_get, kv_set

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
    log = logging.getLogger("orchestrator")

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set."); sys.exit(1)
    if APPROVAL_MODE == "telegram" and (not TELEGRAM_BOT_TOKEN or not TELEGRAM_DRAFT_CHAT_ID):
        log.error("APPROVAL_MODE=telegram but Telegram vars not set."); sys.exit(1)

    init_db()
    log.info("Thelivu agent starting | Approval: %s | Interval: %dh", APPROVAL_MODE, CHECK_INTERVAL_HOURS)

    _cost_report_sent_date = None

    while True:
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()

        if now_utc.hour == 14 and now_utc.minute >= 30 and _cost_report_sent_date != today:
            try:
                send_cost_report()
                _cost_report_sent_date = today
            except Exception as e:
                log.error("Cost report failed: %s", e)

        try:
            last_scout = kv_get("last_scout_at")
            if not last_scout or (now_utc - datetime.fromisoformat(last_scout)).days >= 7:
                run_source_scout()
        except Exception as e:
            log.error("Source scout failed: %s", e)

        try:
            run_daily_cycle()
            retry_held()
        except Exception as e:
            log.error("Cycle failed: %s", e, exc_info=True)

        log.info("Sleeping %dh until next cycle...", CHECK_INTERVAL_HOURS)
        time.sleep(CHECK_INTERVAL_HOURS * 3600)

else:
    from thelivu_bot.bot import main
    main()
