# Thelivu — Brand Basics

**Name:** Thelivu (തെളിവ്) — Malayalam for *clarity* and *evidence/proof*. Names
both the method (the receipts) and the goal (understanding).

**Tagline:** "The evidence, and what it means." — a writing/positioning line only.
**It does not appear in the visual system.** The reel sign-off card shows the
*descriptor* instead (see "Reels & sign-off" below); the tagline was tried there
and cut.

**Descriptor** (the line the brand leads with on-surface): *"Fact-checked stories.
Every claim verified, every piece human-reviewed."*

**About blurb** (also the public statement of stance):
> Thelivu is explanatory journalism. We take important but under-reported stories —
> wherever they are — verify them across independent sources, and explain why they
> matter — openly from the side of ordinary people and public goods, and we tell you
> when we're arguing a view. Every claim is sourced. We correct mistakes in the open.

*(Positioning: global in scope with a working emphasis on uncovering Kerala — where
much of the audience is — but never Kerala-limited. This is a sourcing emphasis, not
a public frame: we don't brand as "Kerala-first." See PROJECT-STATUS, 2026-07-16.)*

**Standing footer** (on every published piece — keep verbatim):
> Sources above. Drafted with AI assistance, reviewed by a human editor before
> publishing. Spotted an error? We correct openly — [contact].

**Handles to secure (check availability before announcing):**
`@thelivu` on Telegram (bot + channel), and the YouTube/Instagram handles if you
mirror there. Fallbacks: `@thelivunews`, `@thelivu_in`.

**Two lines to keep verbatim, always:**
"…and we tell you when we're arguing a view" (the transparent-perspective promise)
and the open-correction line. They are what make the stance honest instead of a
label.

## Visual identity — "The Dossier"

Locked direction for the Instagram/social slide template (chosen from three
explored directions — dossier/case-file, kayal/backwater, verdict/newsroom).
Rationale: Thelivu means *evidence, proof* — the visual should read as "here
are the receipts," not "here is an opinion." Case-file aesthetic: kraft paper,
redaction-red stamps, typewriter metadata.

**Colours** — authoritative for rendering is `publishing/slides.py PALETTE`; this
table documents it. If they ever drift, slides.py wins and this gets corrected.

| Token | Hex | Use |
|---|---|---|
| Ink (dark bg) | `#17140D` | **the default ground** — social surfaces |
| Ink (text on kraft) | `#1B1710` | foreground on the light/kraft variant |
| Gold (dark accent) | `#D2AA6D` | accent + stamp colour on the ink ground |
| Kraft (light bg) | `#E6DCC3` | light variant — article/bio pages |
| Kraft-fg on dark | `#E9E0C8` | text on the ink ground |
| Redaction red | `#8C2A1B` | accent + stamp on the kraft/light variant |
| Kraft-dim | `#B3A891` | secondary/muted tone |

**Theme lock (2026-07-26):** the social surface is **single ink-dark**. This
reverses the earlier mood-based kraft/ink alternation — one ground, so the grid
reads as one system. Kraft is demoted to a *light variant* retained for the
article and bio pages (`publishing/biopage.py`, `articlepage.py`), which are
unchanged. On the ink ground the accent is **gold**, not redaction-red; red
stays the accent on the kraft variant.

**Type**
- Display / headline: Georgia or Times New Roman, **bold**, serif — "case-file" weight
- Body / metadata: Courier New (or ui-monospace fallback) — typewriter, "typed record" feel
- Utility (verdict stamps, citations): monospace, uppercase, letter-spaced

**Components**
- **Stamp**: top-left, border `2px solid #8C2A1B` (or `#D2AA6D` on dark bg), rotated
  `-3deg`, uppercase, e.g. `VERIFIED`, `FACT vs ALLEGATION`
- **Headline (`.hl`)**: serif bold, ~21px, tight line-height (1.22)
- **Sub** (supporting line): monospace, smaller, separated by a dashed top rule in
  redaction red (`1px dashed #8C2A1B66`)
- **Footer**: tiny uppercase monospace, ~75% opacity — site/handle + CTA

Full explored-directions artifact (for reference, not the source of truth —
this section is): https://claude.ai/code/artifact/15020fc7-bfd3-494d-bb21-1bc6333dc35c

## Reels & sign-off (locked 2026-07-26)

Reels are the **default reach surface**; carousels are optional — the "receipts"
deep-dive for stories that merit one.

**The mark** is the real Instagram logo: **ത + തെളിവ് inside a gold frame**.
Repo asset: `branding/assets/logo-hires.png` (recreated crisp/high-res; a tiny
illegible subtext in the original was dropped). Anything drawing the sign-off
should use this asset rather than redrawing the ത glyph — the repo serif has no
Malayalam glyphs, and the system font that does
(`/usr/share/fonts/.../NotoSerifMalayalam-Bold.ttf`) is not bundled.

**Frame furniture** — every reel frame: full-bleed illustration, bottom scrim,
`THELIVU · reel` wordmark, serif caption, progress bar, and
`thelivu.reports · sources in bio`.

**The sign-off card** closes every reel: ink ground, the logo mark, and the
**descriptor** — *"Fact-checked stories. Every claim verified, every piece
human-reviewed."* Not the tagline.

**The sign-off is SILENT.** The story plays in Anil's cloned voice, then the card
holds ~3s with no speech. Two things were tried and rejected: the cloned TTS
cannot pronounce "തെളിവ്", and splicing in a real-voice recording clashed with
the cloned voice badly enough that reel #8 was posted and pulled. The fix is to
say nothing and show the brand. **Do not rebuild the voice-splice.**

**The voice never speaks a bare acronym.** Same root cause as the sign-off: the cloned
TTS mangles initialisms. Write the expansion into the spoken line and let the CAPTION
carry the acronym — the renderer already highlights acronyms and numbers in the accent
colour, because those are precisely the tokens the voice gets wrong and the muted viewer
reads anyway. Familiar ones (RBI, NEET, CAG) may be spoken; a technical agency's initials
may not. This lived only as a code comment in `publishing/reel.py` for a long while, so
the script generator was never told and kept producing them — it is a brand rule, stated
in `skills/video-script/SKILL.md`.

**Signature elements — not theme variables.** The mark, the wordmark, the
serif/mono pairing, the layout skeleton and the sign-off card are fixed. The
illustration is the only thing that varies per story.

**Illustration lane:** *conceptual illustration* — symbolic, non-photoreal. This
protects the verification brand: no image may read as fabricated evidence of a
real event or person. Generated with FLUX.1-dev on the free NVIDIA key, on
**dark grounds** so the whole feed is one ink-dark system (owner's call,
2026-07-26 — earlier prototypes had warm/kraft skies with only the furniture in
ink). Watch the NIM safety filter: 'somber/grave/vulnerable/redaction' phrasing
returns all-black frames (`finishReason=CONTENT_FILTERED`) — check finishReason
and reject sub-50KB images.
