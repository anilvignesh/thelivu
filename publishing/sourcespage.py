"""Render the public /sources page: where Thelivu's claims come from.

Two lists, names and links only: public records we read directly (the digger's active targets), and the news feeds we
monitor. Internal editorial metadata (lean, notes, role, handles) is never selected. Same look as the homepage.
"""
import html
from urllib.parse import urlsplit

from publishing.sitestyle import BASE_CSS, header

_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sources &mdash; Thelivu</title>
<meta name="description" content="The public records and news feeds Thelivu reads before it reports.">
<style>
{base_css}
  body {{ max-width: 56rem; margin: 0 auto; padding: 1.75rem 1.25rem 3.5rem; }}
  h1 {{ font-size: clamp(2rem, 6vw, 3.2rem); line-height: 1.05; margin-bottom: .75rem; }}
  .lede {{ font-size: 1.15rem; line-height: 1.55; color: var(--dim); max-width: 40rem; margin-bottom: 2.5rem; }}
  h2 {{ font-size: .78rem; letter-spacing: .2em; text-transform: uppercase; color: var(--accent); margin: 2.5rem 0 .25rem; }}
  .count {{ color: var(--dim); font-family: var(--sans); font-size: .85rem; margin-bottom: .75rem; }}
  ul {{ list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); gap: 0 2rem; }}
  li {{ border-top: 1px solid var(--line); padding: .8rem 0; }}
  li a, li span.n {{ font-family: var(--sans); font-weight: 700; color: var(--fg); text-decoration: none; display: block; }}
  li small {{ display: block; color: var(--dim); font-family: var(--sans); font-size: .8rem; margin-top: .15rem; overflow-wrap: anywhere; }}
  @media (hover: hover) and (pointer: fine) {{ li a:hover {{ color: var(--accent); }} }}
  .back {{ display: inline-block; margin-top: 3rem; font: 700 .9rem var(--sans); color: var(--accent); }}
</style></head><body>
{header}
<h1>Where our claims come from</h1>
<p class="lede">Every story is checked against primary sources before it is published. These are the ones we read.</p>
<h2>Public records</h2><p class="count">{n_records} sources read directly: government, audit and court documents.</p>
<ul>{records}</ul>
<h2>News feeds we monitor</h2><p class="count">{n_feeds} feeds that point us to stories. A feed is a lead, never proof.</p>
<ul>{feeds}</ul>
<a class="back" href="/">&larr; Latest stories</a>
</body></html>
"""


def _host(url):
    try:
        return urlsplit(url).netloc.removeprefix("www.")
    except ValueError:
        return ""


def render(sources):
    esc = html.escape
    records = "".join(
        f'<li><a href="{esc(r["url"], True)}" rel="noopener">{esc(r["name"])}</a><small>{esc(_host(r["url"]))}</small></li>'
        for r in sources["records"] if str(r["url"]).startswith(("http://", "https://")))
    feeds = "".join(
        f'<li><span class="n">{esc(f["name"])}</span>' + (f'<small>{esc(f["platform"])}</small>' if f["platform"] else "") + "</li>"
        for f in sources["feeds"])
    return _PAGE.format(base_css=BASE_CSS, header=header(), records=records or "<li>None listed yet.</li>",
                        feeds=feeds or "<li>None listed yet.</li>",
                        n_records=len(sources["records"]), n_feeds=len(sources["feeds"]))
