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
  .mast h1 {{ text-align: center; color: var(--accent); line-height: 1; font-weight: 800; }}
  .mast h1 a {{ color: inherit; text-decoration: none; display: flex; flex-direction: column; align-items: center; gap: .5rem; }}
  .mast .ml {{ font-family: 'Noto Sans Malayalam', 'Manjari', 'Malayalam MN', 'Kartika', 'Nirmala UI', var(--sans); font-weight: 800;
    font-size: clamp(3.4rem, 11vw, 7.5rem); line-height: 1.25; letter-spacing: 0; }}
  .mast .en {{ font-family: var(--sans); font-weight: 600; font-size: clamp(.95rem, 2.2vw, 1.4rem); letter-spacing: .5em;
    text-transform: uppercase; padding-left: .5em; color: var(--fg); }}
  .nav {{ display: flex; gap: 1.25rem; flex-wrap: wrap; justify-content: center; }}
  .navlink {{ color: var(--accent); font-weight: 700; text-decoration: none; letter-spacing: .04em; }}
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

  .pager {{ display: flex; justify-content: center; gap: 1rem; margin-top: 2.5rem; font-family: var(--sans); }}
  .pager a {{ font-weight: 700; font-size: .9rem; padding: .7rem 1.4rem; border: 1.5px solid var(--accent); color: var(--accent);
    text-decoration: none; transition: background 160ms ease, color 160ms ease, transform 160ms var(--ease-out); }}
  .pager a:active {{ transform: scale(.97); }}
  @media (hover: hover) and (pointer: fine) {{ .pager a:hover {{ background: var(--accent); color: var(--on-accent); }} }}
  .cover {{ background: linear-gradient(160deg, var(--panel), var(--line)); border-top: 4px solid var(--accent); overflow: hidden; }}
  .cover svg {{ display: block; width: 100%; height: 100%; transition: transform 500ms var(--ease-out); }}
  .cover .ln {{ fill: var(--fg); opacity: .22; }}
  .cover .rd {{ fill: var(--fg); opacity: .82; }}
  .cover .hl {{ fill: var(--accent); opacity: .9; }}
  .cover .st {{ fill: none; stroke: var(--accent); stroke-width: 1.4; opacity: .95; }}
  .cover .st.thin {{ stroke-width: .5; }}
  .cover .stt {{ fill: var(--accent); font: 800 3.1px var(--sans); letter-spacing: .08em; }}
  .cover .ghost {{ font: 800 30px 'Noto Sans Malayalam', 'Manjari', 'Malayalam MN', 'Kartika', 'Nirmala UI', var(--sans);
    fill: var(--accent); opacity: .13; }}
  .cover-contested {{ border-top-color: var(--alert); }}
  .cover-contested .st {{ stroke: var(--alert); }}
  .cover-contested .hl, .cover-contested .stt {{ fill: var(--alert); }}
  .story-media-wrap.cover {{ aspect-ratio: 16 / 10; }}
  .story.feature .story-media-wrap.cover {{ aspect-ratio: 16 / 8; }}
  @media (hover: hover) and (pointer: fine) {{ .story:hover .cover svg, .hero:hover .cover svg {{ transform: scale(1.04); }} }}

  /* The lead sits on an ink panel: the one dark block on the page, so the eye lands there first */
  .hero {{ --ink: #1B1710; background: var(--ink); color: #EFE5CB; padding: clamp(1rem, 2vw, 1.75rem); }}
  @media (prefers-color-scheme: dark) {{ .hero {{ --ink: #241F14; }} }}
  .hero .hook {{ color: rgba(239,229,203,.78); }}
  .hero .when {{ color: rgba(239,229,203,.7); }}
  .hero .status.developing {{ color: #D2AA6D; border-color: #D2AA6D; }}
  .hero .status.confirmed {{ background: #D2AA6D; border-color: #D2AA6D; color: #1B1710; }}
  .hero .cover {{ background: linear-gradient(160deg, #2A2418, #1B1710); border-top-color: #D2AA6D; }}
  .hero .cover .ln {{ fill: #EFE5CB; opacity: .22; }}
  .hero .cover .rd {{ fill: #EFE5CB; opacity: .8; }}
  .hero .cover .hl, .hero .cover .ghost, .hero .cover .stt {{ fill: #D2AA6D; }}
  .hero .cover .st {{ stroke: #D2AA6D; }}
  @media (hover: hover) and (pointer: fine) {{ a.hero:hover h2 {{ color: #D2AA6D; }} }}
.sentinel {{ height: 3rem; margin-top: 1.5rem; }}
  .sentinel.loading {{ background: linear-gradient(90deg, transparent, var(--line), transparent) 0 50% / 40% 2px no-repeat;
    animation: sweep 1s linear infinite; }}
  @keyframes sweep {{ from {{ background-position: -40% 50%; }} to {{ background-position: 140% 50%; }} }}
  .end {{ text-align: center; margin-top: 2.5rem; font: 600 .78rem var(--sans); letter-spacing: .2em; text-transform: uppercase; color: var(--dim); }}
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
<footer>Every story fact-checked before it reaches you &middot; <a href="/sources">our sources</a>{footer_social} &middot; <a href="/bio">link in bio</a></footer>
<script>
(function() {{
  document.documentElement.classList.add('js');
  var bar = document.querySelector('.minibar'), mast = document.querySelector('.mast');
  if (bar && mast && 'IntersectionObserver' in window) {{
    new IntersectionObserver(function(e) {{ bar.classList.toggle('show', !e[0].isIntersecting); }}).observe(mast);
  }}
  var ro, rev = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {{
    ro = new IntersectionObserver(function(es) {{
      es.forEach(function(e) {{ if (e.isIntersecting) {{ e.target.classList.add('in'); ro.unobserve(e.target); }} }});
    }}, {{rootMargin: '0px 0px -8% 0px'}});
    rev.forEach(function(r, i) {{ r.style.transitionDelay = (i % 4) * 60 + 'ms'; ro.observe(r); }});
  }} else {{ rev.forEach(function(r) {{ r.classList.add('in'); }}); }}
  setTimeout(function() {{ rev.forEach(function(r) {{ r.classList.add('in'); }}); }}, 2500);
  var feed = document.querySelector('.feed'), nextLink = document.querySelector('.pager a[rel=next]');
  var fl = document.querySelector('.filters');
  function applyFilter(st) {{
    var on = fl && fl.querySelector('.chip[aria-pressed=true]');
    st.hidden = !!on && on.dataset.f !== 'all' && st.dataset.status !== on.dataset.f;
  }}
  function recount() {{
    if (!fl) return;
    var all = document.querySelectorAll('.feed .story');
    fl.querySelectorAll('.chip').forEach(function(c) {{
      var n = c.dataset.f === 'all' ? all.length : document.querySelectorAll('.feed .story[data-status="' + c.dataset.f + '"]').length;
      c.querySelector('.n').textContent = n;
    }});
  }}
  /* infinite scroll: each page is still a real /?page=N URL (crawlers, no-JS), this just fetches the next one early */
  if (feed && nextLink && 'IntersectionObserver' in window && window.fetch) {{
    var pager = nextLink.closest('.pager'), busy = false;
    var sentinel = document.createElement('div'); sentinel.className = 'sentinel'; sentinel.setAttribute('aria-hidden', 'true');
    pager.parentNode.insertBefore(sentinel, pager);
    nextLink.hidden = true;  // hide only the Older link; Newer stays so a deep link can always get back
    var more = new IntersectionObserver(function(es) {{ if (es[0].isIntersecting) loadMore(); }}, {{rootMargin: '0px 0px 900px 0px'}});
    function done() {{
      more.disconnect(); sentinel.className = 'end'; sentinel.removeAttribute('aria-hidden'); sentinel.textContent = 'You are up to date';
    }}
    function loadMore() {{
      if (busy || !nextLink) return;
      busy = true; sentinel.className = 'sentinel loading';
      fetch(nextLink.getAttribute('href'), {{credentials: 'same-origin'}}).then(function(r) {{
        if (!r.ok) throw 0; return r.text();
      }}).then(function(t) {{
        var d = new DOMParser().parseFromString(t, 'text/html');
        d.querySelectorAll('.feed .story').forEach(function(n) {{
          n = document.importNode(n, true); applyFilter(n); feed.appendChild(n);
          if (ro) ro.observe(n); else n.classList.add('in');
        }});
        recount();
        nextLink = d.querySelector('.pager a[rel=next]');
        if (!nextLink) done();
      }}).catch(function() {{ nextLink.hidden = false; more.disconnect(); }})
        .then(function() {{
          busy = false;
          if (nextLink) {{ sentinel.className = 'sentinel'; more.unobserve(sentinel); more.observe(sentinel); }}  // re-arm: fires again if still in range
        }});
    }}
    more.observe(sentinel);
  }}

  if (fl) {{
    fl.hidden = false;
    fl.addEventListener('click', function(ev) {{
      var b = ev.target.closest('.chip'); if (!b) return;
      fl.querySelectorAll('.chip').forEach(function(c) {{ c.setAttribute('aria-pressed', c === b ? 'true' : 'false'); }});
      document.querySelectorAll('.feed .story').forEach(function(st) {{
        applyFilter(st);
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
    stamp = item.get("published_at") or item.get("updated_at")
    date = str(stamp)[:10] if stamp else ""
    return article, slug, date or "recently"


def _media_url(item):
    """(tag, url) — 'video'/'img'/None. None means no media exists for this story."""
    if item.get("reel_id"):
        return "video", f'/reel/{item["reel_id"]}.mp4'
    if item.get("carousel_id"):
        return "img", f'/carousel_{item["carousel_id"]}_1.jpg'
    return None, None


def _cover(label, cls, seed=0):
    """Generated 'dossier' art for a story with no reel or carousel: ruled document lines, some blacked out, one
    highlighted claim, a status stamp, the Malayalam wordmark ghosted behind. Seeded by the story id so each story gets its
    own stable composition. Theme colours come from CSS variables; decorative only (the headline carries the meaning)."""
    import random
    r = random.Random(seed * 7919 + 13)
    rows, hl = [], r.randrange(2, 7)
    for i in range(9):
        y = 11 + i * 9.2
        w = r.randint(48, 128)
        kind = "hl" if i == hl else ("rd" if r.random() < .28 else "ln")
        rows.append(f'<rect class="{kind}" x="10" y="{y:.1f}" width="{w}" height="4.2" rx="1"/>')
        if kind == "ln" and r.random() < .5:
            rows.append(f'<rect class="ln" x="{10 + w + 4}" y="{y:.1f}" width="{r.randint(8, 22)}" height="4.2" rx="1"/>')
    cx, cy, rot = r.randint(112, 140), r.randint(58, 82), r.randint(-22, 14)
    stamp = (f'<g transform="rotate({rot} {cx} {cy})"><circle class="st" cx="{cx}" cy="{cy}" r="19"/>'
             f'<circle class="st thin" cx="{cx}" cy="{cy}" r="15.5"/>'
             f'<text class="stt" x="{cx}" y="{cy + 2.2}" text-anchor="middle">{_esc(label.upper())}</text></g>')
    svg = (f'<svg viewBox="0 0 160 100" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" focusable="false">'
           f'<text class="ghost" x="6" y="88" lang="ml">തെളിവ്</text>{"".join(rows)}{stamp}</svg>')
    return f'<div class="{cls} cover cover-{_esc(label.lower(), True)}" aria-hidden="true">{svg}</div>'


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
            f'preload="metadata" controls><source src="{url}#t=0.1" type="video/mp4"></video></div>'
        )
    elif kind == "img":
        media = (
            f'<div class="hero-media-wrap"><img class="hero-media" src="{url}" '
            f'alt="{_esc(article.title, True)}"></div>'
        )
    if not media:
        media = _cover(article.confidence_label, "hero-media-wrap", item.get("id") or 0)
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
            f'<div class="story-media-wrap"><video class="story-media" muted loop playsinline autoplay preload="metadata">'
            f'<source src="{url}#t=0.1" type="video/mp4"></video></div>'
        )
    elif tier != "compact" and kind == "img":
        media = f'<div class="story-media-wrap"><img class="story-media" src="{url}" loading="lazy" alt="{_esc(article.title, True)}"></div>'

    if not media and tier != "compact":
        media = _cover(article.confidence_label, "story-media-wrap", item.get("id") or 0)
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


def _lead_index(items, contact_handle, window=6):
    """The lead: the newest titled story that has media among the first `window`, so the top of the page is never a
    blank panel when a nearby story has a video or image. Falls back to the newest titled story."""
    first = _first_titled_index(items, contact_handle)
    for i, it in enumerate(items[:window]):
        kind, _ = _media_url(it)
        if kind and (i == first or (_parsed(it, contact_handle) or [None])[0] and _parsed(it, contact_handle)[0].title):
            return i
    return first


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


def _pager(page, has_more):
    links = []
    if page > 1:
        links.append(f'<a href="{"/" if page == 2 else f"/?page={page - 1}"}">&larr; Newer</a>')
    if has_more:
        links.append(f'<a rel="next" href="/?page={page + 1}">Older stories &rarr;</a>')
    return f'<nav class="pager">{" ".join(links)}</nav>' if links else ""


def _footer_social(socials):
    return "".join(f' &middot; <a href="{_esc(u, True)}" rel="noopener">{_esc(n)}</a>' for n, u in socials)


def _masthead(channel_url, socials=()):
    import datetime
    today = datetime.date.today().strftime("%A, %d %B %Y")
    social_links = "".join(f'<a class="navlink" href="{_esc(u, True)}" rel="noopener">{_esc(n)}</a>' for n, u in socials)
    return (
        f'<header class="mast"><div class="mast-top"><span class="dateline">{today}</span><span class="nav"><a class="navlink" href="/sources">Our sources</a>{social_links}</span></div>'
        f'<h1><a href="/"><span class="ml" lang="ml">തെളിവ്</span><span class="en">Thelivu</span></a></h1>'
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


def render_feed(items, contact_handle, channel_url="", page=1, has_more=False, socials=()):
    """items: rows from shared.db.get_feed_items(), newest first. The first item with a usable title is the lead; the next
    four fill the Latest rail beside it; everything after is a card grid tiered by confidence."""
    mast = _masthead(channel_url, socials)
    pager = _pager(page, has_more)
    empty = '<p class="empty">First stories coming soon.</p>'
    if not items:
        return _PAGE.format(base_css=BASE_CSS, footer_social=_footer_social(socials), masthead=mast, body=empty)

    if page > 1:  # later pages are just the grid, no lead or rail
        grid = [g for g in (_story_html(i, contact_handle) for i in items) if g]
        body = (f'<a class="backlink" href="/">&larr; Latest stories</a><h2 class="section-label">Older &middot; page {page}</h2><div class="feed">\n' + "\n".join(grid) + "\n</div>" + pager) if grid else empty
        return _PAGE.format(base_css=BASE_CSS, footer_social=_footer_social(socials), masthead=mast, body=body)

    hero_idx = _lead_index(items, contact_handle)
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
    return _PAGE.format(base_css=BASE_CSS, footer_social=_footer_social(socials), masthead=mast, body="\n".join(parts) + pager if parts else empty)
