"""One-time local script to mint a YouTube Data API refresh token.

Run this ONCE, locally, after creating the OAuth client (Desktop app type) in
Google Cloud Console — see docs/HANDOFF.md for the console steps. It opens a
browser consent screen, you approve as the Thelivu Google account, and it
prints the refresh token to store as YOUTUBE_REFRESH_TOKEN on Railway.

    venv/bin/python -m publishing.youtube_auth --client-id ... --client-secret ...

Never run this from Railway or any unattended context — it needs a real
browser and a human clicking "Allow". That's a one-time cost; the resulting
refresh token is what youtube.py uses for every upload after this.

⚠️ Testing-mode caveat (see docs/HANDOFF.md): while the OAuth consent screen
stays in "Testing" publishing status, Google expires this refresh token after
7 days — re-run this script to mint a new one until the app is verified for
"In production" (needed for the youtube.upload scope specifically).
"""
import argparse
import sys
import webbrowser
from urllib.parse import urlencode

import requests

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
# youtube.readonly added 2026-08-17: uploads worked on youtube.upload alone,
# but reading anything back (video statistics for the analytics dashboard,
# channel branding) 403s with ACCESS_TOKEN_SCOPE_INSUFFICIENT on that scope
# alone — verified directly against the live API before adding this, not
# assumed. Re-consenting widens the token; it doesn't narrow what upload could
# already do.
_SCOPE = ("https://www.googleapis.com/auth/youtube.upload "
         "https://www.googleapis.com/auth/youtube.readonly")
_REDIRECT = "http://localhost:8734/"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    ap.add_argument("--code", default=None,
                    help="Skip the interactive prompt — pass the code directly "
                         "(e.g. when driving the browser step separately).")
    args = ap.parse_args()

    params = {
        "client_id": args.client_id,
        "redirect_uri": _REDIRECT,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",   # required to get a refresh_token back
        "prompt": "consent",        # forces one even on a re-run for the same account
    }
    url = f"{_AUTH_URL}?{urlencode(params)}"
    print(f"\nOpening this URL — approve as the Thelivu Google account:\n\n  {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print(f"After approving, Google redirects to {_REDIRECT}?code=... — that page")
    print("will fail to load (nothing is listening on that port), which is fine.")
    print("Copy the 'code' value out of the browser's address bar and paste it here.\n")
    code = args.code or input("code: ").strip()
    if not code:
        sys.exit("no code given")

    resp = requests.post(_TOKEN_URL, data={
        "code": code,
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "redirect_uri": _REDIRECT,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    tokens = resp.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit(f"No refresh_token in response ({tokens}) — if you've run this "
                 "before for the same account, Google may not re-issue one; try "
                 "revoking prior access at https://myaccount.google.com/permissions "
                 "and running this again.")
    print("\n✓ Got a refresh token. Set it on Railway:\n")
    print(f"  railway variable set YOUTUBE_REFRESH_TOKEN={refresh} --service thelivu-agent")
    print(f"  railway variable set YOUTUBE_CLIENT_ID={args.client_id} --service thelivu-agent")
    print(f"  railway variable set YOUTUBE_CLIENT_SECRET={args.client_secret} --service thelivu-agent")


if __name__ == "__main__":
    main()
