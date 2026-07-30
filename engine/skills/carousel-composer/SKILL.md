---
name: carousel-composer
description: Turns a human-approved, already-published Thelivu article into the copy for a multi-slide Instagram carousel in the "Dossier" visual identity (engine/BRAND.md) — a swipeable breakdown of the article's own argument, up to 10 slides. Judgment/writing task — routes to Claude.
---

# Carousel Composer

The article is already written, verified, and approved — this skill does not
re-report or re-argue anything. Its job is **sequencing**: take the article's
own throughline and break it into a swipeable set of short slides that reads
as a complete mini-version of the piece, so a reader who never leaves
Instagram still gets the real argument, not just a hook.

This skill enforces the editorial charter (`../../CHARTER.md`) and the
substance rule in particular: **a slide may never say something the article
doesn't.** No new numbers, no new claims, no softened or sharpened framing
relative to the piece. Every slide's text should be a quote or a tight
paraphrase of something actually in the article.

## What you're given

The full approved article markdown: title (H1), the standing byline line,
body paragraphs, and a sources footer.

## What to produce

**Pick the number of slides that does two things at once: explains the story
completely AND earns engagement.** You decide per story — Thelivu's call, not a
fixed count. Two forces to balance:

- *Explain properly:* enough slides that a reader finishes understanding the
  argument — nothing important compressed out.
- *Engage:* Instagram rewards **completion, saves and dwell time**, and re-serves a
  carousel to people on a later slide — so a fuller, well-paced set gets more reach,
  as long as every slide earns its swipe.

In practice that lands at **8–10 slides** for most Thelivu pieces (a substantive
story with a hook, several evidence beats, a turn, and a close). **Hard ceiling: 10**
(Instagram's carousel limit). **Never pad** to hit a number — a genuinely tight
piece can be complete at 6–7, and filler dilutes engagement rather than helping it.
**Never truncate** a story that needs the room, either — if it takes 9–10 slides to
land the argument, use them. Below ~5 it isn't a breakdown, just a single slide with
extra steps. Judge each story on whether the reader leaves both *informed* and
*wanting to save/share it*.

**Slide 1 — the hook.** Same job as a single slide's headline: the claim or
question that makes someone stop scrolling and swipe. Close to the article's
own title, tightened if needed. Under ~90 characters where possible.

**Middle slides — the argument, in order.** Walk through the article's actual
structure: the key fact, the context that reframes it, the evidence, the
comparison, the turn. Each slide is one beat — one sentence's worth of idea,
not a paragraph. Pull real sentences or numbers from the body; paraphrase
tightly rather than summarizing vaguely. A reader swiping through should be
able to reconstruct the article's real argument, not just a mood.

**Last slide — the close.** The article's own conclusion or the sharpest
closing line — the "so what" or the question left hanging. Not a
call-to-action slide ("read more!") — the caption already carries the link to
the full piece; this slide's job is to land the argument, same as the
article's own final paragraph does.

**STAMP** — one short uppercase tag for slide 1 only (the rest show a
position indicator instead, added automatically — don't include it
yourself). Same vocabulary as the single-slide skill:
- `VERIFIED` — standard confirmed piece.
- `FACT vs ALLEGATION` — pieces whose core move is separating a true fact
  from a spun/false framing of it.
- `DEVELOPING` — only if the article itself is marked Developing confidence.

**DARK** — `true` or `false`, chosen once for the whole carousel (all slides
share it — flipping background color mid-swipe looks broken). `false`
(kraft/light) is the default; `true` (ink/dark) for pieces with a harder,
more confrontational edge. Use sparingly.

**HASHTAGS** — 6–10 hashtags specific to THIS story, for Instagram reach. The
engine adds evergreen brand tags (Thelivu, FactCheck, Journalism, News)
automatically, so do NOT repeat those — give the tags that make *this* piece
discoverable: the topic, the sector, named places/schemes/entities, the theme,
**and the geography that actually fits the story** — `#Kerala` for a Kerala piece,
the relevant national (`#India`) or international place/subject tags for a national
or international one. Thelivu covers Kerala, national and international stories; tag
each for what it is, don't force Kerala onto everything. Prefer terms real people
search (`#Varkala`, `#EthanolBlending`, `#WaterCrisis`, `#RTI`, `#KIIFB`). One
word each, no spaces, no punctuation, no leading `#` needed. Skip banned/spammy or
engagement-bait tags (`#follow4follow` etc.) — they suppress reach. Space-separated
on one line.

## Output (exactly this, nothing else)

```
DARK: <true|false>
STAMP: <text>
HASHTAGS: <tag1 tag2 tag3 …>
SLIDE 1: <hook>
SLIDE 2: <beat>
SLIDE 3: <beat>
...
SLIDE N: <closing line>
```
