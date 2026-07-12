---
name: slide-composer
description: Turns a human-approved, already-published Thelivu article into the copy for one Instagram slide in the "Dossier" visual identity (engine/BRAND.md). Picks a punchy headline, pulls a real supporting line from the article body, and chooses a stamp + light/dark variant. Judgment/writing task — routes to Claude.
---

# Slide Composer

The article is already written, verified, and approved — this skill does not
re-report or re-argue anything. Its only job is **compression for a single
image**: pick the four short strings a slide needs, straight out of the
article that's already true.

This skill enforces the editorial charter (`../../CHARTER.md`) and the
substance rule in particular: **a slide may never say something the article
doesn't.** No new numbers, no new claims, no softened or sharpened framing
relative to the piece. If it isn't in the article, it doesn't go on the slide.

## What you're given

The full approved article markdown: title (H1), the standing byline line,
body paragraphs, and a sources footer.

## What to produce

**HEADLINE** — the hook, in one glance.
- Start from the article's own title. If it already reads well at slide size
  (roughly under 90 characters, no subordinate clauses trailing off), use it
  close to verbatim.
- If the title is long or academic, tighten it — cut qualifiers and connective
  tissue, keep the actual claim. Never introduce a number, name, or comparison
  that isn't in the title or opening paragraphs.
- It's fine for this to *not* be a full sentence.

**SUB** — one supporting line, pulled from the body.
- This is the single most common failure mode: do NOT use a section heading
  (e.g. "What the audit actually says") — that's a label, not a hook. Find an
  actual sentence or tight paraphrase from the body: a stat, a comparison, a
  sharp turn of phrase, the line that makes someone stop scrolling.
  Direction A examples from the locked design brief: "₹16 lakh crore in bank
  write-offs. No audit. No names. That's the law." / "Write-off ≠ waiver —
  but the scrutiny only ever points one way."
- Keep it under ~140 characters. Quote or closely paraphrase — do not invent
  a figure or characterization absent from the text.
- If nothing in the body works as a standalone hook, leave it empty (`(none)`)
  rather than force a weak line.

**STAMP** — one short uppercase tag, top-left of the slide.
- Default `VERIFIED` for a standard confirmed piece.
- Use `FACT vs ALLEGATION` when the article's core move is separating a true
  fact from a spun/false framing of it (audits, "everyone says X but the
  record shows Y" pieces).
- Use `DEVELOPING` only if the article itself is marked Developing confidence,
  not Confirmed.
- Keep it under 20 characters, uppercase words only.

**DARK** — `true` or `false`.
- `false` (kraft/light) is the default — reads as a standard case file.
- `true` (ink/dark) for pieces with a harder, more confrontational edge —
  exposing a specific double standard or a starker number. Use sparingly; it's
  a mood shift, not a coin flip.

## Output (exactly this, nothing else)

```
HEADLINE: <text>
SUB: <text, or (none)>
STAMP: <text>
DARK: <true|false>
```
