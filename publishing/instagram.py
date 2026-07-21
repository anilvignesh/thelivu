"""Thin Instagram API (Content Publishing) client.

Two-step publish: create a media container from a public image_url, then
publish the container. Instagram's API only accepts a fetchable URL, not a
file upload — publishing.telegraph.upload_image() is used as the public host
for the locally-rendered slide PNG.

Uses graph.instagram.com, not graph.facebook.com — the app was set up via
Meta's newer "Instagram API with Instagram Login" flow (no Facebook Page
required), which issues tokens scoped to the Instagram-native host. The
classic Page-linked Graph API (graph.facebook.com) expects a different token
type and will reject these with "Cannot parse access token".

Requires IG_USER_ID (the professional account's numeric id) and
IG_ACCESS_TOKEN (long-lived, instagram_business_basic +
instagram_business_content_publish) in shared/config.py. Both are set once
the Meta app + IG account are wired up; until then, IGNotConfigured is raised
so callers can degrade gracefully instead of crashing the approval flow.
"""
import logging
import time

import requests

from shared.config import IG_USER_ID, IG_ACCESS_TOKEN

_API = "https://graph.instagram.com/v21.0"
log = logging.getLogger("instagram")

# Meta error codes that are transient (their servers, not our request) — retry these.
# 1/2 = unknown/unexpected, 4/17/32/613 = rate/throughput limits. is_transient=True
# also marks them. A non-transient error (bad token, bad param) is returned as-is so
# the caller can raise a clear message instead of retrying pointlessly.
_TRANSIENT_CODES = {1, 2, 4, 17, 32, 341, 368, 613}
# Publish-step subcodes that are Meta-side internal errors, NOT our request — these
# lie about is_transient (they come back is_transient=False, code=-1) but the
# error_user_msg says "try again later". 2207085 = "Generic internal error" on
# media_publish (the carousel #13 failure). Retrying after a delay clears them.
_TRANSIENT_SUBCODES = {2207085, 2207001, 2207032, 2207003, 2207020, 2207026}
# Message fragments that mark a retryable server-side blip regardless of the flags.
_TRANSIENT_MSGS = ("try again", "internal server error", "temporarily", "please retry")


def _is_transient_error(payload):
    err = payload.get("error") if isinstance(payload, dict) else None
    if not err:
        return False
    if err.get("is_transient") or err.get("code") in _TRANSIENT_CODES:
        return True
    if err.get("error_subcode") in _TRANSIENT_SUBCODES:
        return True
    msg = f"{err.get('error_user_msg','')} {err.get('message','')}".lower()
    return any(frag in msg for frag in _TRANSIENT_MSGS)


class IGNotConfigured(RuntimeError):
    """IG_USER_ID / IG_ACCESS_TOKEN not set yet — Meta app isn't wired up."""


class IGPublishError(RuntimeError):
    pass


def _require_config():
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        raise IGNotConfigured(
            "IG_USER_ID / IG_ACCESS_TOKEN not set — Instagram publishing isn't "
            "configured yet. The slide is saved; post it manually for now."
        )


def _graph_post(node_path, data, tries=5, max_backoff=10):
    """POST to the Graph API with retries. Meta's domains are flaky on some ISPs
    (docs/HANDOFF.md §5) — a reset/empty response makes r.json() raise a bare
    "Expecting value" JSONDecodeError, which used to crash the whole publish. Retry
    transient transport/parse failures AND Meta-side transient error payloads with
    backoff; return parsed JSON or raise. max_backoff lets the publish step wait
    longer (its 2207085 "internal error" often needs 30–60s to clear)."""
    last = None
    for i in range(tries):
        r = None
        try:
            r = requests.post(f"{_API}/{node_path}", data=data, timeout=30)
            out = r.json()
            if _is_transient_error(out):  # Meta-side blip — retry
                last = out["error"]
                log.warning("Instagram POST %s attempt %d/%d transient: %s (subcode %s)",
                            node_path, i + 1, tries, out["error"].get("message"),
                            out["error"].get("error_subcode"))
                time.sleep(min(2 ** i, max_backoff)); continue
            return out
        except (requests.RequestException, ValueError) as e:
            last = e
            # Capture the smoking gun: on an empty/non-JSON body log the raw HTTP
            # status + body snippet, instead of a bare "Expecting value" error.
            detail = f" [HTTP {r.status_code}, body={r.text[:200]!r}]" if r is not None else " [no response]"
            log.warning("Instagram POST %s attempt %d/%d failed: %s%s", node_path, i + 1, tries, e, detail)
            time.sleep(min(2 ** i, max_backoff))
    raise IGPublishError(f"Instagram POST {node_path} failed after {tries} tries (last: {last})")


def _graph_get(node_path, params, tries=5):
    last = None
    for i in range(tries):
        r = None
        try:
            r = requests.get(f"{_API}/{node_path}", params=params, timeout=15)
            out = r.json()
            if _is_transient_error(out):
                last = out["error"]
                time.sleep(min(2 ** i, 10)); continue
            return out
        except (requests.RequestException, ValueError) as e:
            last = e
            detail = f" [HTTP {r.status_code}, body={r.text[:200]!r}]" if r is not None else " [no response]"
            log.warning("Instagram GET %s attempt %d/%d failed: %s%s", node_path, i + 1, tries, e, detail)
            time.sleep(min(2 ** i, 10))
    raise IGPublishError(f"Instagram GET {node_path} failed after {tries} tries (last: {last})")


def _create_container(image_url, caption):
    data = _graph_post(f"{IG_USER_ID}/media",
                       {"image_url": image_url, "caption": caption, "access_token": IG_ACCESS_TOKEN})
    if "id" not in data:
        raise IGPublishError(f"Container creation failed: {data}")
    return data["id"]


def _create_carousel_item(image_url):
    data = _graph_post(f"{IG_USER_ID}/media",
                       {"image_url": image_url, "is_carousel_item": "true", "access_token": IG_ACCESS_TOKEN})
    if "id" not in data:
        raise IGPublishError(f"Carousel item creation failed: {data}")
    return data["id"]


def _create_carousel_container(child_ids, caption):
    data = _graph_post(f"{IG_USER_ID}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN,
    })
    if "id" not in data:
        raise IGPublishError(f"Carousel container creation failed: {data}")
    return data["id"]


def _wait_until_ready(container_id, attempts=10, delay=2):
    """Poll the container's status_code until FINISHED (or give up and try
    publishing anyway — single-image containers are usually ready instantly;
    this just avoids a race on a slow day)."""
    for _ in range(attempts):
        status = _graph_get(container_id, {"fields": "status_code", "access_token": IG_ACCESS_TOKEN}).get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise IGPublishError(f"Container {container_id} failed processing.")
        time.sleep(delay)


def _publish_container(container_id):
    # The publish step is the one that throws Meta's intermittent 2207085 "internal
    # error" even when the container is FINISHED — give it more tries + longer waits
    # (up to ~2 min) so it rides out the blip instead of failing the whole post.
    data = _graph_post(f"{IG_USER_ID}/media_publish",
                       {"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
                       tries=7, max_backoff=30)
    if "id" not in data:
        raise IGPublishError(f"Publish failed: {data}")
    return data["id"]


def _permalink(media_id):
    try:
        r = requests.get(
            f"{_API}/{media_id}",
            params={"fields": "permalink", "access_token": IG_ACCESS_TOKEN},
            timeout=15,
        )
        return r.json().get("permalink", "")
    except Exception:
        return ""


def publish_photo(image_url, caption=""):
    """Publish one image (already at a public image_url) to the configured IG
    account. Returns (media_id, permalink). Raises IGNotConfigured if the Meta
    app isn't set up, or IGPublishError on any Graph API failure."""
    _require_config()
    container_id = _create_container(image_url, caption)
    _wait_until_ready(container_id)
    media_id = _publish_container(container_id)
    return media_id, _permalink(media_id)


def publish_carousel(image_urls, caption="", progress=None):
    """Publish up to 10 images (already at public image_urls) as one
    Instagram carousel post. Returns (media_id, permalink). Raises
    IGNotConfigured if the Meta app isn't set up, or IGPublishError on any
    Graph API failure (including a single bad child — the whole carousel is
    one post, so a partial publish isn't meaningful).

    `progress(fraction, message)` — optional callback for a UI progress bar; called
    at each step (0.0→1.0). Ignored if None."""
    def _p(frac, msg):
        if progress:
            try:
                progress(min(max(frac, 0.0), 1.0), msg)
            except Exception:
                pass

    _require_config()
    if not 2 <= len(image_urls) <= 10:
        raise IGPublishError(f"Carousel needs 2-10 images, got {len(image_urls)}")
    n = len(image_urls)
    total = n + 2  # each slide upload + assemble + publish
    child_ids = []
    for i, url in enumerate(image_urls):
        _p(i / total, f"Uploading slide {i + 1} of {n}…")
        child_ids.append(_create_carousel_item(url))
    for i, child_id in enumerate(child_ids):
        _wait_until_ready(child_id)
        _p((i + 1) / total, f"Processing slide {i + 1} of {n}…")
    _p(n / total, "Assembling the carousel…")
    container_id = _create_carousel_container(child_ids, caption)
    _wait_until_ready(container_id)
    _p((n + 1) / total, "Publishing to Instagram…")
    media_id = _publish_container(container_id)
    _p(1.0, "Posted ✓")
    return media_id, _permalink(media_id)
