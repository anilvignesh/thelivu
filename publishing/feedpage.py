"""Render the public homepage: an editorial feed.

The newest story runs as the lead with its media; everything after it is tiered by Thelivu's own confidence signal instead of one
uniform card: Confirmed runs wide with media, Developing runs standard (thumbnail beside the text), Contested runs compact and
text-only. That tiering is Thelivu's editorial model made visible in the layout.

This is the real homepage for organic/direct visitors and shared article links. `/bio` (publishing/biopage.py) is untouched and
keeps serving the minimal link list Instagram's in-app browser opens from the bio tap. See docs/homepage-feed.md.

Self-contained: one same-origin font (Archivo, publishing/static/), shared look in publishing/sitestyle.py, no third-party host and
no GSAP here. Motion is one authored moment (the lead's media settles in on load, ease-out) plus press feedback; everything is fully
visible and readable with no JS, and reel previews autoplay (muted, in place) only if IntersectionObserver is available.
"""
import html

from publishing.articlepage import make_slug
from publishing.parser import parse_article, prepare_for_publish
from publishing.sitestyle import BASE_CSS, header, status_block

_CONF_TIER = {"confirmed": "feature", "developing": "standard", "contested": "compact"}


def _esc(s, quote=False):
    return html.escape(s or "", quote=quote)


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thelivu</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="Thelivu">
<meta property="og:title" content="Thelivu">
<meta property="og:description" content="Verification-first journalism — every story fact-checked before it reaches you.">
<style>
{base_css}
  body {{ max-width: 44rem; margin: 0 auto; padding: 1.75rem 1.25rem 3.5rem; }}
  .channel {{
    display: inline-block; margin-bottom: 2rem; font-family: var(--sans); font-size: .85rem; font-weight: 600;
    color: var(--accent); text-decoration: none; border-bottom: 1.5px solid var(--accent); padding-bottom: .1rem;
  }}
  a.story {{ display: block; color: var(--fg); text-decoration: none; }}

  /* Lead: the newest story, media full width of the column */
  .hero {{ display: block; margin-bottom: 3rem; color: var(--fg); text-decoration: none; }}
  .hero-media-wrap {{ overflow: hidden; max-height: 62vh; background: var(--line); margin-bottom: 1.25rem; }}
  .hero-media {{ display: block; width: 100%; max-height: 62vh; object-fit: cover; animation: settle 700ms var(--ease-out) both; }}
  @keyframes settle {{ from {{ transform: scale(1.05); opacity: .6; }} to {{ transform: none; opacity: 1; }} }}
  .hero h2 {{ font-size: clamp(1.7rem, 5.5vw, 2.5rem); line-height: 1.1; margin-bottom: .75rem; }}
  .hero p.hook {{ font-size: 1.12rem; line-height: 1.55; color: var(--fg); max-width: 38rem; }}

  .section-label {{
    display: flex; align-items: center; gap: .8rem; margin: 0 0 .5rem;
    font-family: var(--sans); font-size: .78rem; font-weight: 600; letter-spacing: .2em; text-transform: uppercase;
    color: var(--accent);
  }}
  .section-label::after {{ content: ""; flex: 1; border-top: 1px solid var(--line); }}

  .feed {{ display: flex; flex-direction: column; }}
  .story {{ padding: 1.4rem 0; border-bottom: 1px solid var(--line); }}
  .story h3 {{ margin-bottom: .4rem; }}
  .story p.hook {{ color: var(--dim); line-height: 1.5; }}

  /* Confirmed: media on top, the biggest headline */
  .story.feature .story-media {{ display: block; width: 100%; max-height: 20rem; object-fit: cover; background: var(--line); margin-bottom: 1rem; }}
  .story.feature h3 {{ font-size: 1.45rem; line-height: 1.2; }}
  .story.feature p.hook {{ font-size: 1.02rem; }}

  /* Developing: thumbnail beside the text */
  .story.standard {{ display: flex; gap: 1rem; align-items: flex-start; }}
  .story.standard .story-media {{ width: 6.5rem; height: 6.5rem; flex: none; object-fit: cover; background: var(--line); }}
  .story.standard .story-body {{ min-width: 0; }}
  .story.standard h3 {{ font-size: 1.12rem; line-height: 1.25; }}
  .story.standard p.hook {{ font-size: .94rem; }}

  /* Contested: text only; the red status block carries the signal */
  .story.compact h3 {{ font-size: 1.02rem; line-height: 1.3; }}

  .empty {{ font-style: italic; color: var(--dim); padding: 3rem 0; }}
  footer {{ margin-top: 2.5rem; font-family: var(--sans); font-size: .78rem; color: var(--dim); }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
{header}{channel_line}
{body}
<footer>Every story fact-checked before it reaches you &middot; <a href="/bio">link in bio</a></footer>
<script>
(function() {{
  var vids = document.querySelectorAll('video.hero-media, video.story-media');
  if (!vids.length || !('IntersectionObserver' in window)) return;
  var io = new IntersectionObserver(function(entries) {{
    entries.forEach(function(e) {{
      if (e.isIntersecting) {{ e.target.play().catch(function() {{}}); }}
      else {{ e.target.pause(); }}
    }});
  }}, {{threshold: .5}});
  vids.forEach(function(v) {{ io.observe(v); }});
}})();
</script>
</body>
</html>
"""


def _parsed(item, contact_handle):
    """(article, slug, date) for a feed row, or None if the draft couldn't be
    parsed — skipped, not fatal; one bad row must not break the homepage."""
    try:
        article = parse_article(prepare_for_publish(item["draft_text"], contact_handle))
    except Exception:
        return None
    slug = item.get("slug") or make_slug(item["id"], article.title)
    date = str(item["updated_at"])[:10] if item.get("updated_at") else ""
    return article, slug, date or "recently"


def _media_url(item):
    """(tag, url) — 'video'/'img'/None. None means no media exists for this story."""
    if item.get("reel_id"):
        return "video", f'/reel/{item["reel_id"]}.mp4'
    if item.get("carousel_id"):
        return "img", f'/carousel_{item["carousel_id"]}_1.jpg'
    return None, None


def _hero_html(item, contact_handle):
    parsed = _parsed(item, contact_handle)
    if not parsed:
        return ""
    article, slug, date = parsed
    kind, url = _media_url(item)
    media = ""
    if kind == "video":
        media = (
            f'<div class="hero-media-wrap"><video class="hero-media" muted loop playsinline autoplay '
            f'preload="metadata" controls><source src="{url}" type="video/mp4"></video></div>'
        )
    elif kind == "img":
        media = (
            f'<div class="hero-media-wrap"><img class="hero-media" src="{url}" '
            f'alt="{_esc(article.title, True)}"></div>'
        )
    return (
        f'<a class="hero" href="/a/{slug}">{media}'
        f'<div class="hero-body">'
        f'<p class="meta">{status_block(article.confidence_label, date)}</p>'
        f'<h2>{_esc(article.title)}</h2>'
        f'<p class="hook">{_esc(article.hook)}</p>'
        f'</div></a>'
    )


def _story_html(item, contact_handle):
    """One tiered story row for the 'more reporting' section, or None on a
    parse failure (skipped, not fatal — see _parsed)."""
    parsed = _parsed(item, contact_handle)
    if not parsed:
        return None
    article, slug, date = parsed
    tier = _CONF_TIER.get(article.confidence_label.lower(), "standard")
    kind, url = _media_url(item)

    media = ""
    if tier != "compact" and kind == "video":
        media = (
            f'<video class="story-media" muted loop playsinline autoplay preload="metadata">'
            f'<source src="{url}" type="video/mp4"></video>'
        )
    elif tier != "compact" and kind == "img":
        media = f'<img class="story-media" src="{url}" loading="lazy" alt="{_esc(article.title, True)}">'

    meta = f'<p class="meta">{status_block(article.confidence_label, date)}</p>'
    heading = f'<h3>{_esc(article.title)}</h3>'
    hook = f'<p class="hook">{_esc(article.hook)}</p>' if tier != "compact" else ""

    if tier == "standard":
        return (
            f'<a class="story standard" href="/a/{slug}">{media}'
            f'<div class="story-body">{meta}{heading}{hook}</div></a>'
        )
    # feature and compact both stack meta/media/heading/hook in document order
    return f'<a class="story {tier}" href="/a/{slug}">{media}{meta}{heading}{hook}</a>'


def _first_titled_index(items, contact_handle):
    """Index of the first item whose draft parses to a non-empty title, or 0.
    A blank title is easy to shrug off in a dense compact row but not as the
    single full-bleed hero headline on the page — a draft with no heading at
    all (parse_article's own fallback has nothing to promote, e.g. run #207,
    see docs/homepage-feed.md) should drop to a lower tier instead, not sit in
    the hero blank. Falls back to 0 if nothing in the batch has a title —
    still shows a hero (with an empty headline) rather than none at all."""
    for i, it in enumerate(items):
        parsed = _parsed(it, contact_handle)
        if parsed and parsed[0].title:
            return i
    return 0


def render_feed(items, contact_handle, channel_url=""):
    """items: rows from shared.db.get_feed_items(), newest first. The first
    item with a usable title renders as the hero; everything else (including
    any title-less item skipped over) is tiered by confidence below it."""
    channel_line = ""
    if channel_url:
        channel_line = (
            f'\n  <a class="channel" href="{_esc(channel_url, True)}">'
            f'Join the Telegram channel &rarr;</a>'
        )
    if not items:
        return _PAGE.format(base_css=BASE_CSS, header=header(), body='<p class="empty">First stories coming soon.</p>', channel_line=channel_line)

    hero_idx = _first_titled_index(items, contact_handle)
    hero_html = _hero_html(items[hero_idx], contact_handle)
    rest_items = items[:hero_idx] + items[hero_idx + 1:]
    rest = [s for s in (_story_html(i, contact_handle) for i in rest_items) if s]

    parts = []
    if hero_html:
        parts.append(hero_html)
    if rest:
        parts.append('<h2 class="section-label">More reporting</h2>')
        parts.append('<div class="feed">\n' + "\n".join(rest) + "\n</div>")
    body = "\n".join(parts) if parts else '<p class="empty">First stories coming soon.</p>'
    return _PAGE.format(base_css=BASE_CSS, header=header(), body=body, channel_line=channel_line)
