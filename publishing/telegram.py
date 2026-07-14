"""Render a Thelivu Article for Telegram: a Telegraph page + a channel teaser.

`render()` publishes the full article as a Telegraph Instant-View page and builds
a short HTML teaser for the channel (bold title, derived hook, the Instant-View
link, confidence, and the correction contact). The teaser is derived
deterministically — no LLM in the publish path.
"""
import html
import re

from publishing import telegraph

# bold | italic | [text](url)
_INLINE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|\[(.+?)\]\((.+?)\)")


def _inline_to_nodes(s):
    """Inline markdown -> list of Telegraph nodes (strings and tag dicts)."""
    nodes, pos = [], 0
    for m in _INLINE.finditer(s):
        if m.start() > pos:
            nodes.append(s[pos:m.start()])
        if m.group(1) is not None:
            nodes.append({"tag": "strong", "children": [m.group(1)]})
        elif m.group(2) is not None:
            nodes.append({"tag": "em", "children": [m.group(2)]})
        else:
            nodes.append({"tag": "a", "attrs": {"href": m.group(4)}, "children": [m.group(3)]})
        pos = m.end()
    if pos < len(s):
        nodes.append(s[pos:])
    return nodes or [s]


def _blocks_to_nodes(blocks):
    """Neutral Blocks -> Telegraph DOM nodes. Telegraph supports only h3/h4."""
    nodes = []
    for b in blocks:
        if b.type == "rule":
            nodes.append({"tag": "hr"})
        elif b.type == "heading":
            tag = "h3" if b.level <= 2 else "h4"
            nodes.append({"tag": tag, "children": _inline_to_nodes(b.text)})
        elif b.type == "blockquote":
            nodes.append({"tag": "blockquote", "children": _inline_to_nodes(b.text)})
        elif b.type == "list":
            items = [{"tag": "li", "children": _inline_to_nodes(it)} for it in b.items]
            nodes.append({"tag": "ul", "children": items})
        else:
            nodes.append({"tag": "p", "children": _inline_to_nodes(b.text)})
    return nodes


def _esc(s):
    return html.escape(s, quote=False)


def build_teaser(article, url, contact):
    """The short HTML channel post pointing at the article's canonical URL —
    since 2026-07-14 that's the self-hosted /a/ page, not Telegraph (Telegram-
    owned domains are blocked or flaky on Indian ISPs; see
    docs/article-hosting.md)."""
    parts = [f"<b>{_esc(article.title)}</b>"]
    if article.hook:
        parts += ["", _esc(article.hook)]
    parts += ["", f'▸ <a href="{html.escape(url, quote=True)}">Read the full story</a>']
    parts += ["", f"{article.confidence_emoji} {_esc(article.confidence_label)}"]
    parts.append(f"Spotted an error? We correct openly — {_esc(contact)}")
    return "\n".join(parts)


def report_to_telegraph(title, markdown):
    """Publish any markdown body (a verification report, a draft preview, etc.) as
    a clean Telegraph page and return its URL. Used by owner-facing comms so long
    reports become a link instead of a wall of raw markdown in the chat."""
    from publishing.parser import parse_blocks
    nodes = _blocks_to_nodes(parse_blocks(markdown or ""))
    return telegraph.create_page(title or "Thelivu report", nodes)
