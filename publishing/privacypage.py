"""Render the public privacy policy page — served at /privacy.

Added 2026-09-07, purpose-built as the publicly-reachable privacy policy
Google requires before it will review the YouTube Data API `youtube.upload`
scope for "In production" status (see docs/HANDOFF.md §4a). Static content —
this describes data practices, not per-request data, so unlike the other
pages here it doesn't need a DB read. Same house style as biopage.py.
"""
from shared.config import CONTACT_HANDLE

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy — Thelivu</title>
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
    max-width: 40rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem;
    line-height: 1.6;
  }}
  header {{ text-align: center; margin-bottom: 2rem; }}
  h1 {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: 1.4rem; letter-spacing: .25em; text-indent: .25em;
    text-transform: uppercase;
  }}
  .rule {{
    border: none; border-top: 2px dashed var(--accent);
    margin: 1rem auto 2rem; width: 6rem;
  }}
  h2 {{
    font-family: 'DejaVu Sans Mono', ui-monospace, monospace;
    font-size: .95rem; letter-spacing: .08em; text-transform: uppercase;
    color: var(--accent); margin: 2rem 0 .75rem;
  }}
  p {{ margin-bottom: 1rem; }}
  ul {{ margin: 0 0 1rem 1.25rem; }}
  li {{ margin-bottom: .4rem; }}
  a {{ color: var(--accent); }}
  .updated {{ font-size: .85rem; opacity: .7; font-style: italic; }}
  footer {{
    margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--line);
    font-size: .85rem; text-align: center; opacity: .8;
  }}
</style>
</head>
<body>
<header>
  <h1>Thelivu</h1>
  <hr class="rule">
  <p class="updated">Privacy Policy — last updated 2026-09-07</p>
</header>

<p>Thelivu ("we", "the site") is an independent, verification-first news
publication. This page describes what data we collect, how we use it, and
what happens to it — plainly, because that is the same standard we hold
everyone else to.</p>

<h2>What we collect from readers</h2>
<p>Thelivu does not require an account to read anything published here.
We do not run analytics or advertising trackers, and we do not build reader
profiles. Our web server keeps standard access logs (IP address, requested
page, timestamp, user agent) for operational purposes — diagnosing outages
and abuse — and these are not sold, shared, or used for profiling. They are
retained only as long as needed for that purpose.</p>

<h2>What our YouTube integration does</h2>
<p>Thelivu cross-posts video content we produce (news explainer reels) to
our own YouTube channel via the YouTube Data API. This integration:</p>
<ul>
  <li>Uploads video files we create to the Thelivu YouTube channel only —
      it does not access, read, or modify any other YouTube channel or
      account, and it is never used on a viewer's or a third party's
      behalf.</li>
  <li>Uses the <code>youtube.upload</code> scope to publish our own videos,
      and <code>youtube.readonly</code> solely to read back basic
      performance statistics (views, likes) on videos we ourselves
      uploaded, for our own editorial reporting.</li>
  <li>Stores only an OAuth refresh token for the Thelivu channel's own
      Google account, held as an encrypted environment variable on our
      hosting provider (Railway) — never in application code, never
      committed to source control, and never exposed to any page a reader
      can reach.</li>
  <li>Does not collect, store, or process any data belonging to viewers of
      our YouTube videos, or to any Google account other than the single
      Thelivu channel account that authorized this integration.</li>
</ul>

<h2>Third parties</h2>
<p>We use standard infrastructure providers (hosting, our LLM/AI providers
for research and drafting assistance, image generation, and distribution
APIs for Telegram/Instagram/YouTube) strictly to operate the publication.
None of these relationships involve selling reader data, because we do not
collect reader data to sell in the first place.</p>

<h2>Corrections and editorial practice</h2>
<p>Thelivu publishes transparent-perspective journalism and issues public
corrections when we get something wrong. That practice is described in our
published articles themselves, not this policy — this page is specifically
about data handling, not editorial standards.</p>

<h2>Contact</h2>
<p>Questions about this policy, or a request relating to data we hold about
you, can be sent via {contact}.</p>

<h2>Changes to this policy</h2>
<p>If our data practices change materially, this page will be updated and
the "last updated" date above will change accordingly.</p>

<footer>Thelivu</footer>
</body>
</html>"""


def render():
    return _PAGE.format(contact=CONTACT_HANDLE)
