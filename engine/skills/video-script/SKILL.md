---
name: video-script
description: Turn a human-approved, already-published Thelivu article into a spoken script for a short (<60s) AI-avatar Instagram Reel — the same story as the carousel, but voiced. Produces the presenter's spoken lines plus on-screen caption beats. Judgment/writing task — routes to Claude. Produces a script only; never publishes.
---

# Video Script (the reel)

Turns a verified article into a **≤60-second spoken script** for a short vertical
Reel where a stylized Thelivu presenter voices the story. Reels are the reach
surface — this is the same argument as the carousel, compressed to what a person can
say in under a minute, written for the ear and for a muted viewer reading captions.

This skill enforces the project's editorial charter (`../../CHARTER.md`) and brand
(`../../BRAND.md`). Read them if present; the charter governs in any conflict. It
writes a script only — it never fabricates, never overstates, and never publishes.

## Hard rules (same spine as the rest of the engine)
- **Only what the article established.** No new claims, no numbers not in the piece,
  no fabricated quotes. If the article hedged, the script hedges (say "alleged,"
  "reportedly," "the records suggest").
- **Attribute the load-bearing facts** in the voice line itself ("the CAG report
  found…", "court records show…") — a spoken claim with no source is not Thelivu.
- **Transparent perspective:** you may argue the article's view, openly — but signal
  when it's a view, not a fact.
- Named living people: documented facts and contested processes only, never asserted
  wrongdoing. Defamation care applies at spoken pace too.

## Shape (write for the ear, and for muted viewing)
- **Total: 110–135 words** (~40–50s at a natural pace). Do not exceed.
- **Hook (first 3 seconds / ~1 sentence):** the sharpest fact or the stakes. This is
  the whole reel's fate — earn the next 3 seconds. No throat-clearing, no "in this
  video."
- **Body (3–4 short beats):** the key fact → the context that reframes it → the
  evidence → the turn. One idea per beat, plain spoken sentences, short words.
- **Close (1 line):** the "so what," or the question left hanging. Then a soft share
  cue is allowed once ("send this to someone who should see it") — never engagement
  bait.
- Every spoken line has a paired **CAPTION** beat: a tight on-screen version (most
  viewers watch muted) — not a transcript, the 3–6 word gist that reinforces the VO.

## Output (exactly this, nothing else)
```
TITLE: <short internal title>
HOOK: <the spoken opening line>
HOOK_CAPTION: <3–6 word on-screen text>
BEAT 1: <spoken line>
BEAT 1 CAPTION: <on-screen text>
BEAT 2: <spoken line>
BEAT 2 CAPTION: <on-screen text>
...
CLOSE: <spoken closing line>
CLOSE_CAPTION: <on-screen text>
HASHTAGS: <6–10 story-specific tags — geography that fits the story; brand tags added by the engine>
```

## Example (illustrative — the ethanol/E20 water angle)
```
TITLE: E20 — the water no one's counting
HOOK: India's new petrol is 20% ethanol. Here's the cost nobody's putting on the pump.
HOOK_CAPTION: The hidden cost of E20
BEAT 1: That ethanol is made from crops — and the most water-hungry ones. Rice-based ethanol can take around ten thousand litres of water for a single litre of fuel.
BEAT 1 CAPTION: ~10,000 L water → 1 L ethanol (rice)
BEAT 2: And the distilleries drawing that water sit in states the Central Ground Water Board already flags as critical.
BEAT 2 CAPTION: Built where groundwater is critical
BEAT 3: The sugar industry disputes the exact figure — but even they agree the direction is up.
BEAT 3 CAPTION: Industry disputes the number, not the trend
CLOSE: So before the next blend target, one question: do we have the water to burn?
CLOSE_CAPTION: Do we have the water to burn?
HASHTAGS: Ethanol E20 WaterCrisis Groundwater FoodVsFuel India FuelPolicy
```
