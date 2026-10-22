"""Shared look for the public pages (feed, article): the same "dossier" language as the reels.

Ink ground (kraft in light mode), Archivo for our voice, Charter/Georgia for the source's words and long reading, the wordmark
left in gold with a hairline under it. Status is a block, not an emoji: solid accent = Confirmed, outlined accent = Developing,
solid red = Contested (red always means missing/late/lost). Motion follows one rule set: ease-out on a strong curve, specific
properties only, under 300ms, press feedback on anything pressable, hover only where hover exists, nothing when the reader
prefers reduced motion. Archivo ships as one 25 KB woff2 subset from publishing/static/ (SIL OFL), no third-party host.
"""
import html

STATUS_CLASS = {"confirmed": "confirmed", "developing": "developing", "contested": "contested"}


def status_block(label, date=""):
    """<span> status block + date, for the meta line of a story or an article."""
    cls = STATUS_CLASS.get((label or "").lower(), "developing")
    d = f'<span class="when">{html.escape(date)}</span>' if date else ""
    return f'<span class="status {cls}">{html.escape(label or "Developing")}</span>{d}'


def header(right="Fact-checked &middot; sourced &middot; reviewed"):
    return f'<header class="top"><a class="logo" href="/">Thelivu</a><span class="tag">{right}</span></header>'


BASE_CSS = """
  @font-face {
    font-family: 'Archivo'; src: url('/static/Archivo.woff2') format('woff2');
    font-weight: 400 800; font-style: normal; font-display: swap;
  }
  :root {
    --bg: #E6DCC3; --fg: #1B1710; --dim: rgba(27,23,16,.68); --accent: #8C2A1B; --on-accent: #E6DCC3;
    --alert: #B3261E; --on-alert: #F6EFDD; --line: rgba(27,23,16,.22); --panel: rgba(27,23,16,.05);
    --sans: 'Archivo', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    --serif: Charter, 'Bitstream Charter', 'Iowan Old Style', Georgia, serif;
    --ease-out: cubic-bezier(.23, 1, .32, 1);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17140D; --fg: #E9E0C8; --dim: #B3A891; --accent: #D2AA6D; --on-accent: #17140D;
      --alert: #FF6B57; --on-alert: #17140D; --line: rgba(233,224,200,.5); --panel: rgba(30,26,18,.75);
    }
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { background: var(--bg); -webkit-text-size-adjust: 100%; }
  body {
    background: var(--bg); color: var(--fg); font-family: var(--serif);
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; text-rendering: optimizeLegibility;
  }
  h1, h2, h3, h4 { font-family: var(--sans); font-weight: 700; letter-spacing: -.015em; text-wrap: balance; }
  p, li { text-wrap: pretty; }
  a { color: inherit; }

  /* document header: wordmark left, descriptor right, hairline under */
  header.top {
    display: flex; justify-content: space-between; align-items: baseline; gap: 1rem;
    padding-bottom: .8rem; border-bottom: 2px solid var(--line); margin-bottom: 2rem;
  }
  .logo {
    font-family: var(--sans); font-weight: 600; font-size: .95rem; letter-spacing: .3em; text-transform: uppercase;
    color: var(--accent); text-decoration: none;
  }
  .tag { font-family: var(--sans); font-size: .72rem; color: var(--dim); text-align: right; }

  /* status block + date: the confidence label, never an emoji */
  .meta { display: flex; align-items: center; gap: .6rem; margin-bottom: .75rem; font-family: var(--sans); }
  .status {
    font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    padding: .22rem .55rem; line-height: 1.2; border: 1.5px solid var(--accent);
  }
  .status.confirmed { background: var(--accent); color: var(--on-accent); }
  .status.developing { color: var(--accent); }
  .status.contested { background: var(--alert); border-color: var(--alert); color: var(--on-alert); }
  .when { font-size: .75rem; color: var(--dim); font-variant-numeric: tabular-nums; }

  /* anything pressable answers the press; hover only where a pointer can hover */
  a.story, a.hero, .logo, footer a { transition: transform 160ms var(--ease-out), color 160ms ease; }
  a.story:active, a.hero:active { transform: scale(.985); }
  @media (hover: hover) and (pointer: fine) {
    a.story:hover h3, a.hero:hover h2 { color: var(--accent); }
  }
  a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
  }
"""
