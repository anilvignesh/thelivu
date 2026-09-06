"""Render the public Terms of Service page — served at /terms.

Added 2026-09-07 alongside privacypage.py, same trigger (Google OAuth
verification prep) though ToS itself isn't a requirement for that specific
review — added because Anil asked for it directly. Same house style,
static content, no DB read.
"""
from shared.config import CONTACT_HANDLE

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Terms of Service — Thelivu</title>
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
  <p class="updated">Terms of Service — last updated 2026-09-07</p>
</header>

<p>These terms cover use of Thelivu ("we", "the site") — an independent,
verification-first news publication. By reading or otherwise using this
site, you agree to them.</p>

<h2>What Thelivu is</h2>
<p>Thelivu publishes news articles, explainer videos, and illustrated
carousels, with editorial standards described in our published work
itself: attributed sourcing, transparent perspective, and public
corrections when we get something wrong.</p>

<h2>Using the site</h2>
<ul>
  <li>Content here is free to read. No account or payment is required.</li>
  <li>You may share links to our articles and quote us with attribution, as
      is standard practice for news content.</li>
  <li>Reproducing full articles, videos, or carousels elsewhere without
      permission is not authorized.</li>
</ul>

<h2>No warranty</h2>
<p>We report in good faith and correct errors publicly when found, but we
make no guarantee that every claim on this site is complete or free of
error at every moment — journalism is an ongoing process, not a finished
product. Check an article's "last updated" context and any published
corrections before treating a specific figure or claim as final.</p>

<h2>Third-party links and platforms</h2>
<p>Our content is distributed via our own site and via third-party
platforms (Instagram, YouTube, Telegram). Those platforms have their own
terms; we're not responsible for their availability or behavior.</p>

<h2>Changes</h2>
<p>We may update these terms as the site evolves. Material changes will
update the "last updated" date above.</p>

<h2>Contact</h2>
<p>Questions about these terms can be sent via {contact}.</p>

<footer>Thelivu</footer>
</body>
</html>"""


def render():
    return _PAGE.format(contact=CONTACT_HANDLE)
