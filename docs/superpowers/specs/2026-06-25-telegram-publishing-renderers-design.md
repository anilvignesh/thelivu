# Extensible Publishing Renderers — Telegram Hybrid

**Date:** 2026-06-25
**Status:** Approved, pending implementation

## Problem

Approved articles are posted to the Telegram channel as raw text with no
`parse_mode`, so Markdown (`#`, `**`, `*`, `>`) renders as literal characters and
long pieces split into 4–5 ugly messages. We want an attractive, Telegram-native
presentation now, structured so other targets (Medium, Instagram) can be added
later without reworking the pipeline.

## Decision

**Hybrid model:** a short formatted teaser in the channel + a Telegraph
"Instant View" link to the full, cleanly-typeset article. The teaser hook is
**derived deterministically** from the article (no LLM in the publish path — that
caused the pre-flight incident).

## Architecture

A new `publishing/` package. The extensibility primitive is a platform-neutral
parse of the article; each platform renders from it.

```
publishing/
  parser.py     # markdown -> neutral Article + Blocks (shared by all platforms)
  telegraph.py  # thin Telegraph API client (createAccount/createPage, token cached in kv)
  telegram.py   # Article -> (teaser HTML, Telegraph URL)   [built now]
  __init__.py   # publish_telegram(markdown) -> (teaser_html, telegraph_url)
  # future: medium.py, instagram.py — consume the same Article/Blocks
```

### parser.py (neutral, reusable)
- `parse_article(prepared_md) -> Article` with:
  - `title` — first `# ` H1
  - `hook` — the `## ` subtitle line immediately after the title; fallback to the
    first sentence of the first body paragraph
  - `standfirst` — the `*From Thelivu …*` masthead line
  - `confidence` — `(label, emoji)` parsed from the `*Confidence: X — …*` line
    (Confirmed 🟢 / Developing 🟡 / Contested 🔴; default 🟡 Developing)
  - `sources` — the `*Sources: …*` footer line
  - `blocks` — the body as neutral Blocks
- `parse_blocks(md) -> [Block]` for the writer's markdown subset: headings (1–3),
  paragraphs, blockquotes, `---` rules, bullet lists. Blocks carry raw inline
  markdown; renderers convert inline (`**bold**`, `*italic*`, `[t](u)`) themselves.

`Block` = `{"type": heading|paragraph|blockquote|list|rule, "level": int,
"text": str, "items": [str]}`.

### telegraph.py
- `get_token()` — `kv_get("telegraph_token")`; if absent, `createAccount`
  (short_name/author "Thelivu") and cache it.
- `create_page(title, nodes, author_name="Thelivu") -> url`.
- Telegraph supports only `h3`/`h4` headings; `strong`, `em`, `a`, `blockquote`,
  `p`, `ul`/`ol`/`li`, `hr`, `br`.

### telegram.py
- `_blocks_to_nodes(blocks)` — Blocks -> Telegraph DOM nodes. `#`/`##` -> `h3`,
  `###` -> `h4`; inline -> `strong`/`em`/`a`.
- `_inline_to_html(s)` — escape `& < >`, then `**b**`->`<b>`, `*i*`->`<i>`,
  `[t](u)`->`<a href="u">t</a>`.
- `_build_teaser(article, url)` ->
  ```
  <b>TITLE</b>

  HOOK

  ▸ Full piece (Instant View): URL

  🟡 Developing
  Spotted an error? We correct openly — @Blazedddddd
  ```
- `render(markdown) -> (teaser_html, url)`: parse, publish Telegraph page, build
  teaser.

### Wiring (thelivu_bot/bot.py)
`_handle_approve`, after `_prepare_for_publish(draft)`:
1. `teaser, url = publish_telegram(text)`
2. Post `teaser` to the channel with `parse_mode=HTML`, web preview **on** (so the
   Instant-View card shows). Record the message id(s) as today.
3. **Fallback:** on any exception in `publish_telegram` or the HTML post, fall back
   to the existing chunked plain-text `_post_to_channel(text)`. Approval must never
   hard-fail. Log that it fell back.

## Scope guards (YAGNI)
- No images (articles have none) — future Telegraph capability.
- Medium/Instagram not built; only the neutral Article/Blocks seam is in place.
- The teaser is derived, never LLM-generated.

## Testing
- `parse_blocks` / `parse_article` on the real ISKCON draft: correct title, hook,
  confidence, block types.
- `_inline_to_html` escaping and bold/italic/link conversion.
- `_blocks_to_nodes` produces valid Telegraph node shapes (h3/h4/p/blockquote).
- Teaser contains title, hook, url, confidence emoji, contact; no raw `#`/`*`.
- Fallback path: when Telegraph client raises, the bot posts via the plain-text
  path (verified with a stubbed client).
- Telegraph API call itself is exercised via a thin client and mocked in tests; a
  live smoke test is run once during rollout.
```
