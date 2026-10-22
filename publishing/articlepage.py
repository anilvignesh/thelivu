"""Render a published article as a self-hosted web page.

Telegraph was the article host until Indian ISPs made Telegram-owned domains
unreachable (t.me doesn't resolve, telegra.ph connection-resets — tested
2026-07-14). Articles are served from our own Railway domain instead, at
/a/<run_id>-<kebab-headline>, rendered per request from the approved draft in
pipeline_runs — see docs/article-hosting.md.

Consumes the same neutral blocks as every other renderer (publishing.parser);
palette mirrors the bio page and the slides. Self-contained HTML, mobile-first,
readable inside Instagram's in-app browser, except two same-origin self-hosted
GSAP files (see publishing/static/, served by the /static/ route in
fileserver.py) that add a reading-progress bar and scroll-reveal on the
illustrated slide figures interleaved through the piece — see render_article's
`slides` param. No third-party CDN. Progressive enhancement: every block and
figure is fully visible with no JS at all.
"""
import html
import re

from publishing.sitestyle import BASE_CSS, header, status_block

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


# What the reader sees at the head of a callout. Fixed per kind so it reads as a
# label the site always uses, not as something this particular piece decided to
# say about itself.
_CALLOUT_TITLE = {"VIEW": "A view from the record — "}


def _slide_figure(slide):
    """One illustrated-carousel slide, interleaved into the article body as a
    scroll-reveal figure. `slide`: a row from
    shared.db.get_carousel_slides_for_run() — position, headline, image_url."""
    headline = slide.get("headline") or ""
    caption = f"<figcaption>{_inline(headline)}</figcaption>" if headline else ""
    return (
        f'<figure class="slide-figure" data-reveal>'
        f'<img src="{html.escape(slide["image_url"], quote=True)}" loading="lazy" '
        f'alt="{html.escape(headline, quote=True)}">{caption}</figure>'
    )


def _blocks_to_html(blocks, slides=None):
    out = []
    # Slides space out evenly through the piece rather than clumping at the
    # top — position 1 is the carousel's cover/hook slide, skipped here as
    # redundant with the article's own H1. Whatever's left over (a piece
    # shorter than expected) lands at the end rather than being dropped.
    remaining = [s for s in (slides or []) if s.get("position", 1) != 1]
    step = max(2, len(blocks) // (len(remaining) + 1)) if remaining else 0
    next_slide_at = step
    for i, b in enumerate(blocks):
        if b.type == "heading":
            lvl = min(max(b.level, 2), 4)  # the H1 slot belongs to the title
            out.append(f"<h{lvl}>{_inline(b.text)}</h{lvl}>")
        elif b.type == "blockquote":
            out.append(f"<blockquote>{_inline(b.text)}</blockquote>")
        elif b.type == "callout":
            # The shape-B view label. Deliberately not a blockquote: it is a
            # statement about the piece, and a reader skimming must register it
            # as furniture rather than as a nicely-set line from the story.
            out.append(f'<aside class="callout"><b>{_CALLOUT_TITLE.get(b.kind, b.kind)}</b>'
                       f"{_inline(b.text)}</aside>")
        elif b.type == "list":
            items = "".join(f"<li>{_inline(i)}</li>" for i in b.items)
            out.append(f"<ul>{items}</ul>")
        elif b.type == "rule":
            out.append("<hr>")
        else:
            out.append(f"<p>{_inline(b.text)}</p>")
        if remaining and i + 1 == next_slide_at:
            out.append(_slide_figure(remaining.pop(0)))
            next_slide_at += step
    for s in remaining:  # piece was shorter than the step math assumed
        out.append(_slide_figure(s))
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
{base_css}
  body {{ max-width: 40rem; margin: 0 auto; padding: 1.75rem 1.25rem 3rem; line-height: 1.65; font-size: 1.08rem; }}
  h1 {{ font-size: clamp(1.7rem, 6vw, 2.3rem); line-height: 1.12; margin-bottom: 1.2rem; }}
  .meta {{ margin-top: .2rem; margin-bottom: 1.1rem; }}
  article > .meta {{ padding-bottom: 0; }}
  h2, h3, h4 {{ margin: 2rem 0 .6rem; line-height: 1.25; }}
  h2 {{ font-size: 1.3rem; }} h3 {{ font-size: 1.12rem; }} h4 {{ font-size: 1rem; }}
  p {{ margin-bottom: 1.1rem; }}
  ul {{ margin: 0 0 1.1rem 1.4rem; }}
  li {{ margin-bottom: .4rem; }}
  /* a quoted source: translucent panel, gold edge — the same panel the reels use for the record's own words */
  blockquote {{
    background: var(--panel); border: 1px solid color-mix(in srgb, var(--accent) 60%, transparent);
    padding: 1.1rem 1.2rem; margin: 1.8rem 0; font-style: normal;
  }}
  /* the view label on a contested-frame piece: outlined, no italics, must not read as a pull-quote */
  aside.callout {{
    border: 2px solid var(--alert); padding: .8rem 1rem; margin: 0 0 1.5rem;
    font-size: .95rem; line-height: 1.5;
  }}
  aside.callout b {{
    font-family: var(--sans); font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; color: var(--alert);
  }}
  hr {{ border: none; border-top: 1px solid var(--line); margin: 2rem 0; }}
  article a {{ color: var(--accent); text-underline-offset: 3px; text-decoration-thickness: 1px; }}
  #reading-progress {{ position: fixed; top: 0; left: 0; height: 3px; width: 0%; background: var(--accent); z-index: 10; }}
  figure.slide-figure {{ margin: 2rem 0; }}
  figure.slide-figure img {{ display: block; width: 100%; }}
  figure.slide-figure figcaption {{ font-family: var(--sans); font-size: .78rem; color: var(--dim); margin-top: .5rem; }}
  footer {{ margin-top: 2.5rem; }}
  footer a {{ font-family: var(--sans); font-size: .85rem; font-weight: 600; color: var(--accent); text-decoration: none; border-bottom: 1.5px solid var(--accent); padding-bottom: .1rem; }}
</style>
</head>
<body>
<div id="reading-progress"></div>
{header}
<article>
<p class="meta">{status}</p>
<h1>{title}</h1>
{body}
</article>
<footer><a href="/">&larr; all Thelivu stories</a></footer>
<script>
(function() {{
  var bar = document.getElementById('reading-progress');
  function update() {{
    var h = document.documentElement, height = h.scrollHeight - h.clientHeight;
    bar.style.width = (height > 0 ? Math.min(100, (h.scrollTop / height) * 100) : 0) + '%';
  }}
  document.addEventListener('scroll', update, {{passive: true}});
  update();
}})();
</script>
<script src="/static/gsap.min.js"></script>
<script src="/static/ScrollTrigger.min.js"></script>
<script>
(function() {{
  if (!window.gsap || !window.ScrollTrigger) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  gsap.registerPlugin(ScrollTrigger);
  gsap.utils.toArray('[data-reveal]').forEach(function(el) {{
    gsap.fromTo(el, {{opacity: 0, y: 10}}, {{
      opacity: 1, y: 0, duration: .35, ease: 'power3.out',
      scrollTrigger: {{trigger: el, start: 'top 90%'}}
    }});
  }});
}})();
</script>
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


def render_article(article, published_at=None, slides=None):
    """article: a publishing.parser.Article from the prepared draft.
    slides: rows from shared.db.get_carousel_slides_for_run(), or None/[] —
    woven into the body as scroll-reveal figures, see _blocks_to_html."""
    date = ""
    if published_at:
        # both TIMESTAMP (postgres) and TEXT (sqlite) arrive stringifiable
        date = str(published_at)[:10]
    return _PAGE.format(
        title=_inline(article.title),
        title_attr=html.escape(article.title, quote=True),
        hook_attr=html.escape(article.hook or "", quote=True),
        base_css=BASE_CSS,
        header=header("Article"),
        status=status_block(article.confidence_label, "Published " + (date or "recently")),
        body=_blocks_to_html(article.blocks, slides),
    )


def render_not_found():
    return _NOT_FOUND