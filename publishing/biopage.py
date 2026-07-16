"""Render the public "link in bio" page.

Every slide footer says "Thelivu · link in bio" — this is that page: the
published Telegraph articles plus any pinned evergreen links (channel, about),
served by publishing/fileserver.py at / and /bio. Self-contained HTML (inline
CSS, no external assets) because it opens inside Instagram's in-app browser;
palette mirrors the slide renderer in publishing/slides.py.
"""
import html

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thelivu</title>
<style>
  :root {{
    --bg: #E6DCC3; --fg: #1B1710; --accent: #8C2A1B; --line: rgba(27,23,16,.25);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #17140D; --fg: #E9E0C8; --accent: #D2AA6D; --line: rgba(233,224,200,.25); }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--fg);
    font-family: Georgia, 'Times New Roman', serif;
    max-width: 34rem; margin: 0 auto; padding: 2.5rem 1.25rem 3rem;
  }}
  header {{ text-align: center; margin-bottom: 2rem; }}
  h1 {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: 1.6rem; letter-spacing: .35em; text-indent: .35em;
    text-transform: uppercase;
  }}
  .rule {{
    border: none; border-top: 2px dashed var(--accent);
    margin: 1rem auto; width: 6rem;
  }}
  .tagline {{ font-style: italic; font-size: .95rem; opacity: .8; }}
  .channel {{
    display: inline-block; margin-top: .6rem;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .9rem; color: var(--accent); text-decoration: none;
    border-bottom: 1px dashed var(--accent); padding-bottom: .1rem;
  }}
  ul {{ list-style: none; }}
  li {{ margin-bottom: .8rem; }}
  a.link {{
    display: block; padding: 1rem 1.1rem;
    border: 2px solid var(--line); color: var(--fg);
    text-decoration: none; font-size: 1.05rem; line-height: 1.4;
  }}
  a.link:hover {{ border-color: var(--accent); }}
  li.pinned a.link {{ border-color: var(--accent); }}
  li.pinned a.link::before {{
    content: "★ "; color: var(--accent); font-size: .85em;
  }}
  .empty {{ text-align: center; font-style: italic; opacity: .7; padding: 2rem 0; }}
  footer {{
    margin-top: 2.5rem; text-align: center; font-size: .8rem; opacity: .6;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
  }}
</style>
</head>
<body>
<header>
  <h1>Thelivu</h1>
  <hr class="rule">
  <p class="tagline">Verification-first &middot; human-reviewed</p>{channel_line}
</header>
{body}
<footer>every story fact-checked before it reaches you</footer>
</body>
</html>
"""


def render(links, channel_url=""):
    """links: rows from shared.db.list_bio_links() (already in page order).
    channel_url: the channel's public join link (config.CHANNEL_PUBLIC_URL) —
    part of the page template rather than a bio_links row, so the one permanent
    brand link can't be /dellink'ed or unpinned by accident. It renders as the
    header's second line, above the article list."""
    channel_line = ""
    if channel_url:
        channel_line = (
            f'\n  <a class="channel" href="{html.escape(channel_url, quote=True)}">'
            f'Join the Telegram channel &rarr;</a>'
        )
    items = []
    for link in links:
        cls = ' class="pinned"' if link.get("pinned") else ""
        items.append(
            f'<li{cls}><a class="link" href="{html.escape(link["url"], quote=True)}">'
            f'{html.escape(link["title"] or link["url"])}</a></li>'
        )
    if not items:
        body = '<p class="empty">First stories coming soon.</p>'
    else:
        body = "<ul>\n" + "\n".join(items) + "\n</ul>"
    return _PAGE.format(body=body, channel_line=channel_line)
