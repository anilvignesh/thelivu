---
name: long-form-script
description: Write a chaptered long-form video script (5-8 minutes) for a verified story too dense for the 90s reel ceiling. Use when a reel script cannot fit 225 spoken words without cutting the hook, the close, or the attribution that makes a claim checkable. Produces a script only — never publishes, never fabricates. Most stories should still be reels; this is the exception.
---

# Long-Form Script

The reel format has a hard ceiling of 225 spoken words, and an overflow rule: *if
you are over budget, cut a middle beat.* For most stories that is the right
trade. For a few it is not — when what gets cut is a second figure that changes
what the first one means, or the attribution that separates "spent badly" from
"allegedly stolen", the reel is no longer a shorter version of the story. It is a
less defensible one.

This skill exists for that case only. **Most stories should still become reels.**
A long-form script that is a reel with more words in it is a failure, not a
format.

This skill enforces the project's editorial charter (`../../CHARTER.md`) and
brand (`../../BRAND.md`). Read them if present; the charter governs in any
conflict. It writes a script only — it never fabricates, never overstates, and
never publishes.

## When a story earns this format

Route here only if at least one is true:

1. **The reel script still exceeds 225 words after cutting a middle beat** — i.e.
   cutting further would take the hook, the close, or a checkable attribution.
2. **The story turns on a distinction that takes a sentence to state.** The live
   example: the same ₹46,300cr figure is used one way as total road spend that
   produced substandard roads (a quality-failure claim) and another as 75% of
   that amount misappropriated (a theft claim). Conflating those is exactly the
   overstatement the charter's verb-precision rule blocks — and stating the
   difference properly does not fit a 30-word beat.
3. **The evidence is a trajectory, not a fact.** Multi-year figures where the
   shape over time *is* the finding, and any single year is unremarkable.

If none holds, go back and write a reel. Say so plainly rather than producing a
long script nobody needed.

## Word budget

| | |
|---|---|
| **Target** | **750–1,200 spoken words (~5–8 minutes)** |
| Hard ceiling — never exceed | 1,500 words (~10 minutes) |

Count only SPOKEN lines. Narration is synthesised on a CPU box at roughly **7.2x
realtime** (measured 2026-09-10), so a 1,200-word script costs about an hour of
machine time and a 1,500-word one about seventy-five minutes. That is why the
ceiling is a ceiling: it is not an aesthetic preference, it is the point past
which one video starves the reel pipeline that runs on the same machine.

The ceiling is not a target. A 900-word script that earns every word beats a
1,400-word one that repeats itself with more dignity.

## Shape

Long-form is **chaptered**, not a longer chain of beats. Each chapter is a unit a
viewer could describe afterwards in one sentence.

- **COLD OPEN (1–3 lines).** The sharpest verifiable fact anywhere in the story,
  stated flat. Same rule as the reel: do not open with context, open with the
  thing that makes someone stay. Do not promise what the video will cover.
- **3–6 CHAPTERS.** Each has a title and 150–300 spoken words. One chapter, one
  move: establish a figure, complicate it, attribute it, or show what follows
  from it. A chapter that does not change what the viewer believes is padding.
- **CLOSE (2–4 lines).** What is still unknown and what would settle it. Long-form
  earns the right to say "here is specifically what is missing" — that is real
  information, not a dead end, and it is often the most honest ending available.

### What chapters are FOR

The reel format forces one idea per beat. Long-form's gain is not more ideas — it
is room for the **second sentence**: the qualification, the counter-case, the
"the department disputes this, and here is their number." A chapter that states a
finding and moves on has used the format's length without using its capability.

## Hard rules

These carry over from the reel skill unchanged, because they are charter rules,
not format rules:

- **Every figure is attributed in the spoken line**, not only on screen. "The
  CAG's 2024 audit put it at ₹1,950 crore" — not "reports suggest".
- **Verb precision.** Alleged, filed, chargesheeted, found, convicted are
  different words describing different states of the world. Never promote one to
  another for rhythm.
- **No fixed villains.** Start from the record and follow it to whoever it names.
  Scrutiny is symmetric regardless of which party or organisation the record
  implicates.
- **Never fabricate a figure, date, name, or quote.** If a number is uncertain,
  say it is uncertain in the spoken line.
- **A disputed figure is reported as disputed**, with both readings, in the
  chapter where it appears — not corrected later.

## Chapters on YouTube

Give each chapter a timestamp label. The engine turns these into YouTube
chapters (`publishing/youtube.py::format_chapters`), which requires the list to
start at 0:00, have three or more entries, and ascend — otherwise YouTube renders
none at all. Estimate timestamps from the word budget at roughly **150 spoken
words per minute**; the renderer corrects them against the real audio.

## Illustration

One IMAGE per chapter, not per line — a long-form video holds a document, a
chart, or a single conceptual frame on screen while the narration works through
it. Where the evidence *is* a document (an audit paragraph, an affidavit line),
say so in the IMAGE line: holding the actual record on screen is stronger than
illustrating around it.

## Output (exactly this, nothing else)
```
TITLE: <short internal title>
PLACE: <where the story happens — "Karnataka, India". Never spoken; it anchors illustrations to the right country. Blank if genuinely placeless.>
WHY_LONG_FORM: <one sentence naming which of the three triggers above this story meets>
COLD_OPEN: <spoken opening, 1-3 lines>
COLD_OPEN_IMAGE: <one-sentence conceptual illustration>
CHAPTER 1 TITLE: <4-8 words, plain>
CHAPTER 1: <spoken lines, 150-300 words>
CHAPTER 1 IMAGE: <one-sentence conceptual illustration, or the document to hold on screen>
CHAPTER 2 TITLE: <...>
CHAPTER 2: <...>
CHAPTER 2 IMAGE: <...>
...
CLOSE: <spoken closing, 2-4 lines: what is unknown, and what would settle it>
CLOSE_IMAGE: <one-sentence conceptual illustration>
DESCRIPTION: <2-4 sentences for the video description, with the primary sources named>
HASHTAGS: <6-10 story-specific tags — brand tags are added by the engine>
WORD_COUNT: <integer, spoken words only>
```

## Self-check before output

1. **Word count is real.** Count the spoken lines. If over 1,500, cut a whole
   chapter — never thin every chapter to fit, which produces a script that reads
   rushed at every point instead of one that is shorter.
2. **Every figure has its attribution in the spoken line.**
3. **Every chapter changes what the viewer believes.** If one only restates, cut
   it and say the script is shorter.
4. **WHY_LONG_FORM is honest.** If you cannot name a trigger, this should have
   been a reel — say so instead of producing the script.
