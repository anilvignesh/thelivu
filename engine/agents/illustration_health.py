"""Proactive illustration-provider health checks — same principle as
model_health.py ("check proactively, don't wait for a real failure"), applied
to the class of bug that principle didn't cover: an image-generation provider
that's broken in a way that never surfaces until the OTHER provider is also
down.

Added 2026-09-02, diagnosed the same day: the Cloudflare Workers AI fallback
(publishing/illustrate.py, added 2026-08-29 for FLUX outages) had been
rejected on 100% of calls since it shipped — Cloudflare's REST endpoint
rejects the `seed` parameter outright, contrary to its own docs — and nobody
noticed for 3+ days, because it's ONLY ever invoked when FLUX has already
failed. A broken fallback is invisible exactly when you need it, which is the
opposite of model_health.py's failure mode (a slow/dead model shows up in
every reel immediately). This module tests each illustration provider
independently and on its own schedule, not conditional on the other having
failed first — that's the whole point.

Deliberately NOT reusing model_health.py's ping_model() — that's a text-
completion ping against NVIDIA's chat endpoint; this needs a real (tiny,
cheap) image generation call against each provider's actual illustration
endpoint, since the Cloudflare bug was specifically a request-shape mismatch
that a generic health check would never have caught. Logs into the same
model_health_checks table (shared.db.add_model_health_check) — same trend
data, same dashboard, just a different kind of "model" name.
"""
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("illustration-health")

SWEEP_HOURS = 6
LAST_SYNC_KEY = "last_illustration_health_at"
LAST_RESULT_KEY = "last_illustration_health_result"
FORCE_KEY = "force_illustration_health_check"
TIMEOUT = 45
_TEST_PROMPT = "a simple wooden chair in a plain room, warm lighting"


def _ping_flux_nvidia():
    """One real (cheap: 10 steps) FLUX.1-dev call against NVIDIA's endpoint —
    same one publishing/illustrate.py actually uses. Returns (ok, latency_s,
    error)."""
    import os, requests
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        return None, None, "NVIDIA_API_KEY not set"
    t0 = time.time()
    try:
        r = requests.post(
            "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
            headers={"Authorization": f"Bearer {key}"},
            json={"prompt": _TEST_PROMPT, "cfg_scale": 5, "seed": 0, "steps": 10},
            timeout=TIMEOUT,
        )
        latency = time.time() - t0
        if r.status_code != 200:
            return False, latency, f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        if not (body.get("artifacts") and body["artifacts"][0].get("base64")):
            return False, latency, "200 OK but no image data in response"
        return True, latency, None
    except Exception as e:
        return False, time.time() - t0, f"{type(e).__name__}: {str(e)[:200]}"


def _ping_cloudflare():
    """One real flux-1-schnell call against Cloudflare's actual REST endpoint
    — the exact request shape publishing/illustrate.py sends (this is
    precisely the check that would have caught the seed-param bug on day
    one). Returns (ok, latency_s, error), or (None, None, reason) when not
    configured — same "nothing to check" shape as model_health.py's missing-
    key case, not a failure."""
    import os, requests
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not (account and token):
        return None, None, "CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID not set"
    t0 = time.time()
    try:
        r = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/"
            f"@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {token}"},
            json={"prompt": _TEST_PROMPT, "steps": 8},
            timeout=TIMEOUT,
        )
        latency = time.time() - t0
        if r.status_code != 200:
            return False, latency, f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        if not (body.get("result") or {}).get("image"):
            return False, latency, "200 OK but no image data in response"
        return True, latency, None
    except Exception as e:
        return False, time.time() - t0, f"{type(e).__name__}: {str(e)[:200]}"


def run_health_check():
    """Test both illustration providers independently, log each, alert once
    per provider per broken streak (same one-shot-then-quiet pattern as
    model_health.py, so a sustained outage doesn't spam). Returns a summary
    string. Never raises."""
    from shared.db import add_model_health_check, kv_get, kv_set

    checks = [("flux.1-dev (nvidia, primary)", _ping_flux_nvidia),
              ("flux-1-schnell (cloudflare, fallback)", _ping_cloudflare)]

    results = []
    for label, fn in checks:
        ok, latency, error = fn()
        if ok is None:
            # Not configured — nothing to check, not a failure. Don't log a
            # None into a boolean column or alert on it.
            results.append((label, None, None, error))
            continue
        add_model_health_check(label, ok, latency_s=(round(latency, 2) if latency else None),
                               error=error)
        results.append((label, ok, latency, error))

        alert_key = f"illustration_health_alerted_{label}"
        if not ok:
            if not kv_get(alert_key):
                kv_set(alert_key, "1")
                _alert(label, error)
        else:
            kv_set(alert_key, "")  # recovered — re-arm for next time

    summary = ", ".join(
        f"{label}: not configured" if ok is None else
        f"{label}: {'ok' if ok else 'FAIL'} {latency:.1f}s"
        for label, ok, latency, _err in results
    )
    kv_set(LAST_SYNC_KEY, datetime.now(timezone.utc).isoformat())
    kv_set(LAST_RESULT_KEY, summary[:300])
    log.info("illustration health: %s", summary)
    return summary


def _alert(label, error):
    """Best-effort Telegram push, same reasoning as model_health.py's."""
    try:
        from engine.agents.orchestrator import _notify
        _notify(f"⚠️ Illustration provider broken: {label} — {error}. "
                f"If this is the fallback, it means reels will silently drop "
                f"to text-slide the next time the primary provider fails too "
                f"— worth fixing before that happens, not after.")
    except Exception as e:
        log.warning("could not send illustration-health alert: %s", e)


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
