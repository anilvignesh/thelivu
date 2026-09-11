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
    the description if not already present.

    Shorts-shelf eligibility (verified 2026-08-17, correcting a stale comment
    that said <=60s): YouTube expanded the Shorts length ceiling from 60s to
    3 minutes in October 2024. A vertical/square video just needs to be
    <=3min to qualify — nowhere near what video-script's ~85s ceiling
    produces, so the 2026-08-17 length increase (engine/skills/video-script/
    SKILL.md, 110-210 words) doesn't cost Shorts placement here. Instagram's
    own Reels-shelf ceiling (90s) is still the tighter constraint of the two
    platforms — video-script's cap tracks Instagram's, not YouTube's.
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


def publish_video(video_bytes, title, description="", tags=None, progress=None,
                  privacy="public", chapters=None):
    """Upload a full-length (horizontal or vertical) video. Returns (id, permalink).

    The long-form sibling of publish_short(), for stories too dense for the 90s
    reel ceiling — see docs/plans/ and the Long-Form Video Format note. Kept as a
    separate function rather than a flag on publish_short() because the two
    differ in ways that matter and would otherwise accumulate as branches:

      * No "#Shorts" tag. Appending it to a 10-minute video does not make it a
        Short; it just mislabels the video and can suppress its placement.
      * The permalink is /watch?v=, not /shorts/. A long video served under a
        /shorts/ URL redirects, and any link we have already published stays
        wrong.
      * `privacy` is a parameter and can be "private" or "unlisted". A long-form
        cut is the kind of thing worth reviewing before it is public, and the
        90s pipeline's straight-to-public default is not obviously right here.
      * Chapters. YouTube builds them from timestamps in the description, and
        long-form is exactly where they earn their keep.

    Timeouts are raised over publish_short()'s: a 10-minute render is a much
    larger file, and a PUT that dies at 300s on a slow uplink would waste the
    ~70 minutes of CPU that produced it (Chatterbox measured at ~7.2x realtime
    on the reel-worker, 2026-09-10).

    Raises YouTubeNotConfigured / YouTubePublishError.
    """
    def _p(frac, msg):
        if progress:
            try: progress(min(max(frac, 0.0), 1.0), msg)
            except Exception: pass

    _p(0.05, "Authenticating with YouTube…")
    token = _access_token()

    desc = description or ""
    if chapters:
        desc = (desc.rstrip() + "\n\n" + format_chapters(chapters)).strip()

    if privacy not in ("public", "unlisted", "private"):
        raise YouTubePublishError(f"invalid privacy: {privacy!r}")

    metadata = {
        "snippet": {
            "title": (title or "Thelivu")[:100],
            "description": desc[:5000],
            "tags": (tags or [])[:500],
            "categoryId": "25",  # News & Politics, same as the reel path
        },
        "status": {
            "privacyStatus": privacy,
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
        json=metadata, timeout=60,
    )
    if init.status_code != 200 or "Location" not in init.headers:
        raise YouTubePublishError(f"Could not start upload session: "
                                  f"{init.status_code} {init.text[:300]}")
    upload_url = init.headers["Location"]

    _p(0.3, f"Uploading {len(video_bytes) / 1e6:.1f}MB…")
    put = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4",
                 "Content-Length": str(len(video_bytes))},
        data=video_bytes, timeout=1800,
    )
    if put.status_code not in (200, 201):
        raise YouTubePublishError(f"Upload failed: {put.status_code} {put.text[:300]}")

    body = put.json()
    video_id = body.get("id")
    if not video_id:
        raise YouTubePublishError(f"Upload succeeded but no video id in response: {body}")
    _p(1.0, "Posted ✓")
    return video_id, f"https://youtube.com/watch?v={video_id}"


# videos.insert needs only youtube.upload. videos.update (the privacy flip that
# PUBLISHES a long-form video) and videos.delete (the reject path) do not —
# confirmed against Google's docs 2026-09-11: youtube.upload "allows an
# application to upload files to the authenticated user's YouTube channel, but
# doesn't allow other types of access."
#
# The production token is youtube.upload + youtube.readonly (see
# publishing/youtube_auth.py), which is why every Short has posted fine for
# months: insert is all the reel path ever does. The long-form path needs more,
# and would have discovered that AFTER spending an hour of the voice server.
PUBLISH_SCOPES = ("https://www.googleapis.com/auth/youtube",
                  "https://www.googleapis.com/auth/youtube.force-ssl")


def preflight(need_publish=False):
    """(ok, why) — can we do what we are about to do? Checked BEFORE the work.

    A long-form render costs ~80 minutes of the only voice server. Finding out
    afterwards that the token cannot upload, or cannot flip a video public, is
    the most expensive possible moment to find out.
    """
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        return False, ("YouTube is not configured on this box — "
                       "YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN are unset")
    try:
        resp = requests.post(_TOKEN_URL, data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }, timeout=30)
    except Exception as e:
        return False, f"could not reach Google: {type(e).__name__}: {e}"
    if resp.status_code != 200:
        return False, f"refresh token rejected: {resp.text[:200]}"

    granted = (resp.json().get("scope") or "").split()
    if "https://www.googleapis.com/auth/youtube.upload" not in granted and not any(
            sc in granted for sc in PUBLISH_SCOPES):
        return False, f"token cannot upload; scopes are {granted}"
    if need_publish and not any(sc in granted for sc in PUBLISH_SCOPES):
        return False, (
            "token can upload but CANNOT publish or delete — videos.update and "
            "videos.delete need youtube or youtube.force-ssl, and this token has "
            f"{granted}. Re-run publishing/youtube_auth.py to widen it.")
    return True, "ok"


def set_privacy(video_id, privacy):
    """Flip an already-uploaded video's privacy. Returns the new status.

    This is how a long-form video is *published*. It is uploaded UNLISTED at
    render time (see publishing/longform_build.py) so that gate 2 — Anil
    watching it — happens on YouTube's own player rather than off a fileserver
    streaming a few hundred megabytes, and so the upload's ~20 minutes are
    spent before the review rather than after it.

    Which means the two halves of publishing run in different places: the
    reel-worker box has the bytes and no posting credentials, Railway has the
    credentials and no bytes. A privacy flip needs only the credentials.

    `part=status` with only the fields we mean to change: YouTube's videos.update
    REPLACES each part it is given, so sending `snippet` here would blank the
    title and description that were set at upload.
    """
    if privacy not in ("public", "unlisted", "private"):
        raise YouTubePublishError(f"invalid privacy: {privacy!r}")
    token = _access_token()
    r = requests.put(
        "https://www.googleapis.com/youtube/v3/videos?part=status",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=UTF-8"},
        json={"id": video_id,
              "status": {"privacyStatus": privacy,
                         "selfDeclaredMadeForKids": False}},
        timeout=60)
    if r.status_code != 200:
        raise YouTubePublishError(
            f"Could not set {video_id} to {privacy}: {r.status_code} {r.text[:300]}")
    return (r.json().get("status") or {}).get("privacyStatus", privacy)


def delete_video(video_id):
    """Remove a video from the channel. Returns True, or raises.

    Only used on the long-form reject path: an unlisted cut staged for review
    and then turned down should not stay on the channel. Nothing else here
    deletes anything, and nothing should — a published video is a public record
    that we corrected rather than removed.
    """
    token = _access_token()
    r = requests.delete(
        f"https://www.googleapis.com/youtube/v3/videos?id={video_id}",
        headers={"Authorization": f"Bearer {token}"}, timeout=60)
    # 204 on success; 404 means it is already gone, which is the desired state.
    if r.status_code not in (200, 204, 404):
        raise YouTubePublishError(
            f"Could not delete {video_id}: {r.status_code} {r.text[:300]}")
    return True


def format_chapters(chapters):
    """[(seconds, label), ...] -> the timestamp block YouTube parses.

    YouTube's rules, which are easy to get subtly wrong: the list must start at
    00:00, needs at least three entries, and they must be in ascending order —
    break any of those and YouTube silently renders no chapters at all rather
    than reporting an error. Returning the block unchanged when it would not
    qualify keeps a half-valid list out of the description.
    """
    items = sorted((int(s), str(l).strip()) for s, l in chapters if str(l).strip())
    if len(items) < 3 or items[0][0] != 0:
        return ""
    lines = []
    for secs, label in items:
        h, rem = divmod(secs, 3600)
        m, sec = divmod(rem, 60)
        stamp = f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
        lines.append(f"{stamp} {label}")
    return "\n".join(lines)
