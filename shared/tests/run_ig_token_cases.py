"""Keeping the Instagram token alive.

    python -m shared.tests.run_ig_token_cases

No network: the refresh HTTP call is stubbed. A throwaway SQLite file, so the
kv persistence is real.

What this is FOR: the token expired on 2026-09-10 and took every Instagram path
down until a human re-issued it, because nothing refreshed it. Meta's
long-lived tokens last 60 days, and a token must still be VALID to refresh —
once it lapses there is no automated recovery at all. So the two things that
must not break are the margin (refresh at 30 days, not 59) and the hand-over
(a token Anil pastes after an expiry must actually take effect).
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from engine.agents import ig_token as t          # noqa: E402
from shared.db import init_db, kv_get, kv_set    # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def _fresh(env_token="SEED-1"):
    init_db()
    for k in (t.TOKEN_KEY, t.SEED_KEY, t.ISSUED_KEY):
        kv_set(k, "")
    if env_token is None:
        os.environ.pop("IG_ACCESS_TOKEN", None)
    else:
        os.environ["IG_ACCESS_TOKEN"] = env_token


def _age(days):
    kv_set(t.ISSUED_KEY, (datetime.now(timezone.utc) - timedelta(days=days)).isoformat())


class _Resp:
    def __init__(self, code=200, payload=None, text=""):
        self.status_code, self._p, self.text = code, payload or {}, text
    def json(self):
        return self._p


def _with_http(resp, fn):
    import requests
    orig = requests.get
    requests.get = lambda *a, **k: resp
    try:
        return fn()
    finally:
        requests.get = orig


# --------------------------------------------------------------------------
# the margin
# --------------------------------------------------------------------------

def t_refresh_happens_at_half_life_not_at_the_deadline():
    """A token must be valid to refresh it; at 30 days a failed attempt can be
    retried daily for a month before anything breaks."""
    _fresh(); t.current_token()
    _age(29); check("not due at 29 days", t.refresh_due()[0], False)
    _age(30); check("due at 30 days", t.refresh_due()[0], True)
    _age(59); check("still due at 59", t.refresh_due()[0], True)


def t_meta_refuses_tokens_under_24h():
    _fresh(); t.current_token()
    _age(0.5)
    due, why = t.refresh_due()
    check("too young to refresh", due, False)
    check("reason names Meta's rule", "24h" in why, True)


def t_unknown_age_counts_as_due():
    """A token we cannot date is one we cannot promise is fresh, and refreshing
    early is free."""
    _fresh(); t.current_token(); kv_set(t.ISSUED_KEY, "")
    check("unknown age is due", t.refresh_due()[0], True)


# --------------------------------------------------------------------------
# the hand-over after an expiry
# --------------------------------------------------------------------------

def t_a_hand_pasted_replacement_takes_effect():
    """After an expiry Anil sets a fresh value in Railway. Without this the
    stored dead token would keep winning forever."""
    _fresh("OLD"); check("seeded", t.current_token(), "OLD")
    os.environ["IG_ACCESS_TOKEN"] = "NEW-AFTER-EXPIRY"
    check("new env value adopted", t.current_token(), "NEW-AFTER-EXPIRY")
    check("age reset with it", round(t.age_days() or 99), 0)


def t_stored_token_wins_over_an_unchanged_env():
    """The refreshed token must not be overwritten by the stale seed on every
    read — that would undo every refresh."""
    _fresh("SEED-1"); t.current_token()
    kv_set(t.TOKEN_KEY, "REFRESHED-BY-META")
    check("stored token preserved", t.current_token(), "REFRESHED-BY-META")


def t_db_failure_falls_back_to_the_environment():
    """A database problem must never take Instagram down."""
    _fresh("ENV-ONLY")
    orig = t.seed_from_env
    t.seed_from_env = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    try:
        check("falls back to env", t.current_token(), "ENV-ONLY")
    finally:
        t.seed_from_env = orig


# --------------------------------------------------------------------------
# refreshing
# --------------------------------------------------------------------------

def t_successful_refresh_stores_the_new_token_and_resets_the_clock():
    _fresh("OLD"); t.current_token(); _age(31)
    out = _with_http(_Resp(200, {"access_token": "FRESH-60D", "expires_in": 5184000}),
                     t.refresh)
    check("reports success", out.startswith("refreshed"), True)
    check("says how long", "60 days" in out, True)
    check("new token stored", t.current_token(), "FRESH-60D")
    check("clock reset", round(t.age_days() or 99), 0)
    check("no longer due", t.refresh_due()[0], False)


def t_a_rejection_does_not_destroy_the_working_token():
    """If Meta refuses, the token we hold may still be good for weeks. Clearing
    it would turn a recoverable state into an outage."""
    _fresh("STILL-GOOD"); t.current_token(); _age(31)
    out = _with_http(_Resp(400, {"error": {"message": "Session has expired"}}), t.refresh)
    check("reports the rejection", out.startswith("refresh rejected"), True)
    check("carries Meta's message", "expired" in out, True)
    check("token untouched", t.current_token(), "STILL-GOOD")


def t_a_network_failure_is_reported_not_swallowed():
    _fresh("TOK"); t.current_token(); _age(31)
    import requests
    orig = requests.get
    requests.get = lambda *a, **k: (_ for _ in ()).throw(OSError("connection reset"))
    try:
        out = t.refresh()
    finally:
        requests.get = orig
    check("failure reported", out.startswith("refresh request failed"), True)
    check("token untouched", t.current_token(), "TOK")


def t_a_200_with_no_token_is_treated_as_failure():
    _fresh("TOK"); t.current_token(); _age(31)
    out = _with_http(_Resp(200, {"expires_in": 5184000}), t.refresh)
    check("no-token response rejected", "no token" in out, True)
    check("token untouched", t.current_token(), "TOK")


def t_status_line_is_useful():
    _fresh(None)
    check("unconfigured is stated", "not configured" in t.status(), True)
    _fresh("TOK"); t.current_token(); _age(45)
    s = t.status()
    check("remaining days shown", "15 days remaining" in s, True)
    check("due-ness shown", "refresh due" in s, True)


def main():
    print("ig token cases")
    for fn in (t_refresh_happens_at_half_life_not_at_the_deadline,
               t_meta_refuses_tokens_under_24h,
               t_unknown_age_counts_as_due,
               t_a_hand_pasted_replacement_takes_effect,
               t_stored_token_wins_over_an_unchanged_env,
               t_db_failure_falls_back_to_the_environment,
               t_successful_refresh_stores_the_new_token_and_resets_the_clock,
               t_a_rejection_does_not_destroy_the_working_token,
               t_a_network_failure_is_reported_not_swallowed,
               t_a_200_with_no_token_is_treated_as_failure,
               t_status_line_is_useful):
        fn()
    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all ig token cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
