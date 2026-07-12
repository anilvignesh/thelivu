"""Thin Telegraph (telegra.ph) API client.

One account is created on first use and its token cached in the kv store, so
long-form articles can be published as Instant-View pages. No secrets required —
Telegraph hands out the token from an open createAccount call.
"""
import json
import mimetypes

import requests

from shared.db import kv_get, kv_set

_API = "https://api.telegra.ph"
_NAME = "Thelivu"
_TOKEN_KEY = "telegraph_token"


def get_token():
    token = kv_get(_TOKEN_KEY)
    if token:
        return token
    r = requests.post(
        f"{_API}/createAccount",
        data={"short_name": _NAME, "author_name": _NAME},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegraph createAccount failed: {data}")
    token = data["result"]["access_token"]
    kv_set(_TOKEN_KEY, token)
    return token


def create_page(title, nodes, author_name=_NAME):
    """Create a Telegraph page from content nodes; return its URL."""
    token = get_token()
    r = requests.post(
        f"{_API}/createPage",
        data={
            "access_token": token,
            "title": (title or _NAME)[:256],
            "author_name": author_name,
            "content": json.dumps(nodes, ensure_ascii=False),
            "return_content": "false",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegraph createPage failed: {data}")
    return data["result"]["url"]


def upload_image(path):
    """Upload a local image via Telegraph's (unofficial, keyless) file host and
    return its public URL. Used as the public image_url bridge for APIs — like
    Instagram's Graph API — that fetch images by URL rather than accept uploads."""
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        r = requests.post(
            "https://telegra.ph/upload",
            files={"file": (path.rsplit("/", 1)[-1], f, mime)},
            timeout=30,
        )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Telegraph upload failed: {data}")
    if not isinstance(data, list) or not data or "src" not in data[0]:
        raise RuntimeError(f"Telegraph upload returned unexpected response: {data}")
    return "https://telegra.ph" + data[0]["src"]
