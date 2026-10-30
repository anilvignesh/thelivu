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
  body {{ max-width: 90rem; margin: 0 auto; padding: 1.25rem clamp(1.25rem, 4vw, 3.5rem) 3rem; }}
  a.story, a.rail-item {{ display: block; color: var(--fg); text-decoration: none; }}

  /* Masthead: wide wordmark, dateline, action; newspaper double rule under */
  .mast {{ border-bottom: 4px double var(--line); padding-bottom: 1rem; margin-bottom: 2rem; }}
  .mast-top {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
    font-family: var(--sans); font-size: .78rem; color: var(--dim); padding-bottom: .9rem; }}
  .mast-top .dateline {{ letter-spacing: .08em; text-transform: uppercase; font-weight: 600; }}
  .mast h1 {{ font-size: clamp(2.6rem, 9vw, 6rem); font-weight: 800; letter-spacing: .18em; text-transform: uppercase;
    line-height: 1; text-align: center; color: var(--accent); }}
  .mast h1 a {{ color: inherit; text-decoration: none; }}
  .mast-sub {{ display: flex; justify-content: center; margin-top: .8rem; font-family: var(--sans); font-size: .9rem;
    color: var(--dim); text-align: center; }}
  .channel {{ font-family: var(--sans); font-size: .82rem; font-weight: 700; letter-spacing: .04em; color: var(--on-accent);
    background: var(--accent); text-decoration: none; padding: .45rem .9rem; transition: transform 160ms var(--ease-out); }}
  .channel:active {{ transform: scale(.97); }}

  /* Front page: lead story (wide) beside the Latest rail */
  .front {{ display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(16rem, 1fr); gap: clamp(1.5rem, 3vw, 3rem);
    padding-bottom: 2.5rem; border-bottom: 1px solid var(--line); margin-bottom: 2.5rem; }}
  .hero {{ display: block; color: var(--fg); text-decoration: none; }}
  .hero-media-wrap {{ overflow: hidden; aspect-ratio: 16 / 9; background: var(--line); margin-bottom: 1.25rem; }}
  .hero-media {{ display: block; width: 100%; height: 100%; object-fit: cover; animation: settle 700ms var(--ease-out) both; }}
  @keyframes settle {{ from {{ transform: scale(1.05); opacity: .6; }} to {{ transform: none; opacity: 1; }} }}
  .hero h2 {{ font-size: clamp(2rem, 4.2vw, 3.6rem); line-height: 1.05; margin-bottom: .9rem; }}
  .hero p.hook {{ font-size: clamp(1.1rem, 1.6vw, 1.35rem); line-height: 1.5; color: var(--dim); max-width: 46rem; }}
  .hero.textonly {{ border-top: 6px solid var(--accent); padding-top: 1.25rem; }}

  .rail {{ border-left: 1px solid var(--line); padding-left: clamp(1.25rem, 2.5vw, 2.5rem); }}
  .rail .section-label {{ margin-bottom: .25rem; }}
  .rail-item {{ padding: 1.1rem 0; border-bottom: 1px solid var(--line); transition: transform 160ms var(--ease-out); }}
  .rail-item:last-child {{ border-bottom: 0; }}
  .rail-item:active {{ transform: scale(.985); }}
  .rail-item h3 {{ font-size: 1.15rem; line-height: 1.25; margin-top: .1rem; }}
  .rail-item p.meta {{ margin-bottom: .5rem; }}

  .section-label {{
    display: flex; align-items: center; gap: .8rem; margin: 0 0 1rem;
    font-family: var(--sans); font-size: .78rem; font-weight: 700; letter-spacing: .2em; text-transform: uppercase;
    color: var(--accent);
  }}
  .section-label::after {{ content: ""; flex: 1; border-top: 1px solid var(--line); }}
  .rail .section-label::after {{ display: none; }}

  /* Card grid fills the whole width; Confirmed cards run double-wide */
  .feed {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); gap: 2.25rem clamp(1.25rem, 2.5vw, 2.5rem); }}
  .story {{ border-top: 3px solid var(--line); padding-top: 1rem; }}
  .story.feature {{ grid-column: span 2; border-top-color: var(--accent); }}
  .story.compact {{ border-top-color: var(--alert); }}
  .story h3 {{ margin-bottom: .45rem; font-size: 1.25rem; line-height: 1.2; }}
  .story.feature h3 {{ font-size: 1.7rem; line-height: 1.12; }}
  .story p.hook {{ color: var(--dim); line-height: 1.5; font-size: .98rem; }}
  .story-media {{ display: block; width: 100%; aspect-ratio: 16 / 10; object-fit: cover; }}
  .story.feature .story-media {{ aspect-ratio: 16 / 8; }}


  /* Modern touches: filter chips, hover zoom, scroll reveal, sticky mini-bar */
  .filters {{ display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin: 0 0 1.5rem; font-family: var(--sans); }}
  .chip {{ font: 600 .8rem var(--sans); letter-spacing: .04em; padding: .45rem .9rem; border: 1.5px solid var(--line);
    background: transparent; color: var(--fg); border-radius: 999px; cursor: pointer;
    transition: background 160ms ease, color 160ms ease, border-color 160ms ease, transform 160ms var(--ease-out); }}
  .chip:active {{ transform: scale(.96); }}
  .chip .n {{ opacity: .6; margin-left: .35rem; font-variant-numeric: tabular-nums; }}
  .chip[aria-pressed="true"] {{ background: var(--accent); border-color: var(--accent); color: var(--on-accent); }}
  .story[hidden] {{ display: none; }}
  .story-media-wrap {{ overflow: hidden; margin-bottom: 1rem; background: var(--line); }}
  .story-media-wrap .story-media {{ margin: 0; transition: transform 500ms var(--ease-out); }}
  @media (hover: hover) and (pointer: fine) {{
    .story:hover .story-media, .hero:hover .hero-media {{ transform: scale(1.04); }}
    .story:hover {{ border-top-color: var(--accent); }}
  }}
  .hero-media {{ transition: transform 500ms var(--ease-out); }}
  .js .reveal {{ opacity: 0; transform: translateY(14px); transition: opacity 500ms var(--ease-out), transform 500ms var(--ease-out); }}
  .js .reveal.in {{ opacity: 1; transform: none; }}
  .minibar {{ position: fixed; top: 0; left: 0; right: 0; z-index: 10; background: var(--bg); border-bottom: 1px solid var(--line);
    padding: .55rem clamp(1.25rem, 4vw, 3.5rem); display: flex; justify-content: space-between; align-items: center;
    font-family: var(--sans); transform: translateY(-100%); transition: transform 250ms var(--ease-out); }}
  .minibar.show {{ transform: none; }}
  .minibar a:first-child {{ font-weight: 800; letter-spacing: .2em; text-transform: uppercase; color: var(--accent); text-decoration: none; }}
  .minibar a:last-child {{ font-size: .8rem; font-weight: 700; color: var(--accent); }}

  @media (max-width: 62rem) {{
    .front {{ grid-template-columns: 1fr; }}
    .rail {{ border-left: 0; padding-left: 0; border-top: 1px solid var(--line); padding-top: 1.5rem; }}
    .story.feature {{ grid-column: auto; }}
  }}

  .empty {{ font-style: italic; color: var(--dim); padding: 3rem 0; }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line); font-family: var(--sans); font-size: .78rem; color: var(--dim); }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="minibar" aria-hidden="true"><a href="/">Thelivu</a><a href="#top">Top &uarr;</a></div>
<div id="top"></div>
{masthead}
{body}
<footer>Every story fact-checked before it reaches you &middot; <a href="/bio">link in bio</a></footer>
<script>
(function() {{
  document.documentElement.classList.add('js');
  var bar = document.querySelector('.minibar'), mast = document.querySelector('.mast');
  if (bar && mast && 'IntersectionObserver' in window) {{
    new IntersectionObserver(function(e) {{ bar.classList.toggle('show', !e[0].isIntersecting); }}).observe(mast);
  }}
  var rev = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {{
    var ro = new IntersectionObserver(function(es) {{
      es.forEach(function(e) {{ if (e.isIntersecting) {{ e.target.classList.add('in'); ro.unobserve(e.target); }} }});
    }}, {{rootMargin: '0px 0px -8% 0px'}});
    rev.forEach(function(r, i) {{ r.style.transitionDelay = (i % 4) * 60 + 'ms'; ro.observe(r); }});
  }} else {{ rev.forEach(function(r) {{ r.classList.add('in'); }}); }}
  setTimeout(function() {{ rev.forEach(function(r) {{ r.classList.add('in'); }}); }}, 2500);
  var fl = document.querySelector('.filters');
  if (fl) {{
    fl.hidden = false;
    fl.addEventListener('click', function(ev) {{
      var b = ev.target.closest('.chip'); if (!b) return;
      fl.querySelectorAll('.chip').forEach(function(c) {{ c.setAttribute('aria-pressed', c === b ? 'true' : 'false'); }});
      document.querySelectorAll('.feed .story').forEach(function(st) {{
        st.hidden = b.dataset.f !== 'all' && st.dataset.status !== b.dataset.f;
      }});
    }});
  }}
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
        f'<a class="hero{"" if media else " textonly"}" href="/a/{slug}">{media}'
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
            f'<div class="story-media-wrap"><video class="story-media" muted loop playsinline autoplay preload="metadata">'
            f'<source src="{url}" type="video/mp4"></video></div>'
        )
    elif tier != "compact" and kind == "img":
        media = f'<div class="story-media-wrap"><img class="story-media" src="{url}" loading="lazy" alt="{_esc(article.title, True)}"></div>'

    meta = f'<p class="meta">{status_block(article.confidence_label, date)}</p>'
    heading = f'<h3>{_esc(article.title)}</h3>'
    hook = f'<p class="hook">{_esc(article.hook)}</p>' if tier != "compact" else ""

    status = _esc(article.confidence_label.lower(), True)
    return f'<a class="story reveal {tier}" data-status="{status}" href="/a/{slug}">{media}{meta}{heading}{hook}</a>'


def _rail_html(item, contact_handle):
    """One text-only 'Latest' row beside the lead: status, date, headline."""
    parsed = _parsed(item, contact_handle)
    if not parsed:
        return None
    article, slug, date = parsed
    return (
        f'<a class="rail-item" href="/a/{slug}"><p class="meta">{status_block(article.confidence_label, date)}</p>'
        f'<h3>{_esc(article.title)}</h3></a>'
    )


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


def _masthead(channel_url):
    import datetime
    today = datetime.date.today().strftime("%A, %d %B %Y")
    action = (
        f'<a class="channel" href="{_esc(channel_url, True)}">Join the Telegram channel &rarr;</a>'
        if channel_url else ""
    )
    return (
        f'<header class="mast"><div class="mast-top"><span class="dateline">{today}</span>{action}</div>'
        f'<h1><a href="/">Thelivu</a></h1>'
        f'<p class="mast-sub">Fact-checked &middot; sourced &middot; reviewed. Every claim verified before it reaches you.</p></header>'
    )


def _filters(items, contact_handle):
    """Status filter chips with counts; works only with JS, hidden otherwise (the grid is fully visible without it)."""
    counts = {}
    for it in items:
        p = _parsed(it, contact_handle)
        if p:
            k = p[0].confidence_label.lower()
            counts[k] = counts.get(k, 0) + 1
    if len(counts) < 2:
        return ""
    chips = [f'<button class="chip" type="button" data-f="all" aria-pressed="true">All<span class="n">{sum(counts.values())}</span></button>']
    for k in ("confirmed", "developing", "contested"):
        if k in counts:
            chips.append(f'<button class="chip" type="button" data-f="{k}" aria-pressed="false">{k.title()}<span class="n">{counts[k]}</span></button>')
    return '<div class="filters" role="group" aria-label="Filter by status" hidden>' + "".join(chips) + '</div>'


def render_feed(items, contact_handle, channel_url=""):
    """items: rows from shared.db.get_feed_items(), newest first. The first item with a usable title is the lead; the next
    four fill the Latest rail beside it; everything after is a card grid tiered by confidence."""
    mast = _masthead(channel_url)
    empty = '<p class="empty">First stories coming soon.</p>'
    if not items:
        return _PAGE.format(base_css=BASE_CSS, masthead=mast, body=empty)

    hero_idx = _first_titled_index(items, contact_handle)
    hero_html = _hero_html(items[hero_idx], contact_handle)
    rest_items = items[:hero_idx] + items[hero_idx + 1:]
    rail = [r for r in (_rail_html(i, contact_handle) for i in rest_items[:4]) if r]
    grid = [g for g in (_story_html(i, contact_handle) for i in rest_items[4:]) if g]

    parts = []
    if hero_html or rail:
        rail_html = ('<aside class="rail"><h2 class="section-label">Latest</h2>' + "".join(rail) + '</aside>') if rail else ""
        parts.append(f'<section class="front">{hero_html}{rail_html}</section>')
    if grid:
        parts.append('<h2 class="section-label">More reporting</h2>')
        parts.append(_filters(rest_items[4:], contact_handle))
        parts.append('<div class="feed">\n' + "\n".join(grid) + "\n</div>")
    return _PAGE.format(base_css=BASE_CSS, masthead=mast, body="\n".join(parts) or empty)
