# Mistakes Log

A running record of bugs, bad publishes, and near-misses in the live system —
what broke, what a viewer/reader actually saw, root cause, and the fix. Not a
changelog (that's git log) and not a design doc (that's the rest of `docs/`) —
this is specifically *things that went wrong in production*, kept in one place
so the same class of failure is recognizable next time instead of rediscovered
from scratch.

**Add an entry every time something ships broken or nearly does** — a bad
render, a wrong fact, a duplicate post, a stuck pipeline, anything Anil had to
catch or undo by hand. Newest first. Use the template at the bottom.

---

## 2026-08-29 — Same leak, different shape: the first fix didn't generalize

**What happened:** Reel #72 (run #186), same class of bug as 2026-08-26 below
— caught this time BEFORE posting (Anil: "check reel 72" -> "what is
happening to this. all the reasoning and internal things are bleeding into
the reel"). Two of six cards were broken: the HOOK_CAPTION read `"3-6 word
text. Maybe:"` — a near-verbatim echo of SKILL.md's own `<3–6 word on-screen
text>` template placeholder — and the CLOSE_CAPTION read the bare word
`"Question"`, echoing the Close section's own prose description of itself
("the question left hanging") as a category label rather than real text.

**Root cause:** The 2026-08-26 fix (`_sane_caption()`) only checked for a
`(N words)` parenthetical and a 14-word ceiling — a pattern matched to the
ONE leaked string seen at the time, not the general class of problem. Neither
signal fired here: no parentheses, and both leaks were short (5 words, 1
word). The underlying issue is prompt ambiguity in `video-script/SKILL.md` —
the model was confusing the format template's instructional placeholders and
category descriptions for literal desired output, in two different spots in
the same skill.

**Fix:** Two layers, not one this time. (1) Source fix in `SKILL.md` itself —
an explicit anti-pattern note naming both failures and what to write instead,
matching how this codebase already prefers to fix generation problems over
patching downstream. (2) Broadened `_sane_caption()`: a template-echo phrase
check (no real caption says "on-screen text" or "word text") and an
exact-match check against bare meta words (question/hook/close/caption/beat/
title) a real caption never consists of alone. Verified against both leaked
strings AND every caption in SKILL.md's own worked example (no false
positives). Commit `54b5e69`.

**Honest caveat:** this is the second regex-shaped patch for what is
ultimately a semantic problem (the model narrating its own process instead of
producing content) — the SKILL.md fix is the one actually addressing the
cause; `_sane_caption()` is still pattern-matching known shapes and will keep
being incomplete against a shape nobody's seen yet. If a third instance shows
up with neither signal, the right move is probably a cheap LLM sanity check
per caption (Haiku, one short classification call), not a third regex.

---

## 2026-08-26 — Model's own word-count reasoning leaked onto a reel's on-screen caption

**What happened:** Reel #71 (run #203, "Kerala's Disappearing Deficit")
autopublished and posted to Instagram with a caption card reading `"Revenue
pressure" (2 words). Need 3-6. I'll do "Revenue growth slow" (3 words). Or
"Salaries consume spending" (3 words). I'll do "Revenue growth slow" (3
words).` — the video-script model's own self-correction about hitting the
3–6-word caption spec, verbatim, instead of a finished caption. Anil caught it
on Instagram ("the way the texts were shown were not pleasant") and deleted
the post by hand.

**Root cause:** Not a parsing bug — `publishing/reel.py`'s `parse_script()`
regexes (`^BEAT N CAPTION:[ \t]*(.+)$`) are deliberately single-line (see
their own comment, from an earlier HOOK/CLOSE swallow-the-next-line incident)
and faithfully captured whatever the model actually put on that line,
reasoning included. The real gap: nothing downstream ever checked a caption
was *sane* before it got rendered onto frames. `publishing/belief_reel.py`
already had this for the belief desks (`caption_ok()`, `MAX_CAPTION_WORDS`,
`_trim()`); the regular news-desk script path (`video-script` skill ->
`parse_script`) had no equivalent guard.

**Fix:** `_sane_caption()` in `publishing/reel.py` — falls back to the beat's
own spoken line (same fallback already used for an *empty* caption) whenever a
caption matches the self-talk signature (a `(N words)` parenthetical) or blows
past 14 words (spec is 3–6). Verified against the actual leaked text; a normal
short caption passes through unchanged. Commit `0aa6dd8`.

**Caveat:** the leaked text lives only in the rendered video pixels, not in
any DB column — there's no cheap way to audit *past* posted reels for the same
issue. If another one turns up, flag it.

---

## 2026-08-24 — Reveal animation could open a beat on a single stray word

**What happened:** Anil deleted two reels (#69, #70) from Instagram, calling
the text presentation "not pleasant." Diagnosis (frame-by-frame + audio
waveform, ruling out an actual frozen/corrupt render first) found: one beat's
word-by-word caption reveal opened on a single isolated word — "A" — floating
alone in an otherwise near-empty frame, mid-way through the Taj Mahal beat of
reel #69.

**Root cause:** `_reveal_word_count()` in `publishing/reel.py` apportions
reveal steps evenly (`round(per * step)`), which rounds step 0 down to a
single word whenever the caption has more words than steps (e.g. 7 words / 6
steps -> 1 word first). If that first word is a short connector ("A", "The",
"In"), it reads as a broken frame, not a deliberate beat.

**Fix:** floor of 2 words on every reveal step (was 1). One-word captions are
unaffected — they never reach this code path. Commit `8fbdd15`.

**Related, checked and NOT touched:** the underlying static-hold pacing (each
beat held ~7–13s with only an 8% Ken-Burns zoom) is deliberate, tuned design —
Anil already ruled out adding more shot-cuts per beat on 2026-07-31 ("same
text, different image... a slideshow shuffle that spends the viewer's
attention and returns nothing"). Did not re-litigate that call.

---

## 2026-08-24 — Autopost sweep silently stopped for hours whenever the daily budget cap tripped

**What happened:** Anil suspected reels weren't posting autonomously with
confidence. Diagnostic (Railway logs + prod DB) confirmed: reel #70 sat in
`status='ready'` for 3.5+ hours, unposted, despite the autopost sweep logic
being sound (41 reels had posted successfully before this).

**Root cause:** `run_autopublish_sweep()` and `run_youtube_backfill_sweep()`
(in `engine/distribution/sweep.py`, called from `run.py`) sat *below* the
daily budget governor's `continue` in the orchestrator tick loop — so every
day the $1.00 cap tripped (often within ~40 min of the midnight UTC reset),
the sweep stopped firing entirely, for hours, even though posting a
already-rendered reel/carousel calls no LLM anywhere in its path (verified:
`publish_run` / `post_carousel_run` / `post_reel_run` / `recommend_now` are
DB writes + Graph/YouTube HTTP only). This directly contradicted the file's
own documented intent — a whole section already existed, commented
"Deliberately ABOVE the quota breaker... publishing must stay alive" — for
IG sync, YouTube sync, and model health, but the actual autopost sweep was
never moved into it.

**Fix:** moved both sweeps above the breaker/budget checks, same section,
same pattern as the sibling blocks. Verified live: reel #70 posted 91ms
before the next "Model stages paused" log line — sweep runs, LLM spend stays
capped. Commit `bf856e7`.

---

## Template

```
## YYYY-MM-DD — <one-line summary of what a viewer/reader actually saw>

**What happened:** <the observable symptom, and how it was caught>

**Root cause:** <the actual mechanism — not just "a bug," the specific code
path and why it did the wrong thing>

**Fix:** <what changed, where, commit hash>

**Caveat / not fixed:** <anything left open, anything deliberately NOT
touched and why>
```

## Related

- `START-HERE.md` §6 (file map) points here.
- `docs/HANDOFF.md` — the operational/ops-access doc this complements; that
  one is "how the system is wired," this one is "what has gone wrong in it."
