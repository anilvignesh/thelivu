# Self-hosted article pages — /a/<slug>

*Context file for this feature. Written before building; update if the design
changes.*

## Requirement (why Telegraph had to go)

Telegraph was the article host, but Telegram-owned domains are unreliable-to-dead
on Indian ISPs — tested 2026-07-14 from Anil's connection: `t.me` doesn't resolve
at all, `telegra.ph` intermittently connection-resets. A Kerala-first publication
whose article links die for Indian readers has no funnel. Articles therefore get
served from our own Railway domain (`thelivu.up.railway.app`), like the bio page
already is.

## Decisions

- **Route:** `/a/<slug>` on the existing agent web server. Slug =
  `<run_id>-<kebab-case-headline>`; **lookup is by the run-id prefix only**, so
  a retitled headline never breaks an old link.
- **Render from the DB, per request.** The page is built from
  `pipeline_runs.draft_text` (scaffolding stripped, footer + contact filled —
  same preparation as the channel publish path). No static files, no publish
  step: what's approved in the DB is what's served.
- **Human gate holds:** only runs with status `published` are served — a
  guessed URL to an unpublished run 404s.
- **Canonical URL everywhere.** The publish flow now links the channel teaser,
  the bio page, and the IG caption to our page. Telegraph is dropped from the
  article publish path (it stays for owner-facing report/preview links, which
  are read inside Telegram where telegra.ph works).
- **Same visual system as the bio page** (palette from `publishing/slides.py`,
  light + dark, inline CSS, mobile-first). OG meta tags so shared links show
  title + hook.
- **Bio page uses relative `/a/...` URLs** for self-hosted articles, so a
  future domain change needs no data migration.

## Pieces

| Piece | Where |
|---|---|
| `slug` column on `pipeline_runs` (+ migrations), `set_run_slug`, `get_run_by_slug` | `shared/db.py` |
| `make_slug(run_id, headline)` + article HTML renderer | `publishing/articlepage.py` |
| Route `/a/<slug>` (published runs only; styled 404) | `publishing/fileserver.py` |
| Publish flow: slug + self-hosted URL, teaser without Telegraph | `thelivu_bot/bot.py`, `publishing/telegram.py` |
| Backfill: slugs for the 7 published runs; bio_links repointed | one-off, via Railway DB |

## Constraints

- The renderer consumes `publishing.parser` blocks — the same neutral parse the
  Telegram/Telegraph renderers use; no second markdown parser.
- Article HTML must be self-contained (inline CSS, no external assets) and
  readable inside Instagram's in-app browser.
- The web server thread must never crash on a bad slug or DB hiccup.
- `Cache-Control: no-cache` like the bio page — corrections must show up
  immediately (we correct openly; a cached wrong version defeats that).
