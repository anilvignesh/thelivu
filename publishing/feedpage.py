"""Render the public homepage: an editorial feed, not a repeated card grid.

The newest story runs as a full-bleed hero with scroll-scrubbed media (the
actual "scrollytelling" mechanic — motion tied to scroll position, not a
one-shot fade-in). Everything after it is tiered by Thelivu's own confidence
signal instead of one uniform card: Confirmed stories run wide and full
treatment, Developing stories run standard, Contested stories run compact and
text-forward. That tiering is the point — it's Thelivu's actual editorial
model made visible in the layout, not decoration borrowed from a template.

This replaces the flat link list as the *real* homepage for organic/direct
visitors and shared article links. `/bio` (publishing/biopage.py) is untouched
and keeps serving the minimal, self-contained link list Instagram's in-app
browser opens from the bio tap — the two are deliberately different pages for
different readers now. See docs/homepage-feed.md.

Self-contained except two same-origin, self-hosted GSAP files served from
publishing/static/ via the /static/ route in fileserver.py — no third-party
CDN, matching this project's own no-external-host stance (see articlepage.py's
note on why Telegraph was dropped for article hosting). No new font assets
either: display headlines use the system sans stack (bold, tight tracking),
body copy stays the existing Georgia serif — a standard editorial pairing,
zero extra weight to self-host. Progressive enhancement throughout: every
section is fully visible and readable with no JS at all; GSAP only layers
scroll motion on top (the hero's zoom-settle degrades to a static, still-
uncropped image), and reel previews only autoplay (muted, in place) if
IntersectionObserver is available.
"""
import html

from publishing.articlepage import make_slug
from publishing.parser import parse_article, prepare_for_publish

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
  :root {{
    --bg: #E6DCC3; --fg: #1B1710; --accent: #8C2A1B; --line: rgba(27,23,16,.25);
    --card-bg: rgba(27,23,16,.03); --pill-bg: rgba(27,23,16,.06);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17140D; --fg: #E9E0C8; --accent: #D2AA6D; --line: rgba(233,224,200,.25);
      --card-bg: rgba(233,224,200,.04); --pill-bg: rgba(233,224,200,.08);
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ background: var(--bg); }}
  body {{
    background: var(--bg); color: var(--fg);
    font-family: Georgia, 'Times New Roman', serif;
    max-width: 44rem; margin: 0 auto; padding: 2.5rem 1.25rem 3.5rem;
  }}
  .display {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-weight: 700; letter-spacing: -.02em;
  }}
  header {{ text-align: center; margin-bottom: 3rem; }}
  h1 {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: 1.6rem; letter-spacing: .35em; text-indent: .35em;
    text-transform: uppercase; font-weight: 400;
  }}
  .rule {{ border: none; border-top: 2px dashed var(--accent); margin: 1rem auto; width: 6rem; }}
  .tagline {{ font-style: italic; font-size: .95rem; opacity: .8; }}
  .channel {{
    display: inline-block; margin-top: .6rem;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .9rem; color: var(--accent); text-decoration: none;
    border-bottom: 1px dashed var(--accent); padding-bottom: .1rem;
  }}
  a.story {{ display: block; color: var(--fg); text-decoration: none; }}

  /* Pill meta line — shared by every tier */
  .meta {{
    display: inline-flex; align-items: center; gap: .4rem;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .74rem; letter-spacing: .02em; text-transform: uppercase;
    background: var(--pill-bg); border-radius: 99px; padding: .3rem .7rem;
    margin-bottom: .7rem;
  }}

  /* Hero — the newest story, full-bleed, scroll-scrubbed media */
  .hero {{ margin-bottom: 3.5rem; }}
  .hero-media-wrap {{
    width: 100vw; margin-left: calc(50% - 50vw); overflow: hidden;
    max-height: 62vh; background: var(--line);
  }}
  .hero-media {{
    display: block; width: 100%; max-height: 62vh; object-fit: cover;
    transform: scale(1.08); will-change: transform;
  }}
  .hero-body {{ padding-top: 1.4rem; }}
  .hero h2 {{ font-size: clamp(1.6rem, 5vw, 2.4rem); line-height: 1.12; margin-bottom: .7rem; }}
  .hero p {{ font-size: 1.08rem; line-height: 1.55; opacity: .88; max-width: 38rem; }}

  /* Section label between hero and the rest */
  .section-label {{
    display: flex; align-items: center; gap: .8rem; margin: 0 0 1.6rem;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .78rem; letter-spacing: .18em; text-transform: uppercase; opacity: .65;
  }}
  .section-label::after {{ content: ""; flex: 1; border-top: 1px dashed var(--line); }}

  .feed {{ display: flex; flex-direction: column; gap: 2rem; }}

  /* Feature tier — Confirmed: wide media, prominent */
  .story.feature {{ border-bottom: 2px solid var(--line); padding-bottom: 2rem; }}
  .story.feature .story-media {{
    display: block; width: 100%; max-height: 20rem; object-fit: cover;
    background: var(--line); margin-bottom: 1rem;
  }}
  .story.feature h3 {{ font-size: 1.4rem; line-height: 1.25; margin-bottom: .5rem; }}
  .story.feature p.hook {{ font-size: 1rem; line-height: 1.5; opacity: .88; }}

  /* Standard tier — Developing: smaller media, same info */
  .story.standard {{ display: flex; gap: 1rem; align-items: flex-start; }}
  .story.standard .story-media {{
    width: 7rem; height: 7rem; flex: none; object-fit: cover; background: var(--line);
  }}
  .story.standard .story-body {{ min-width: 0; }}
  .story.standard h3 {{ font-size: 1.1rem; line-height: 1.3; margin-bottom: .35rem; }}
  .story.standard p.hook {{ font-size: .92rem; line-height: 1.45; opacity: .85; }}

  /* Compact tier — Contested: dense, text-forward, no media */
  .story.compact {{
    display: block; padding: .9rem 1rem; border: 1px solid var(--line);
  }}
  .story.compact h3 {{ font-size: .98rem; line-height: 1.3; }}
  .story.compact .meta {{ margin-bottom: .4rem; }}

  a.story:hover h3 {{ color: var(--accent); }}

  .empty {{ text-align: center; font-style: italic; opacity: .7; padding: 3rem 0; }}
  footer {{
    margin-top: 3rem; text-align: center; font-size: .8rem; opacity: .6;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
  }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Thelivu</h1>
  <hr class="rule">
  <p class="tagline">Verification-first &middot; human-reviewed</p>{channel_line}
</header>
{body}
<footer>every story fact-checked before it reaches you &middot; <a href="/bio">link in bio</a></footer>
<script src="/static/gsap.min.js"></script>
<script src="/static/ScrollTrigger.min.js"></script>
<script>
(function() {{
  if (!window.gsap || !window.ScrollTrigger) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  gsap.registerPlugin(ScrollTrigger);
  var hero = document.querySelector('.hero-media');
  if (hero) {{
    gsap.to(hero, {{
      scale: 1, ease: 'none',
      scrollTrigger: {{trigger: '.hero', start: 'top top', end: 'bottom top', scrub: true}}
    }});
  }}
  gsap.utils.toArray('.story').forEach(function(el) {{
    gsap.fromTo(el, {{opacity: 0, y: 24}}, {{
      opacity: 1, y: 0, duration: .6, ease: 'power2.out',
      scrollTrigger: {{trigger: el, start: 'top 90%'}}
    }});
  }});
}})();
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
            f'<div class="hero-media-wrap"><video class="hero-media" muted loop playsinline '
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
        f'<p class="meta">{article.confidence_emoji} {_esc(article.confidence_label)} &middot; {date}</p>'
        f'<h2 class="display">{_esc(article.title)}</h2>'
        f'<p>{_esc(article.hook)}</p>'
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
            f'<video class="story-media" muted loop playsinline preload="metadata">'
            f'<source src="{url}" type="video/mp4"></video>'
        )
    elif tier != "compact" and kind == "img":
        media = f'<img class="story-media" src="{url}" loading="lazy" alt="{_esc(article.title, True)}">'

    meta = f'<p class="meta">{article.confidence_emoji} {_esc(article.confidence_label)} &middot; {date}</p>'
    heading = f'<h3 class="display">{_esc(article.title)}</h3>'
    hook = f'<p class="hook">{_esc(article.hook)}</p>' if tier != "compact" else ""

    if tier == "standard":
        return (
            f'<a class="story standard" href="/a/{slug}">{media}'
            f'<div class="story-body">{meta}{heading}{hook}</div></a>'
        )
    # feature and compact both stack meta/media/heading/hook in document order
    return f'<a class="story {tier}" href="/a/{slug}">{media}{meta}{heading}{hook}</a>'


def render_feed(items, contact_handle, channel_url=""):
    """items: rows from shared.db.get_feed_items(), newest first. The first
    renders as the hero; the rest are tiered by confidence below it."""
    channel_line = ""
    if channel_url:
        channel_line = (
            f'\n  <a class="channel" href="{_esc(channel_url, True)}">'
            f'Join the Telegram channel &rarr;</a>'
        )
    if not items:
        return _PAGE.format(body='<p class="empty">First stories coming soon.</p>', channel_line=channel_line)

    hero_html = _hero_html(items[0], contact_handle)
    rest = [s for s in (_story_html(i, contact_handle) for i in items[1:]) if s]

    parts = []
    if hero_html:
        parts.append(hero_html)
    if rest:
        parts.append('<h2 class="section-label">More reporting</h2>')
        parts.append('<div class="feed">\n' + "\n".join(rest) + "\n</div>")
    body = "\n".join(parts) if parts else '<p class="empty">First stories coming soon.</p>'
    return _PAGE.format(body=body, channel_line=channel_line)
