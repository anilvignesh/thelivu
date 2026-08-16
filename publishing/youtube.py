"""Thin YouTube Data API v3 client — uploads a Short from our own stored bytes.

Unlike Instagram (which fetches from a public image_url we host), YouTube's
upload API takes the video bytes directly. Rather than round-tripping through
our own fileserver, this pulls the MP4 straight out of the DB
(shared.db.get_reel_bytes) — same bytes, one less network hop, no dependency
on SLIDE_SERVER_BASE_URL being reachable from Google's side.

Auth is a refresh token minted once via publishing/youtube_auth.py (see that
file's docstring) — exchanged for a short-lived access token on every call
here rather than cached, since uploads are infrequent (a few/day) and this
avoids any stale-token bookkeeping.

Requires YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN in
shared/config.py. Until set, YouTubeNotConfigured is raised so callers degrade
gracefully — same contract as IGNotConfigured in instagram.py.
"""
import logging
import time

import requests

from shared.config import YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?uploadType=resumable&part=snippet,status")
log = logging.getLogger("youtube")


class YouTubeNotConfigured(RuntimeError):
    """YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN not set — see publishing/youtube_auth.py."""


class YouTubePublishError(RuntimeError):
    pass


def _require_config():
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        raise YouTubeNotConfigured(
            "YouTube not configured — run publishing/youtube_auth.py once and set "
            "YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET/YOUTUBE_REFRESH_TOKEN.")


def _access_token():
    _require_config()
    resp = requests.post(_TOKEN_URL, data={
        "client_id": YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=30)
    if resp.status_code != 200:
        # A 400 invalid_grant here is almost always the Testing-mode 7-day expiry
        # (see youtube_auth.py) — surface that plainly rather than a raw traceback.
        body = resp.text[:300]
        if resp.status_code == 400 and "invalid_grant" in body:
            raise YouTubePublishError(
                "YouTube refresh token rejected (likely expired — OAuth consent "
                "screen is still in Testing mode, tokens die after 7 days). "
                "Re-run publishing/youtube_auth.py for a new one.")
        raise YouTubePublishError(f"Could not refresh YouTube access token: {body}")
    return resp.json()["access_token"]


def publish_short(video_bytes, title, description="", tags=None, progress=None):
    """Upload a vertical video as a YouTube Short. Returns (video_id, permalink).

    `title` is truncated to YouTube's 100-char limit. `#Shorts` is appended to
    the description if not already present — that, plus a <=60s vertical video,
    is what gets Shorts-shelf treatment (longer uploads still work, just don't
    get it — see engine/distribution docstring for the reel-length note).
    Raises YouTubeNotConfigured / YouTubePublishError."""
    def _p(frac, msg):
        if progress:
            try: progress(min(max(frac, 0.0), 1.0), msg)
            except Exception: pass

    _p(0.05, "Authenticating with YouTube…")
    token = _access_token()

    desc = description or ""
    if "#shorts" not in desc.lower():
        desc = (desc + "\n\n#Shorts").strip()

    metadata = {
        "snippet": {
            "title": (title or "Thelivu")[:100],
            "description": desc[:5000],
            "tags": (tags or [])[:500],
            "categoryId": "25",  # News & Politics
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    _p(0.15, "Starting the upload session…")
    init = requests.post(
        _UPLOAD_URL,
        headers={"Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(len(video_bytes))},
        json=metadata, timeout=30,
    )
    if init.status_code != 200 or "Location" not in init.headers:
        raise YouTubePublishError(f"Could not start upload session: "
                                  f"{init.status_code} {init.text[:300]}")
    upload_url = init.headers["Location"]

    _p(0.3, "Uploading the video…")
    put = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4",
                "Content-Length": str(len(video_bytes))},
        data=video_bytes, timeout=300,
    )
    if put.status_code not in (200, 201):
        raise YouTubePublishError(f"Upload failed: {put.status_code} {put.text[:300]}")

    body = put.json()
    video_id = body.get("id")
    if not video_id:
        raise YouTubePublishError(f"Upload succeeded but no video id in response: {body}")
    _p(1.0, "Posted ✓")
    return video_id, f"https://youtube.com/shorts/{video_id}"
