"""Transient-failure retry for the free NVIDIA endpoints.

Three places call NVIDIA — the reel's video-script (`publishing/make_reel.py`), the
per-beat illustrations (`publishing/illustrate.py`), and the shared presentation-skill
runner (`engine/agents/skill_runner.py`). The free tier 500s under load and cold-starts
for minutes, so all three need the same retry, which means it belongs here rather than
being written three times and drifting (the same anti-drift rule as `shared/costs.py`).

The transient/hard split is the one the engine already draws for the paid providers in
`shared/quota.py`: 5xx, timeouts and dropped connections are worth another go; a 4xx —
bad key, unknown model, malformed request — is our bug, and retrying it only wastes
minutes on a request that cannot succeed.

This deliberately does NOT touch the quota breaker. NVIDIA has its own key and its own
free quota; a failure here must never park the paid Anthropic/Gemini pipeline.
"""
import logging
import time

log = logging.getLogger("nvidia")

TRIES = 3
BACKOFF_SECS = 20


class NvidiaUnavailable(RuntimeError):
    """Every attempt hit a transient failure — the endpoint is down, not misused."""


def call_with_retry(fn, *, what="nvidia call", tries=None, backoff=None,
                    sleep=time.sleep):
    """Run `fn()`, retrying only transient failures. Returns fn()'s value.

    `fn` must perform the request AND raise on a bad status (`raise_for_status`), so
    that a 5xx arrives here as an HTTPError rather than as a success with a junk body.
    Raises NvidiaUnavailable when the bound is exhausted; re-raises anything
    non-transient immediately.

    `tries`/`backoff` default to the module constants read AT CALL TIME, not bound as
    argument defaults — otherwise a test (or an operator) setting
    `shared.nvidia.BACKOFF_SECS = 0` would have no effect and every retry test would
    really sleep 20s.
    """
    import requests

    tries = TRIES if tries is None else tries
    backoff = BACKOFF_SECS if backoff is None else backoff
    last = None
    for attempt in range(max(int(tries), 1)):
        try:
            return fn()
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", 0) < 500:
                raise
            last = e
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
        if attempt + 1 < tries:
            wait = backoff * (attempt + 1)
            log.warning("%s: transient failure (try %d/%d): %s — retrying in %ds",
                        what, attempt + 1, tries, last, wait)
            sleep(wait)
    raise NvidiaUnavailable(f"{what} failed {tries}x (last: {last})")
