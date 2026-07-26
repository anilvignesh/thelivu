"""Password gate → signed HttpOnly cookie.

Same rule as the Streamlit era: DASHBOARD_PASSWORD must be set or the app
refuses to start. The signing secret is per-process (restart = re-login —
acceptable for a single-owner tool, and it means no secret at rest).
"""
import hashlib
import hmac
import os
import secrets
import time

COOKIE = "cc_session"
_SECRET = secrets.token_bytes(32)
_MAX_AGE = 30 * 24 * 3600  # 30 days — it's his own laptop + Tailscale


def password_ok(pw):
    expected = os.environ.get("DASHBOARD_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(pw or "", expected)


def make_token():
    ts = str(int(time.time()))
    sig = hmac.new(_SECRET, ts.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def token_ok(token):
    if not token or "." not in token:
        return False
    ts, sig = token.split(".", 1)
    good = hmac.new(_SECRET, ts.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return (time.time() - int(ts)) < _MAX_AGE
    except ValueError:
        return False
