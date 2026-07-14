"""Render a published article as a self-hosted web page.

Telegraph was the article host until Indian ISPs made Telegram-owned domains
unreachable (t.me doesn't resolve, telegra.ph connection-resets — tested
2026-07-14). Articles are served from our own Railway domain instead, at
/a/<run_id>-<kebab-headline>, rendered per request from the approved draft in
pipeline_runs — see docs/article-hosting.md.

Consumes the same neutral blocks as every other renderer (publishing.parser);
palette mirrors the bio page and the slides. Self-contained HTML, mobile-first,
readable inside Instagram's in-app browser.
"""
import html
import re

_SLUG_MAX = 60


def make_slug(run_id, headline):
    """'<run_id>-<kebab-headline>' — the id prefix is what lookup uses, the
    words are for humans; cut at a word boundary, never mid-word."""
    kebab = re.sub(r"[^a-z0-9]+", "-", (headline or "").lower()).strip("-")
    if len(kebab) > _SLUG_MAX:
        kebab = kebab[:_SLUG_MAX].rsplit("-", 1)[0]
    return f"{run_id}-{kebab}" if kebab else str(run_id)


def _inline(s):
    """Inline markdown → HTML, escaped first so markup in source text is inert."""
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"__(.+?)__", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
    # s is already entity-escaped, so the captured URL is too (& is &amp;) —
    # valid inside href as-is; only quotes still need neutralising.
    s = re.sub(
        r"\[(.+?)\]\((.+?)\)",
        lambda m: f'<a href="{m.group(2).replace(chr(34), "&quot;")}">{m.group(1)}</a>',
        s,
    )
    return s


def _blocks_to_html(blocks):
    out = []
    for b in blocks:
        if b.type == "heading":
            lvl = min(max(b.level, 2), 4)  # the H1 slot belongs to the title
            out.append(f"<h{lvl}>{_inline(b.text)}</h{lvl}>")
        elif b.type == "blockquote":
            out.append(f"<blockquote>{_inline(b.text)}</blockquote>")
        elif b.type == "list":
            items = "".join(f"<li>{_inline(i)}</li>" for i in b.items)
            out.append(f"<ul>{items}</ul>")
        elif b.type == "rule":
            out.append("<hr>")
        else:
            out.append(f"<p>{_inline(b.text)}</p>")
    return "\n".join(out)


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_attr}</title>
<meta property="og:type" content="article">
<meta property="og:site_name" content="Thelivu">
<meta property="og:title" content="{title_attr}">
<meta property="og:description" content="{hook_attr}">
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
    max-width: 40rem; margin: 0 auto; padding: 2rem 1.25rem 3rem;
    line-height: 1.65; font-size: 1.06rem;
  }}
  .brand {{
    display: block; text-align: center; margin-bottom: 2rem;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: 1rem; letter-spacing: .35em; text-indent: .35em;
    text-transform: uppercase; color: var(--fg); text-decoration: none;
  }}
  h1 {{ font-size: 1.7rem; line-height: 1.25; margin-bottom: .9rem; }}
  .meta {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .8rem; opacity: .75; margin-bottom: 1.6rem;
    padding-bottom: 1.2rem; border-bottom: 2px dashed var(--accent);
  }}
  h2, h3, h4 {{ margin: 1.6rem 0 .6rem; line-height: 1.3; }}
  h2 {{ font-size: 1.25rem; }} h3 {{ font-size: 1.1rem; }} h4 {{ font-size: 1rem; }}
  p {{ margin-bottom: 1rem; }}
  ul {{ margin: 0 0 1rem 1.4rem; }}
  li {{ margin-bottom: .35rem; }}
  blockquote {{
    border-left: 3px solid var(--accent); padding: .2rem 0 .2rem 1rem;
    margin: 0 0 1rem; font-style: italic; opacity: .9;
  }}
  hr {{ border: none; border-top: 2px dashed var(--line); margin: 1.6rem auto; width: 6rem; }}
  a {{ color: var(--accent); }}
  em {{ opacity: .92; }}
  footer {{ margin-top: 2.5rem; text-align: center; }}
  footer a {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .85rem; text-decoration: none;
    border-bottom: 1px dashed var(--accent); padding-bottom: .1rem;
  }}
</style>
</head>
<body>
<a class="brand" href="/">Thelivu</a>
<article>
<h1>{title}</h1>
<p class="meta">{confidence_emoji} {confidence} &middot; published {date}</p>
{body}
</article>
<footer><a href="/">&larr; all Thelivu stories</a></footer>
</body>
</html>
"""

_NOT_FOUND = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thelivu</title>
<style>
  body { background: #E6DCC3; color: #1B1710; font-family: Georgia, serif;
         text-align: center; padding: 4rem 1.25rem; }
  @media (prefers-color-scheme: dark) { body { background: #17140D; color: #E9E0C8; } }
  a { color: inherit; }
</style>
</head>
<body>
<p>No such story.</p>
<p><a href="/">&larr; all Thelivu stories</a></p>
</body>
</html>
"""


def render_article(article, published_at=None):
    """article: a publishing.parser.Article from the prepared draft."""
    date = ""
    if published_at:
        # both TIMESTAMP (postgres) and TEXT (sqlite) arrive stringifiable
        date = str(published_at)[:10]
    return _PAGE.format(
        title=_inline(article.title),
        title_attr=html.escape(article.title, quote=True),
        hook_attr=html.escape(article.hook or "", quote=True),
        confidence=html.escape(article.confidence_label),
        confidence_emoji=article.confidence_emoji,
        date=date or "recently",
        body=_blocks_to_html(article.blocks),
    )


def render_not_found():
    return _NOT_FOUND