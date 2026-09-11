"""Keeping the Instagram token alive.

The token expired on 2026-09-10 and everything that touches Instagram — the
insights sweep, carousel publishing, reel posting — failed until a human
re-issued it by hand. Nothing in the codebase refreshed it, so that was always
going to happen, roughly every sixty days, forever.

Meta's "Instagram API with Instagram Login" issues **long-lived tokens valid for
60 days**, and exposes an endpoint that trades a valid one for a fresh 60-day
token:

    GET graph.instagram.com/refresh_access_token
        ?grant_type=ig_refresh_token&access_token=<current>

Two constraints shape everything here:

  1. **The token must still be valid to refresh it.** Once it expires there is
     no recovery path but the full OAuth flow, by hand, by Anil. So refreshing
     must happen well before the deadline, not near it — this refreshes at 30
     days, leaving a 30-day margin in which several attempts can fail harmlessly.
  2. **A token must be at least 24 hours old** before Meta will refresh it.

## Where the refreshed token lives

Not in the environment — the process cannot write its own Railway variable, and
a token that only exists in memory dies with the dyno. So `IG_ACCESS_TOKEN` is
treated as a **seed**: the first value, set by hand. After the first refresh the
live token lives in `kv_store`, and `current_token()` prefers it.

That has a consequence worth stating plainly: rotating the Railway variable no
longer changes what the app uses, unless the stored token is cleared too.
`seed_from_env()` handles that by noticing when the env value differs from the
seed it recorded, which is exactly what happens when Anil pastes a new one after
an expiry.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger("ig_token")

REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
TIMEOUT = 20

TOKEN_KEY = "ig_access_token"          # the live token
SEED_KEY = "ig_access_token_seed"      # the env value we last adopted
ISSUED_KEY = "ig_access_token_issued"  # when the live token was issued

LIFETIME_DAYS = 60
# Refresh at half-life. Meta requires the token to be valid at refresh time, so
# the margin is the whole safety story: at 30 days a failed attempt can be
# retried daily for a month before anything breaks.
REFRESH_AFTER_DAYS = 30
# Meta refuses to refresh a token younger than this.
MIN_AGE_HOURS = 24


def _now():
    return datetime.now(timezone.utc)


def seed_from_env():
    """Adopt IG_ACCESS_TOKEN from the environment when it is new.

    Called before every read. It is what makes a hand-pasted replacement take
    effect: after an expiry Anil sets a fresh value in Railway, and without this
    the stored (dead) token would keep winning forever.
    """
    from shared.db import kv_get, kv_set
    env = (os.environ.get("IG_ACCESS_TOKEN") or "").strip()
    if not env:
        return
    if kv_get(SEED_KEY) == env and kv_get(TOKEN_KEY):
        return
    kv_set(SEED_KEY, env)
    kv_set(TOKEN_KEY, env)
    kv_set(ISSUED_KEY, _now().isoformat())
    log.info("adopted a new IG token from the environment")


def current_token():
    """The token to use. Stored value wins; the environment seeds it."""
    from shared.db import kv_get
    try:
        seed_from_env()
        return (kv_get(TOKEN_KEY) or os.environ.get("IG_ACCESS_TOKEN") or "").strip()
    except Exception:
        # A DB problem must never take Instagram down — fall back to the env.
        return (os.environ.get("IG_ACCESS_TOKEN") or "").strip()


def age_days():
    """How old the live token is, or None if unknown."""
    from shared.db import kv_get
    raw = kv_get(ISSUED_KEY)
    if not raw:
        return None
    try:
        return (_now() - datetime.fromisoformat(raw)).total_seconds() / 86400.0
    except Exception:
        return None


def days_remaining():
    age = age_days()
    return None if age is None else max(0.0, LIFETIME_DAYS - age)


def refresh_due():
    """(due, why). Unknown age counts as due: a token we cannot date is one we
    cannot promise is fresh, and refreshing early is free."""
    age = age_days()
    if age is None:
        return True, "token age unknown"
    if age < MIN_AGE_HOURS / 24.0:
        return False, f"only {age*24:.0f}h old; Meta refuses to refresh under 24h"
    if age >= REFRESH_AFTER_DAYS:
        return True, f"{age:.0f} days old, past the {REFRESH_AFTER_DAYS}-day half-life"
    return False, f"{age:.0f} days old; refreshes at {REFRESH_AFTER_DAYS}"


def refresh(force=False):
    """Exchange the current token for a fresh 60-day one. Returns a status str."""
    from shared.db import kv_get, kv_set
    token = current_token()
    if not token:
        return "no IG token configured"

    due, why = refresh_due()
    if not due and not force:
        return f"not due: {why}"

    import requests
    try:
        r = requests.get(REFRESH_URL, timeout=TIMEOUT, params={
            "grant_type": "ig_refresh_token", "access_token": token})
    except Exception as e:
        return f"refresh request failed: {type(e).__name__}: {e}"

    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", r.text)[:180]
        except Exception:
            msg = r.text[:180]
        # Worth being loud about: if this is an expiry, no automated path
        # recovers it and only a human re-issue will.
        return f"refresh rejected ({r.status_code}): {msg}"

    body = r.json()
    new_token = (body.get("access_token") or "").strip()
    if not new_token:
        return f"refresh returned no token: {str(body)[:160]}"

    kv_set(TOKEN_KEY, new_token)
    kv_set(ISSUED_KEY, _now().isoformat())
    expires_in = int(body.get("expires_in") or 0)
    return (f"refreshed; valid for {expires_in // 86400 if expires_in else LIFETIME_DAYS} days")


def status():
    """One line for the command centre."""
    tok = current_token()
    if not tok:
        return "IG token: not configured"
    rem = days_remaining()
    if rem is None:
        return "IG token: present, age unknown (will refresh on the next sweep)"
    due, why = refresh_due()
    return (f"IG token: ~{rem:.0f} days remaining"
            + (f" — refresh due ({why})" if due else ""))
