"""Mint a YouTube Data API refresh token, locally, for one of two roles.

Run locally, with the OAuth client (Desktop app type) already created in Google
Cloud Console — see docs/HANDOFF.md. It opens a browser consent screen, you
approve as the Thelivu account, and it writes the credential to a 0600 file.

    venv/bin/python -m publishing.youtube_auth --role publish   # Railway
    venv/bin/python -m publishing.youtube_auth --role upload    # reel-worker VM

The client id and secret come from the environment or a hidden prompt, and the
refresh token is written to a FILE and never printed. Argv is visible in the
process table and in shell history; stdout ends up in scrollback and in any
transcript of the session. A credential belongs in neither.

Never run this from Railway or any unattended context — it needs a real
browser and a human clicking "Allow". That's a one-time cost; the resulting
refresh token is what youtube.py uses for every upload after this.

⚠️ Testing-mode caveat (see docs/HANDOFF.md): while the OAuth consent screen
stays in "Testing" publishing status, Google expires this refresh token after
7 days — re-run this script to mint a new one until the app is verified for
"In production" (needed for the youtube.upload scope specifically).
"""
import argparse
import getpass
import os
import stat
import sys
import webbrowser
from pathlib import Path
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

# Two credentials, deliberately unequal — see publishing/longform_build.py.
#
# The reel-worker box renders the long video and stages it UNLISTED. It must be
# able to upload and must NOT be able to publish: gate 2 is a person watching
# the cut, and the guarantee that an automated box cannot skip that gate should
# be the credential itself, not only the state machine. Code has bugs; a token
# without the scope cannot be talked into it.
#
# Railway holds the publishing credential. It never has the video bytes, so it
# cannot upload anything of its own — it can only flip something already staged,
# after a human tapped Post.
#
# videos.insert needs youtube.upload. videos.update (the flip that publishes)
# and videos.delete (the reject path) need youtube or youtube.force-ssl —
# confirmed against Google's documentation 2026-09-11, not assumed.
ROLES = {
    "upload": ("https://www.googleapis.com/auth/youtube.upload",
               "the reel-worker box — can stage an unlisted cut, cannot publish it"),
    "publish": ("https://www.googleapis.com/auth/youtube.upload "
                "https://www.googleapis.com/auth/youtube.readonly "
                "https://www.googleapis.com/auth/youtube.force-ssl",
                "Railway — can publish, delete, and read insights"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", choices=sorted(ROLES), default="publish",
                    help="which credential to mint: 'publish' for Railway, "
                         "'upload' for the reel-worker box")
    ap.add_argument("--out", default=None,
                    help="where to write the result (default "
                         "~/.thelivu/youtube-<role>.env, mode 0600)")
    ap.add_argument("--code", default=None,
                    help="Skip the interactive prompt — pass the code directly "
                         "(e.g. when driving the browser step separately).")
    args = ap.parse_args()

    scope, who = ROLES[args.role]
    print(f"\nMinting the '{args.role}' credential — for {who}.\n")

    # Never on the command line: argv is visible to anything reading the process
    # table, lands in shell history, and shows up in any terminal transcript.
    client_id = os.environ.get("YOUTUBE_CLIENT_ID") or input("client id: ").strip()
    client_secret = (os.environ.get("YOUTUBE_CLIENT_SECRET")
                     or getpass.getpass("client secret (hidden): ").strip())
    if not (client_id and client_secret):
        sys.exit("need both a client id and a client secret")

    params = {
        "client_id": client_id,
        "redirect_uri": _REDIRECT,
        "response_type": "code",
        "scope": scope,
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
        "client_id": client_id,
        "client_secret": client_secret,
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
    # Written to a file, never printed. A refresh token pasted into a terminal
    # is a refresh token in scrollback, in shell history, and in any transcript
    # of the session — including one an assistant can read.
    out = Path(args.out or (Path.home() / ".thelivu" / f"youtube-{args.role}.env"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"YOUTUBE_CLIENT_ID={client_id}\n"
        f"YOUTUBE_CLIENT_SECRET={client_secret}\n"
        f"YOUTUBE_REFRESH_TOKEN={refresh}\n")
    out.chmod(stat.S_IRUSR | stat.S_IWUSR)

    granted = (tokens.get("scope") or "").split()
    print(f"\n✓ Got a '{args.role}' refresh token — written to {out} (mode 0600).")
    print(f"  fingerprint: {refresh[:6]}…{refresh[-4:]} (len {len(refresh)})")
    print("  granted scopes:")
    for sc in granted:
        print(f"    {sc}")
    can_publish = any(sc.endswith(("/youtube", "/youtube.force-ssl")) for sc in granted)
    print(f"  can upload : {any(sc.endswith('/youtube.upload') for sc in granted)}")
    print(f"  can publish: {can_publish}")
    if args.role == "upload" and can_publish:
        print("\n  ⚠ This token CAN publish. That defeats the point of the "
              "upload-only credential — revoke it at "
              "https://myaccount.google.com/permissions and re-run.")
    print(f"\n  Copy the three values out of {out} into the right place:")
    print("    publish -> Railway (service thelivu-agent)")
    print("    upload  -> the reel-worker VM, ops/oracle-vm/reel-worker.env")


if __name__ == "__main__":
    main()
