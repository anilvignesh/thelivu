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


def _graph_post(node_path, data, tries=5):
    """POST to the Graph API with retries. Meta's domains are flaky on some ISPs
    (docs/HANDOFF.md §5) — a reset/empty response makes r.json() raise a bare
    "Expecting value" JSONDecodeError, which used to crash the whole publish. Retry
    transient transport/parse failures with backoff; return parsed JSON or raise."""
    last = None
    for i in range(tries):
        r = None
        try:
            r = requests.post(f"{_API}/{node_path}", data=data, timeout=30)
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            # Capture the smoking gun: on an empty/non-JSON body we now log the raw
            # HTTP status + body snippet, instead of a bare "Expecting value" error.
            detail = f" [HTTP {r.status_code}, body={r.text[:200]!r}]" if r is not None else " [no response]"
            log.warning("Instagram POST %s attempt %d/%d failed: %s%s", node_path, i + 1, tries, e, detail)
            time.sleep(min(2 ** i, 10))
    raise IGPublishError(f"Instagram POST {node_path} failed after {tries} tries: {last}")


def _graph_get(node_path, params, tries=5):
    last = None
    for i in range(tries):
        r = None
        try:
            r = requests.get(f"{_API}/{node_path}", params=params, timeout=15)
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            detail = f" [HTTP {r.status_code}, body={r.text[:200]!r}]" if r is not None else " [no response]"
            log.warning("Instagram GET %s attempt %d/%d failed: %s%s", node_path, i + 1, tries, e, detail)
            time.sleep(min(2 ** i, 10))
    raise IGPublishError(f"Instagram GET {node_path} failed after {tries} tries: {last}")


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
    data = _graph_post(f"{IG_USER_ID}/media_publish",
                       {"creation_id": container_id, "access_token": IG_ACCESS_TOKEN})
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


def publish_carousel(image_urls, caption=""):
    """Publish up to 10 images (already at public image_urls) as one
    Instagram carousel post. Returns (media_id, permalink). Raises
    IGNotConfigured if the Meta app isn't set up, or IGPublishError on any
    Graph API failure (including a single bad child — the whole carousel is
    one post, so a partial publish isn't meaningful)."""
    _require_config()
    if not 2 <= len(image_urls) <= 10:
        raise IGPublishError(f"Carousel needs 2-10 images, got {len(image_urls)}")
    child_ids = [_create_carousel_item(url) for url in image_urls]
    for child_id in child_ids:
        _wait_until_ready(child_id)
    container_id = _create_carousel_container(child_ids, caption)
    _wait_until_ready(container_id)
    media_id = _publish_container(container_id)
    return media_id, _permalink(media_id)
