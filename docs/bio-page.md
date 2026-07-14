# Bio page — the "link in bio" the slides already promise

*Context file for this feature. Written before building (per workflow); update it
if the design changes.*

## Requirement

Every rendered slide footer says **"Thelivu · link in bio"**. That link has to go
somewhere: a single public page listing the published articles (Telegraph pages)
plus any evergreen links (Telegram channel, about page). Whenever a piece is
published, its link must land on that page. Before automating that, we need the
tool to manage the links at all.

## Decisions

- **Self-hosted, not Linktree.** Same reasoning as the slide file server
  (commit c6b00c2): no third-party host, no secrets in URLs, we already run a
  public HTTP server on the agent service. The bio page is one more route on it.
- **Served at `/` and `/bio`** on the slide server (`SLIDE_SERVER_BASE_URL`).
  The Instagram bio points at the base URL. Custom domain can come later —
  it's just a CNAME in front of the same Railway service.
- **Managed from the Telegram bot**, like everything else (/addfeed, /sources):
  - `/links` — list all links with ids, pinned state, and the public page URL
  - `/addlink <url> | <title>` — add manually (pipe separates url from title)
  - `/dellink <id>` — remove
  - `/pinlink <id>` — toggle pinned (pinned links stay on top)
- **Auto-add on publish.** When the human gate approves a run and the Telegraph
  path succeeds, the article's title + URL are inserted at the top of the page
  automatically (deduped by URL). The plain-text fallback path adds nothing —
  there is no page URL to link.
- **Ordering:** pinned first, then newest first. No manual reordering — pin
  covers the real need (about page etc. on top).
- **The channel button is template, not data.** "Join the Telegram channel" is
  baked into the page (shown when `CHANNEL_PUBLIC_URL` is set), always first —
  a permanent brand link shouldn't be deletable/unpinnable via bot commands.
  The env var stays blank until the channel has a public @username; the
  numeric TELEGRAM_CHANNEL_ID is not a linkable URL.

## Pieces

| Piece | Where |
|---|---|
| `bio_links` table (id, title, url, pinned, created_at) | `shared/db.py`, both schemas |
| DB functions: `add_bio_link`, `list_bio_links`, `delete_bio_link`, `set_bio_link_pinned` | `shared/db.py` |
| HTML renderer (brand palette from `publishing/slides.py`, light + dark) | `publishing/biopage.py` |
| Routes `/` and `/bio` (render per request — traffic is tiny) | `publishing/fileserver.py` |
| Bot commands + auto-add in `_handle_approve` | `thelivu_bot/bot.py` |
| Command docs | `MANUAL.md` |

## Constraints

- The page must be fully self-contained (inline CSS, no external assets) and
  mobile-first — it's opened from the Instagram app's in-app browser.
- The file server thread must never crash on a DB hiccup: the bio route catches
  everything and returns a plain 500.
- The bot writes to the same DB the agent service reads — no cache invalidation
  needed since the page renders per request.
