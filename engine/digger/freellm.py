"""Client for the local freellmapi instance.

freellmapi runs on the SAME box as the digger, bound to 127.0.0.1:3001 — it is
deliberately not reachable from the internet, so this client never needs to
handle auth beyond the local unified key.

Cost isolation (docs/plans/07-tier0-digger.md): this module imports nothing from
shared/budget.py. Tier 0 is free-tier by definition, and a free-provider outage
must not trip the $3/day cap that guards real Claude/Gemini spend.
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:3001"

# Two DIFFERENT families on purpose. The cross-check is only worth anything if
# the second reader can fail differently from the first — running the same model
# twice mostly reproduces its own mistakes.
#
# These two were picked by measurement on 2026-09-10, not by reputation. Against
# a fixed audit-document fixture:
#   gemini-3.5-flash-lite  1.3s  2/2 grounded findings   (Google)
#   command-a              2.5s  2/2 grounded findings   (Cohere)
#   mistral-small-4        HTTP 429 rate-limited
#   llama-4-maverick       HTTP 503 no configured route
#   gemma-4-26b-it         HTTP 502 upstream failure
#
# Do NOT default these to "auto": auto routed to nemotron-3-ultra, a reasoning
# model that returns its chain-of-thought in `content` ("The user wants a
# summary of...") instead of the answer, which fails JSON parsing every time and
# took 44s on a 6k-char prompt. Reasoning models are the wrong tool for
# structured extraction.
MODEL_A = os.environ.get("DIGGER_MODEL_A", "gemini-3.5-flash-lite")
MODEL_B = os.environ.get("DIGGER_MODEL_B", "command-a")
# Free-tier providers rate-limit and 503 constantly, so a named model that is
# unavailable right now falls back to freellmapi's own routing rather than
# losing the cycle.
FALLBACK_MODEL = os.environ.get("DIGGER_FALLBACK_MODEL", "auto")


class FreeLLMError(RuntimeError):
    pass


def base_url():
    return os.environ.get("FREELLMAPI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def api_key():
    key = os.environ.get("FREELLMAPI_KEY", "")
    if not key:
        raise FreeLLMError(
            "FREELLMAPI_KEY is not set. It is freellmapi's unified API key — on "
            "the digger VM, ops/oracle-vm/deploy-digger.sh reads it out of the "
            "freellmapi container's settings table and writes it to digger.env."
        )
    return key


def complete(prompt, model=None, max_tokens=800, temperature=0.0, timeout=90):
    """One chat completion. Returns the assistant text.

    temperature defaults to 0: every use in this package is extraction from a
    supplied document, where sampling variety is a liability, not a feature.
    """
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if model and model != "auto":
        payload["model"] = model

    req = urllib.request.Request(
        f"{base_url()}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise FreeLLMError(f"freellmapi HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FreeLLMError(f"freellmapi unreachable at {base_url()}: {e}") from e

    choices = body.get("choices") or []
    if not choices:
        raise FreeLLMError(f"freellmapi returned no choices: {str(body)[:300]}")
    msg = choices[0].get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        # Some free models put everything in reasoning_content and leave content
        # empty — seen live on nemotron. Treat that as a miss rather than
        # silently recording an empty finding.
        raise FreeLLMError("freellmapi returned an empty completion")
    return text


def routed_model(response_json):
    """freellmapi reports which provider/model actually served a request in
    `_routed_via` — worth recording, since 'auto' says nothing by itself."""
    via = (response_json or {}).get("_routed_via") or {}
    return via.get("model") or (response_json or {}).get("model") or "unknown"


def ping(timeout=10):
    try:
        with urllib.request.urlopen(f"{base_url()}/api/ping", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("status") == "ok"
    except Exception:
        return False
