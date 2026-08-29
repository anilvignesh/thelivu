# Homepage feed — from a flat link list to a real news site

*Context file for this feature (per workflow). Written alongside the build;
update it if the design changes.*

## Requirement

Anil: the homepage was "just a list" (the bio-page link list at `/`) and he
wanted something closer to a proper news site — video + illustrated reports,
not a bare list of article titles. Source: 2026-08-29 conversation, following
up on a Claude skill (`greensock/gsap-skills`) he'd seen for scroll-driven
sites.

## Decisions

- **`/` and `/bio` split.** `/bio` keeps the old minimal, fully self-contained
  link list exactly as it was (see `docs/bio-page.md`) — every slide footer
  says "Thelivu · link in bio" and Instagram's in-app browser opens it from
  the bio tap, so it stays the lightest page on the site, untouched. `/`
  becomes the real homepage: a scroll feed of published stories, for organic
  visitors and shared links, not the IG bio tap.
- **GSAP, self-hosted, not a CDN.** `greensock/gsap-skills` is the official
  GreenSock skill; ScrollTrigger reveal-on-scroll is the actual mechanism
  behind "scrollytelling" journalism sites (NYT, Bloomberg Graphics). Pulled
  `gsap.min.js` + `ScrollTrigger.min.js` (v3.12.5) into `publishing/static/`
  rather than a `<script src="cdn...">` tag — same reasoning as dropping
  Telegraph for article hosting (commit c6b00c2, `docs/article-hosting.md`):
  no third-party domain in the request path. Served by a new allowlisted
  `/static/<file>` route in `fileserver.py` (exact-filename match, same
  no-path-traversal posture as the slide route).
- **Feed shows what already exists, nothing new generated.** Illustrated
  carousel slides and reels were already produced per story but only ever
  reached Instagram/Telegram. The feed surfaces them: a story's most recent
  *posted* reel plays as the card's media, or its most recent *posted*
  carousel's first slide is the thumbnail if there's no reel, or the card is
  text-only if neither exists yet. Only `posted`/`approved_manual` carousels
  and `ready`/`posted` reels are shown — a queued or failed one has no real
  file behind it and would 404.
- **Article pages get the same illustrated slides woven inline**, not just
  the homepage. `get_carousel_slides_for_run()` returns a run's slides
  (skipping position 1 — the carousel's own cover, redundant with the
  article's H1); `_blocks_to_html` spaces them evenly through the piece as
  `<figure data-reveal>` elements instead of clumping them at the top.
- **Progressive enhancement throughout.** Every card/block/figure is fully
  visible and readable with zero JS. GSAP only adds the fade-up scroll
  reveal on top (`gsap.fromTo` sets the hidden starting state itself, so a
  failed/blocked script load just leaves everything visible, never hidden).
  Reel previews autoplay muted/looped only while scrolled into view, via
  `IntersectionObserver`, and pause otherwise — no autoplay if the API isn't
  available. Respects `prefers-reduced-motion`.
- **Reading-progress bar on article pages** is plain JS (`scrollTop` /
  `scrollHeight`), no GSAP dependency — it has to work even if the two GSAP
  files fail to load.

## Pieces

| Piece | Where |
|---|---|
| `get_feed_items(limit)` — published runs + their latest posted carousel/reel ids | `shared/db.py` |
| `get_carousel_slides_for_run(run_id)` — a run's slides from its newest posted carousel only | `shared/db.py` |
| Feed HTML renderer (cards: video/thumbnail/text-only, GSAP reveal, autoplay-in-view) | `publishing/feedpage.py` |
| Article renderer changes: `slides` param, `_slide_figure`, reading-progress bar, GSAP reveal script | `publishing/articlepage.py` |
| Self-hosted GSAP + ScrollTrigger bundles (v3.12.5) | `publishing/static/gsap.min.js`, `publishing/static/ScrollTrigger.min.js` |
| Routes: `/` (feed), `/bio` (unchanged link list), `/static/<file>` (allowlisted) | `publishing/fileserver.py` |

## Constraints

- `/bio` must not change behavior or weight — it's the one page guaranteed to
  open inside Instagram's in-app browser.
- One bad `draft_text` row must not break the whole feed page — `feedpage.py`
  parses each item defensively and skips (not 500s) on a parse failure.
- Only `posted`/`approved_manual` carousels and `ready`/`posted` reels are
  ever linked to from a public page — anything else has no file behind it yet.
- No third-party CDN or asset host anywhere on `/`, `/bio`, or `/a/<slug>`.

## Not done here

- No visual QA against the live Railway deploy yet (no way to browser-test
  from this session) — the DB queries and HTML output are verified with
  fixture/in-memory data (see below), but a real read-through on a phone,
  including how the autoplay-in-view reels feel and how the carousel-image
  spacing reads on an actual multi-thousand-word piece, is still owed before
  calling this done.
- No change to the Telegram bot, `MANUAL.md`, or the publish pipeline —
  this only touches how already-published stories are displayed.
