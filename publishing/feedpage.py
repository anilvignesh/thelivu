"""Render the public homepage: a scroll feed of published stories, each with its
illustrated-carousel thumbnail or reel video where one exists.

This replaces the flat link list as the *real* homepage for organic/direct
visitors and shared article links. `/bio` (publishing/biopage.py) is untouched
and keeps serving the minimal, self-contained link list Instagram's in-app
browser opens from the bio tap — the two are deliberately different pages for
different readers now. See docs/homepage-feed.md.

Self-contained except two same-origin, self-hosted GSAP files served from
publishing/static/ via the /static/ route in fileserver.py — no third-party
CDN, matching this project's own no-external-host stance (see articlepage.py's
note on why Telegraph was dropped for article hosting). Progressive
enhancement throughout: every card is fully visible and readable with no JS at
all; GSAP only layers scroll-reveal motion on top, and reel previews only
autoplay (muted, in place) if IntersectionObserver is available.
"""
import html

from publishing.articlepage import make_slug
from publishing.parser import parse_article, prepare_for_publish


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
    --card-bg: rgba(27,23,16,.03);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17140D; --fg: #E9E0C8; --accent: #D2AA6D; --line: rgba(233,224,200,.25);
      --card-bg: rgba(233,224,200,.04);
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--fg);
    font-family: Georgia, 'Times New Roman', serif;
    max-width: 40rem; margin: 0 auto; padding: 2.5rem 1.25rem 3rem;
  }}
  header {{ text-align: center; margin-bottom: 2.5rem; }}
  h1 {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: 1.6rem; letter-spacing: .35em; text-indent: .35em;
    text-transform: uppercase;
  }}
  .rule {{ border: none; border-top: 2px dashed var(--accent); margin: 1rem auto; width: 6rem; }}
  .tagline {{ font-style: italic; font-size: .95rem; opacity: .8; }}
  .channel {{
    display: inline-block; margin-top: .6rem;
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .9rem; color: var(--accent); text-decoration: none;
    border-bottom: 1px dashed var(--accent); padding-bottom: .1rem;
  }}
  .feed {{ display: flex; flex-direction: column; gap: 1.6rem; }}
  a.card {{
    display: block; border: 2px solid var(--line); background: var(--card-bg);
    color: var(--fg); text-decoration: none; overflow: hidden;
  }}
  a.card:hover {{ border-color: var(--accent); }}
  .card-media {{ display: block; width: 100%; max-height: 22rem; object-fit: cover; background: var(--line); }}
  .card-body {{ padding: 1.1rem 1.2rem 1.3rem; }}
  .card-meta {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .78rem; opacity: .75; margin-bottom: .5rem;
  }}
  .card h2 {{ font-size: 1.2rem; line-height: 1.3; margin-bottom: .5rem; }}
  .card p {{ font-size: .95rem; line-height: 1.5; opacity: .9; }}
  .empty {{ text-align: center; font-style: italic; opacity: .7; padding: 3rem 0; }}
  footer {{
    margin-top: 2.5rem; text-align: center; font-size: .8rem; opacity: .6;
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
  gsap.utils.toArray('.card').forEach(function(card) {{
    gsap.fromTo(card, {{opacity: 0, y: 26}}, {{
      opacity: 1, y: 0, duration: .6, ease: 'power2.out',
      scrollTrigger: {{trigger: card, start: 'top 90%'}}
    }});
  }});
}})();
(function() {{
  var vids = document.querySelectorAll('video.card-media');
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


def _card_html(item, contact_handle):
    """One feed card, or None if the run's draft couldn't be parsed (skipped,
    not fatal — one bad row must not break the whole homepage)."""
    try:
        article = parse_article(prepare_for_publish(item["draft_text"], contact_handle))
    except Exception:
        return None

    slug = item.get("slug") or make_slug(item["id"], article.title)
    date = str(item["updated_at"])[:10] if item.get("updated_at") else ""

    if item.get("reel_id"):
        media = (
            f'<video class="card-media" muted loop playsinline preload="metadata" controls>'
            f'<source src="/reel/{item["reel_id"]}.mp4" type="video/mp4"></video>'
        )
    elif item.get("carousel_id"):
        thumb = f'/carousel_{item["carousel_id"]}_1.jpg'
        media = f'<img class="card-media" src="{thumb}" loading="lazy" alt="{_esc(article.title, True)}">'
    else:
        media = ""

    return (
        f'<a class="card" href="/a/{slug}">{media}'
        f'<div class="card-body">'
        f'<p class="card-meta">{article.confidence_emoji} {_esc(article.confidence_label)}'
        f' &middot; {date or "recently"}</p>'
        f'<h2>{_esc(article.title)}</h2>'
        f'<p>{_esc(article.hook)}</p>'
        f'</div></a>'
    )


def render_feed(items, contact_handle, channel_url=""):
    """items: rows from shared.db.get_feed_items(), newest first."""
    channel_line = ""
    if channel_url:
        channel_line = (
            f'\n  <a class="channel" href="{_esc(channel_url, True)}">'
            f'Join the Telegram channel &rarr;</a>'
        )
    cards = [c for c in (_card_html(i, contact_handle) for i in items) if c]
    body = (
        '<div class="feed">\n' + "\n".join(cards) + "\n</div>"
        if cards else '<p class="empty">First stories coming soon.</p>'
    )
    return _PAGE.format(body=body, channel_line=channel_line)
