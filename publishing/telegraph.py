"""Thin Telegraph (telegra.ph) API client.

One account is created on first use and its token cached in the kv store, so
long-form articles can be published as Instant-View pages. No secrets required —
Telegraph hands out the token from an open createAccount call.
"""
import json

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
