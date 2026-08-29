"""Nemotron 3.5 Content Safety guardrail -- a policy-violation check (hate,
harassment, violence, self-harm, sexual content, etc.), NOT a defamation/legal
check. Free, fast NVIDIA-hosted guardrail model at the same
integrate.api.nvidia.com endpoint already used by publishing/belief_reel.py
and engine/agents/model_health.py.

Added 2026-08-29 (Anil: "yea sure", after discussing openrouter.ai/models's
free list). Explicitly NOT a replacement for the LEGAL-FLAG/defamation gate
that engine/distribution/sweep.py removed the same day -- that was a
deliberate, informed, separate decision (see that module's docstring) and
this does not reinstate any part of it. This only catches the different,
narrower class of thing a content-safety guardrail catches: material that
would get the account flagged/banned on policy grounds, not material that
exposes Anil to a defamation suit.

Verified against the live endpoint before shipping (2026-08-29): sends the
piece as a single user message (the NIM injects its own safety taxonomy
system prompt server-side -- do not add one here, it already accounts for
~480 prompt tokens on a one-sentence input) and returns a bare
"User Safety: safe" or "User Safety: unsafe", nothing else in the basic
single-turn mode this module uses.
"""
import logging
import os

log = logging.getLogger("content_safety")

_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_MODEL = os.environ.get("NVIDIA_CONTENT_SAFETY_MODEL", "nvidia/nemotron-3.5-content-safety")
# Article bodies run ~110-210 words per engine/skills/video-script/SKILL.md's
# own target; this is a generous cap against a runaway draft, not a real limit.
_MAX_CHARS = 6000


def check(text, *, timeout=20):
    """True if `text` reads as safe, False if flagged unsafe, None if the
    check itself failed (no key, network error, or an unparseable response).

    Fail-closed by contract: None means "not clear," never "safe by
    default" -- same philosophy as the (now-removed) legal-flag gate this
    module sits beside. Callers must treat None as ineligible for
    autopublish, not wave it through."""
    from shared.config import NVIDIA_API_KEY
    if not NVIDIA_API_KEY:
        return None
    body = (text or "").strip()
    if not body:
        return None
    try:
        import requests
        from shared.nvidia import call_with_retry

        def _post():
            r = requests.post(
                _URL,
                headers={"Authorization": f"Bearer {NVIDIA_API_KEY}"},
                json={"model": _MODEL,
                      "messages": [{"role": "user", "content": body[:_MAX_CHARS]}],
                      "max_tokens": 50},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()

        raw = call_with_retry(_post, what="content safety check")
    except Exception as e:
        log.warning("content safety check failed (%s) -- treating as unclear", e)
        return None

    low = raw.lower()
    if "unsafe" in low:
        return False
    if "safe" in low:
        return True
    log.warning("content safety check returned an unparseable verdict: %r", raw)
    return None
