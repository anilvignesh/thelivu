# Plan 02 — Productionize the illustrated reel pipeline

**Goal:** `make_narrated_reel()` produces the ink-dark ILLUSTRATED reel (the
reel #9 look — live at instagram.com/reel/DbQB49ajk0l/) instead of text-slide
frames, end to end from the CC's "Make reel" button. Text-slide frames remain
the fallback when illustration generation fails.

**The prototype is rescued and canonical:** `docs/plans/reel-prototype/`
- `assemble_v2_inkdark.py` — the WHOLE look: illustrated frames (full-bleed art,
  bottom scrim gradient, `THELIVU · reel` masthead in accent, serif caption via
  `reel._draw_emph_block` + `_font_safe`, progress bar, footer), and the
  ink-dark **sign-off card** (ത mark + തെളിവ് + gold frame + descriptor).
  Read it first; port, don't reinvent.
- `build_illustrated_varkala.py` + `iterate_style.py` — the FLUX.1-dev call
  shape against NVIDIA (same free `NVIDIA_API_KEY`) and the locked style
  prompt ("style A"). `varkala_ill/img_*.png` are reference outputs — keep
  them; they're the visual regression baseline.
- `signoff_inkdark.png` — reference sign-off card render.

## Brand locks (2026-07-26 — non-negotiable, see plan 03)

Single **ink-dark** theme (no light variant for reels). **GOLD** accent for the
sign-off mark/frame (matches the real IG logo). The sign-off is **SILENT** —
TTS cannot pronounce "തെളിവ്" and a spliced real-voice read failed (reel #8 was
posted then pulled over this); the card carries the descriptor text instead:
*"Fact-checked stories. Every claim verified, every piece human-reviewed."*
Logo asset: `branding/assets/logo-hires.png`.

## Build

1. **`publishing/illustrate.py` (new):** `generate_beat_images(beats, out_dir)`
   → list of PNG paths. FLUX.1-dev via NVIDIA (call shape from
   `build_illustrated_varkala.py`), one image per narration beat, style-A
   prompt prefix locked as a module constant. Per-image failure → return None
   for that slot. Runs locally (the laptop calls NVIDIA; Railway never renders
   reels). Respect RAM: generate serially, don't hold all PIL images open.
2. **Port the frame builders** from `assemble_v2_inkdark.py` into
   `publishing/reel.py` (or a new `publishing/reel_illustrated.py` importing
   reel's helpers): `_illustrated_frame(...)` + `_signoff_card(...)`. Mind the
   Malayalam fonts (`NotoSerifMalayalam-Bold` / `NotoSansMalayalam-*` at
   /usr/share/fonts — laptop-only paths; assert with a clear error).
3. **Wire `publishing/make_reel.py`:** after the script (free Gemma) and before
   TTS, call `generate_beat_images`. All images OK → illustrated frames; any
   missing → current text-slide path for the whole reel (no mixed reels).
   Sign-off: video gets the card for its final seconds with NO narration audio
   over it (see how assemble_v2 pads the tail). Keep `progress()` callbacks —
   the CC job UI shows them. Save with `kind='illustrated'`.
4. **Timing model:** narration beats drive per-frame durations exactly as
   `parse_script`/reel.py does today; the sign-off gets a fixed ~2.5-3s tail
   (match reel #9 by eye — Anil reviews before posting anyway).
5. **CC touch (tiny):** Reels view already previews and posts; add the `kind`
   to the reel card label. Nothing else — "Make reel" flows through unchanged.

## Constraints / gotchas

- Voice server Chatterbox on :3901 (`~/.jarvis/reel-voice.sh start`), CPU
  ffmpeg, 14GB RAM box — stop the voice server when done (CC System view has
  the button). FLUX generation is the slow step (~tens of seconds/image);
  6-beat reel ≈ few minutes total — fine, it's a background job in the CC.
- Acronyms: spoken lines write them out, slides show them
  (`_is_highlight_token` handling stays).
- `_font_safe` guard stays — fonts lack ≈, smart quotes, →.
- **Never post in tests.** Build against prod DB is fine (save_reel is not
  publishing); posting stays behind the CC/bot confirm.

## Test

1. Rebuild the Varkala reel (run 110's draft or the rescued script) and eyeball
   against `varkala_ill/` frames + reel #9.
2. Build one FRESH published run's reel end-to-end from the CC button (script →
   FLUX → voice → assemble → preview streams in the Reels view). Leave it
   `ready`; Anil posts or kills.
3. Force a FLUX failure (bad key env) → confirm clean fallback to text-slide
   frames, not a crash.
