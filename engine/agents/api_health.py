"""Proactive checks for every external API this project depends on that
model_health.py and illustration_health.py don't already cover.

Added 2026-09-06, at Anil's ask ("are all the apis working? that is a check
we should run periodically") while diagnosing the 2026-09-02 pause. A manual
sweep that day found two real, silent gaps: the YouTube refresh token had
expired (Testing-mode OAuth tokens die after 7 days — see docs/HANDOFF.md
§4a) and nobody would have noticed until a cross-post failed; and the
Cloudflare illustration fallback (already covered by illustration_health.py)
had no credentials on Railway at all. Neither surfaces until the thing it
backs is actually needed — same blind spot illustration_health.py names in
its own docstring, just for a different set of dependencies.

Covers: Anthropic (Claude), Gemini, Telegram Bot API, Instagram Graph API,
YouTube (refresh-token liveness). Deliberately does NOT re-check NVIDIA
models or illustration providers — model_health.py and illustration_health.py
already own those; this module exists for everything they don't.

Claude/Gemini pings are genuinely paid calls — model_health.py's own
docstring flagged this exact tradeoff as "a real design decision worth its
own call, not a reflexive extension of this file." That call, made here:
`max_tokens=5` on the cheapest current tier of each (Claude Haiku, Gemini
Flash) is a fraction of a cent per ping; at this module's own 6h cadence
that's ~4 pings/day/provider, negligible against the shared daily budget
governor (shared/budget.py) this project is otherwise careful about. If a
future model swap ever makes the cheap tier meaningfully pricier, revisit
the cadence, not the principle.

Lives ABOVE the budget governor in run.py, same placement and reasoning as
model_health.py/illustration_health.py: these are near-free liveness checks,
not the paid stages the governor exists to park, and they need to keep
watching exactly when those paid stages are busiest.
"""
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("api-health")

SWEEP_HOURS = 6
LAST_SYNC_KEY = "last_api_health_at"
LAST_RESULT_KEY = "last_api_health_result"
FORCE_KEY = "force_api_health_check"
TIMEOUT = 15
PING_MAX_TOKENS = 5


def _ping_claude():
    import os
    try:
        import anthropic
        t0 = time.time()
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        client.messages.create(model="claude-haiku-4-5", max_tokens=PING_MAX_TOKENS,
                                messages=[{"role": "user", "content": "Say OK."}])
        return True, time.time() - t0, None
    except Exception as e:
        return False, 0.0, f"{type(e).__name__}: {str(e)[:200]}"


def _ping_gemini():
    import os
    try:
        from google import genai
        t0 = time.time()
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
        client.models.generate_content(model="gemini-2.5-flash", contents="Say OK.")
        return True, time.time() - t0, None
    except Exception as e:
        return False, 0.0, f"{type(e).__name__}: {str(e)[:200]}"


def _ping_telegram():
    import os, requests
    try:
        t0 = time.time()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=TIMEOUT)
        ok = r.status_code == 200 and r.json().get("ok", False)
        return ok, time.time() - t0, (None if ok else f"{r.status_code}: {r.text[:200]}")
    except Exception as e:
        return False, 0.0, f"{type(e).__name__}: {str(e)[:200]}"


def _ping_instagram():
    """The channel Telegram/reels post through — same graph.instagram.com
    host as publishing/instagram.py (NOT graph.facebook.com, see
    docs/HANDOFF.md §5.11)."""
    import os, requests
    try:
        t0 = time.time()
        ig_user = os.environ.get("IG_USER_ID", "")
        token = os.environ.get("IG_ACCESS_TOKEN", "")
        r = requests.get(f"https://graph.instagram.com/{ig_user}",
                          params={"fields": "id", "access_token": token}, timeout=TIMEOUT)
        ok = r.status_code == 200
        return ok, time.time() - t0, (None if ok else f"{r.status_code}: {r.text[:200]}")
    except Exception as e:
        return False, 0.0, f"{type(e).__name__}: {str(e)[:200]}"


def _ping_youtube():
    """Checks the refresh token still exchanges for an access token — the
    actual failure mode that bit us (Testing-mode OAuth consent expires it
    every 7 days, docs/HANDOFF.md §4a). Skips cleanly, not a failure, if
    YouTube cross-posting was never configured."""
    import os, requests
    cid = os.environ.get("YOUTUBE_CLIENT_ID", "")
    if not cid:
        return None, 0.0, "not configured"
    try:
        t0 = time.time()
        r = requests.post("https://oauth2.googleapis.com/token", timeout=TIMEOUT, data={
            "client_id": cid,
            "client_secret": os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
            "refresh_token": os.environ.get("YOUTUBE_REFRESH_TOKEN", ""),
            "grant_type": "refresh_token",
        })
        ok = r.status_code == 200
        detail = None if ok else f"{r.status_code}: {r.text[:200]}"
        return ok, time.time() - t0, detail
    except Exception as e:
        return False, 0.0, f"{type(e).__name__}: {str(e)[:200]}"


_CHECKS = [
    ("claude", _ping_claude),
    ("gemini", _ping_gemini),
    ("telegram-bot", _ping_telegram),
    ("instagram-graph", _ping_instagram),
    ("youtube-oauth", _ping_youtube),
]


def run_health_check():
    """Ping every API above, snapshot each into model_health_checks (same
    table model_health.py/illustration_health.py use — same trend data, same
    Command Center dashboard, just more rows), alert once per API per failed
    streak. Never raises — a failed ping IS the result."""
    from shared.db import add_model_health_check, kv_get, kv_set

    results = []
    for name, fn in _CHECKS:
        ok, latency, error = fn()
        if ok is None:
            results.append((name, None, 0.0, error))
            continue  # not configured — nothing to snapshot or alert on
        add_model_health_check(name, ok, latency_s=round(latency, 2), error=error)
        results.append((name, ok, latency, error))

        alert_key = f"api_health_alerted_{name}"
        if not ok:
            if not kv_get(alert_key):
                kv_set(alert_key, "1")
                _alert(name, error)
        else:
            kv_set(alert_key, "")  # recovered — re-arm for next time

    summary = ", ".join(
        "(skip) " + name if ok is None else
        f"{name}: {'ok' if ok else 'FAIL'} {latency:.1f}s"
        for name, ok, latency, _err in results)
    kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
    kv_set(LAST_RESULT_KEY, summary[:300])
    log.info("api health: %s", summary)
    return summary


def _alert(name, error):
    """Best-effort Telegram push — same pattern as model_health.py/
    illustration_health.py, reusing the engine's own notifier."""
    try:
        from engine.agents.orchestrator import _notify
        _notify(f"⚠️ API check failed: {name} — {error}. Whatever depends on "
                f"this will fail until it clears.")
    except Exception as e:
        log.warning("could not send api-health alert: %s", e)


def sync_due(now_utc):
    from datetime import timedelta
    from shared.db import kv_get

    raw = kv_get(LAST_SYNC_KEY)
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last - now_utc > timedelta(hours=1):
        return True
    return (now_utc - last).total_seconds() >= SWEEP_HOURS * 3600
