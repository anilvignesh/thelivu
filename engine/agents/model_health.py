"""Proactive model health checks — the piece that would have caught
2026-08-17's stuck-reel incident BEFORE a real render failed, not after.

Yesterday's failure mode: google/gemma-4-31b-it quietly went from fine to
17.8s-for-two-words on NVIDIA's free tier, with nothing watching for that
until a real video-script generation kept blowing its 300s retry timeout.
Same class of problem as the reel-worker stuck-alert (publishing/
reel_worker.py) — a real failure had to happen first because nothing checked
proactively. This module is the "check proactively" half.

Deliberately NVIDIA-only for now, not Claude/Gemini too: NVIDIA's free tier is
the demonstrated flaky one (twice now — the video-script timeouts, and the
belief-caption call that read-timed-out at 120s during today's head-to-head
test), and pinging it costs nothing. Claude/Gemini are paid, and a proactive
ping on every sweep would compete with the same tight shared daily budget
this whole project is careful about — if those ever need the same treatment,
that's a real design decision (a ping costs real money) worth its own call,
not a reflexive extension of this file.

Lives ABOVE the budget governor in run.py, same reasoning as ig_insights.py/
yt_insights.py: this is a free HTTP check, not a model call against the paid
quota, and parking it with the paid stages would mean it goes quiet exactly
when the paid stages are busiest — the opposite of when you'd want it to
still be watching.
"""
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("model-health")

SWEEP_HOURS = 6
LAST_SYNC_KEY = "last_model_health_at"
LAST_RESULT_KEY = "last_model_health_result"
FORCE_KEY = "force_model_health_check"
TIMEOUT = 30
PING_MAX_TOKENS = 20

# A trivial ping taking longer than this means the model is having a bad day —
# calibrated against real numbers, not guessed: 0.5s is what a healthy
# nemotron-3.5-lightning ping looked like (2026-08-18), 17.8s is what the
# degraded google/gemma-4-31b-it looked like the day before. This sits well
# clear of normal variance and well under either failure.
DEGRADED_THRESHOLD_S = 8.0


def _configured_models():
    """Every distinct NVIDIA model this project currently points at, read the
    same way the real call sites resolve them — env override first, else the
    module default — so this checks what's ACTUALLY in use, not a hardcoded
    guess that drifts out of sync with a future model swap."""
    import os
    models = set()
    try:
        from publishing.make_reel import _NVIDIA_SCRIPT_MODEL
        models.add(_NVIDIA_SCRIPT_MODEL)
    except Exception as e:
        log.warning("could not resolve video-script model: %s", e)
    try:
        from publishing.belief_reel import _NVIDIA_MODEL
        models.add(_NVIDIA_MODEL)
    except Exception as e:
        log.warning("could not resolve belief-reel model: %s", e)
    return sorted(models)


def ping_model(model, key):
    """One trivial call. Returns (ok, latency_s, error). Never raises — a
    failed ping IS the result, not an exception to propagate."""
    import requests
    t0 = time.time()
    try:
        r = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model,
                  "messages": [{"role": "user", "content": "Say OK in one word."}],
                  "max_tokens": PING_MAX_TOKENS},
            timeout=TIMEOUT,
        )
        latency = time.time() - t0
        if r.status_code != 200:
            return False, latency, f"{r.status_code}: {r.text[:200]}"
        return True, latency, None
    except Exception as e:
        return False, time.time() - t0, f"{type(e).__name__}: {str(e)[:200]}"


def run_health_check():
    """Ping every configured model, snapshot each, alert once per model per
    degraded streak (not every sweep — same one-shot-then-quiet pattern as
    the reel-worker stuck-alert, so this doesn't spam). Returns a summary
    string. Never raises — the caller's try/except is belt-and-braces."""
    import os
    from shared.db import add_model_health_check, kv_get, kv_set

    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        return "NVIDIA_API_KEY not set — nothing to check"

    models = _configured_models()
    if not models:
        return "no NVIDIA models currently configured"

    results = []
    for model in models:
        ok, latency, error = ping_model(model, key)
        add_model_health_check(model, ok, latency_s=round(latency, 2), error=error)
        degraded = (not ok) or (latency > DEGRADED_THRESHOLD_S)
        results.append((model, ok, latency, error, degraded))

        alert_key = f"model_health_alerted_{model}"
        if degraded:
            if not kv_get(alert_key):
                kv_set(alert_key, "1")
                _alert(model, ok, latency, error)
        else:
            kv_set(alert_key, "")  # recovered — re-arm the alert for next time

    summary = ", ".join(
        f"{m}: {'ok' if ok else 'FAIL'} {latency:.1f}s{' [DEGRADED]' if deg else ''}"
        for m, ok, latency, _err, deg in results)
    kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
    kv_set(LAST_RESULT_KEY, summary[:300])
    log.info("model health: %s", summary)
    return summary


def _alert(model, ok, latency, error):
    """Best-effort Telegram push — reuses the engine's own notifier rather
    than reinventing one, since this runs in the same Railway process
    orchestrator.py does (unlike reel_worker.py's standalone VM-only version,
    which has its own minimal notifier for exactly that reason)."""
    try:
        from engine.agents.orchestrator import _notify
        if ok:
            _notify(f"⚠️ Model slow: {model} took {latency:.1f}s for a trivial "
                    f"ping (threshold {DEGRADED_THRESHOLD_S}s). Reels using this "
                    f"model may be slow or time out — heads-up, not urgent unless "
                    f"it stays this way.")
        else:
            _notify(f"⚠️ Model check failed: {model} — {error}. Reels using this "
                    f"model will fail until this clears.")
    except Exception as e:
        log.warning("could not send model-health alert: %s", e)


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
