---
name: video-script
description: Turn a human-approved, already-published Thelivu article into a spoken script for a short (<60s) AI-avatar Instagram Reel — the same story as the carousel, but voiced. Produces the presenter's spoken lines plus on-screen caption beats. Judgment/writing task — routes to Claude. Produces a script only; never publishes.
---

# Video Script (the reel)

Turns a verified article into a **spoken script for a short vertical Reel**, where a
stylized Thelivu presenter voices the story. Reels are the reach surface — this is
the same argument as the carousel, compressed to what a person can say out loud,
written for the ear and for a muted viewer reading captions.

**Target tight, but the length is a range, not a wall — and the range runs closer
to the ceiling than earlier drafts of this skill used.** Instagram's Graph API only
gives Reels-tab / discovery placement to videos of 5–90 seconds — past that a post
technically still publishes but loses the exact non-follower reach this format
exists for, so 90s is a hard ceiling this skill must never approach. Padding a reel
that didn't need the extra room still costs more reach than it buys — a tight reel
completes better, and completion rate is itself a reach signal, so never write past
what the story actually has. But the correction (Anil, 2026-08-17, after reading
real published pieces): most Thelivu articles are dense enough that compressing to
the short end was cutting real substance — a second sourced data point, the
counter-case, the specific figure that makes a claim checkable — not padding. Write
the length the story earns. If it genuinely earns 40–50s, stop there; if the
verified material runs deeper than that, use the room the platform actually gives
before reaching for a shorter number that isn't reflecting what's really in the
piece.

This skill enforces the project's editorial charter (`../../CHARTER.md`) and brand
(`../../BRAND.md`). Read them if present; the charter governs in any conflict. It
writes a script only — it never fabricates, never overstates, and never publishes.
Before final output, self-check spoken lines and captions against
`../../AI-WRITING-TELLS.md` — clusters of AI-writing patterns, not isolated words.

## Hard rules (same spine as the rest of the engine)
- **NEVER upgrade the procedural status of anything.** Compression is where this
  breaks: a real script said *"the students won a bill"* when the Bill had only
  been **tabled**. Keep the verb the article used.
  - tabled / introduced ≠ **passed** ≠ enacted
  - announced / assured ≠ **withdrawn** ≠ done
  - alleged / claimed ≠ **found** ≠ proven ≠ convicted
  - recorded / filed ≠ **established** ≠ ruled
  - detained ≠ **arrested** ≠ charged
  If the accurate verb costs you three syllables, spend them. A reel that
  overstates by one word is a reel we have to pull.
- **The viewer is the only audience.** Never narrate the editorial process — no
  "we verified this", "we're not repeating that claim", "our earlier report said".
  Say the fact. A correction, if the story needs one, is stated as fact ("A police
  record now shows…"), never as commentary on our own work. Same rule as
  article-writer; it applies to spoken lines, captions and IMAGE prompts alike.
- **Only what the article established.** No new claims, no numbers not in the piece,
  no fabricated quotes. If the article hedged, the script hedges (say "alleged,"
  "reportedly," "the records suggest").
- **Attribute the load-bearing facts** in the voice line itself ("the CAG report
  found…", "court records show…") — a spoken claim with no source is not Thelivu.
- **Never put a bare acronym in a SPOKEN line.** The reel is voiced by a cloned TTS
  that mangles them — it may spell them out, stress them wrongly, or read them as a
  word. Write the words the voice should say, and let the CAPTION carry the acronym,
  where the renderer already highlights it in the accent colour:
  - spoken: *"the North Eastern Space Applications Centre"* — caption: `NESAC says up to 80%`
  - spoken: *"the state pollution control board"* — caption: `KSPCB issued 0 penalties`
  - spoken: *"the state's infrastructure fund"* — caption: `KIIFB · ₹2,000cr`
  This is why numbers and acronyms belong on screen: those are exactly the tokens the
  voice can get wrong, and the muted viewer reads them anyway. If an acronym is genuinely
  more familiar than its expansion (RBI, NEET, CAG), you may speak it — but never one the
  audience would have to decode, and never a technical agency's initials.
- **Never ask an IMAGE line for a map, a seal, a crest, an emblem, or a headline.**
  The illustrator is FLUX, and it renders these wrong in a way that reads as a
  factual error, not a style: asked for a map of the Bengaluru–Mysuru corridor it
  drew **Australia**, and a "government seal" comes back ringed with gibberish
  letters. Reel #22 shipped both. Write the idea as an object or a figure instead
  — land, a road, a building, a hand, a document — and let PLACE do the geography.
- **Transparent perspective:** you may argue the article's view, openly — but signal
  when it's a view, not a fact.
- Named living people: documented facts and contested processes only, never asserted
  wrongdoing. Defamation care applies at spoken pace too.

## Shape (write for the ear, and for muted viewing)
- **Total: 110–210 words** (~40–85s at a natural pace, ~147wpm). Raised from the
  original 110–180 (2026-08-17) — 180 words tops out around 73s, leaving 15+
  seconds of the platform's actual allowance unused every time, and that gap was
  coming out of real verified material, not filler. 110–160 is the working default;
  reach into 160–210 when the story has genuinely earned it (a second sourced data
  point, the counter-case, a specific figure a claim needs to stay checkable) —
  which is common, not the exception, for a piece with real primary sourcing. Never
  exceed 210 — that keeps a natural-pace read safely under the platform's 90s
  ceiling. Still never pad: a 130-word story stays 130 words.
- **Hook (first 3 seconds / ~1 sentence):** the sharpest fact or the stakes. This is
  the whole reel's fate — earn the next 3 seconds. No throat-clearing, no "in this
  video."

  **The hook must carry a stake in its own words.** Someone who sees only that one
  line must already know what is at issue — a number, a name, a loss, or a
  contradiction. A line that merely *introduces* the story is not a hook, however
  well written, because nothing in it makes the next three seconds worth spending:

  - ✗ "Karnataka promised farmers a highway."  ← setup. Promised what? So?
  - ✓ "Karnataka took farmers' land for a highway the High Court says was never
    theirs to take."
  - ✗ "A judge granted a land activist bail."  ← an event with no stake shown.
  - ✓ "A land activist spent nine months in jail for a case the judge called
    'manufactured'."
  - ✓ "India is spending ninety-eight crore rupees to study if cow urine cures
    cancer."  ← a number and a contradiction; nothing else needed.

  The stake must be one the article established — sharpening is selection, never
  escalation. If the piece does not support a sharp hook, the honest fix is a
  narrower story, not a bigger claim.
- **Body (3–4 short beats, up to 6 when the extra length is earned):** the key
  fact → the context that reframes it → the evidence → the turn → (if a fifth or
  sixth beat is truly load-bearing) the counter-case, a second data point, or the
  complication. One idea per beat, plain spoken sentences, short words. The point
  of the wider word budget above is more BEATS worth watching for, not the same
  three or four ideas said more slowly — a longer script that doesn't add a new
  idea per extra beat is padding even if every word is true.
- **Close (1 line):** the "so what," or the question left hanging. Then a soft share
  cue is allowed once ("send this to someone who should see it") — never engagement
  bait.
- Every spoken line has a paired **CAPTION** beat: a tight on-screen version (most
  viewers watch muted) — not a transcript, the 3–6 word gist that reinforces the VO.
- Every beat also gets an **IMAGE** line: a one-sentence description of a
  *conceptual illustration* for that beat. Rules, and they are brand rules, not
  taste: **symbolic, never literal or photographic.** Objects, diagrams, simple
  silhouettes, scales, cross-sections, weather. **No text or lettering in the
  image** (the renderer draws all type), no logos, and **no recognisable real
  people or real events depicted as if photographed** — an image that could be
  mistaken for evidence undermines the one thing Thelivu sells. Describe the
  scene, not the style: the house style is applied by the renderer.

## Output (exactly this, nothing else)
```
TITLE: <short internal title>
PLACE: <where the story happens — "Karnataka, India", "Kerala, India", "San Francisco, USA". Never spoken or shown; it anchors the illustrations to the right country. If the story is genuinely placeless, leave it blank.>
HOOK: <the spoken opening line>
HOOK_CAPTION: <3–6 word on-screen text>
HOOK_IMAGE: <one-sentence conceptual illustration for this beat>
BEAT 1: <spoken line>
BEAT 1 CAPTION: <on-screen text>
BEAT 1 IMAGE: <one-sentence conceptual illustration>
BEAT 2: <spoken line>
BEAT 2 CAPTION: <on-screen text>
BEAT 2 IMAGE: <one-sentence conceptual illustration>
...
CLOSE: <spoken closing line>
CLOSE_CAPTION: <on-screen text>
CLOSE_IMAGE: <one-sentence conceptual illustration>
HASHTAGS: <6–10 story-specific tags — geography that fits the story; brand tags added by the engine>
```

## Example (illustrative — the ethanol/E20 water angle)
```
TITLE: E20 — the water no one's counting
PLACE: India
HOOK: India's new petrol is 20% ethanol. Here's the cost nobody's putting on the pump.
HOOK_CAPTION: The hidden cost of E20
HOOK_IMAGE: A fuel pump nozzle pouring not fuel but a thin stream of water into a dry cracked bowl.
BEAT 1: That ethanol is made from crops — and the most water-hungry ones. Rice-based ethanol can take around ten thousand litres of water for a single litre of fuel.
BEAT 1 CAPTION: ~10,000 L water → 1 L ethanol (rice)
BEAT 1 IMAGE: An enormous water droplet towering over a single tiny fuel drop, stacked paddy field terraces below.
BEAT 2: And the distilleries drawing that water sit in states the Central Ground Water Board already flags as critical.
BEAT 2 CAPTION: Built where groundwater is critical
BEAT 2 IMAGE: A cross-section of ground showing a falling water table beneath a cluster of industrial chimneys and a straw drawing from it.
BEAT 3: The sugar industry disputes the exact figure — but even they agree the direction is up.
BEAT 3 CAPTION: Industry disputes the number, not the trend
BEAT 3 IMAGE: Two arrows of different lengths pointing the same way up a slope, one solid and one dashed.
CLOSE: So before the next blend target, one question: do we have the water to burn?
CLOSE_CAPTION: Do we have the water to burn?
CLOSE_IMAGE: An empty well shaft with a fuel gauge dial at its bottom pointing to empty.
HASHTAGS: Ethanol E20 WaterCrisis Groundwater FoodVsFuel India FuelPolicy
```
