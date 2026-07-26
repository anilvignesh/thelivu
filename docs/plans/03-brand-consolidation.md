# Plan 03 — Brand consolidation into BRAND.md

**Goal:** fold the 2026-07-26 brand locks (currently only in `~/HANDOFF.md` and
the reel prototype) into `engine/BRAND.md` as the single source of truth, and
commit the hi-res logo as a repo asset. Small, no runtime code.

## The locks to record (2026-07-26)

- **Single ink-dark theme** is the default surface. The kraft/light palette
  still exists for article/bio pages (`publishing/slides.py PALETTE`,
  mirrored in `biopage.py`/`articlepage.py`) — those are unchanged. Reels are
  ink-dark only.
- **GOLD accent** (`#D2AA6D`, matches the real IG logo) for the reel sign-off
  mark and frame — NOT redaction-red. Redaction-red (`#8C2A1B`) stays as the
  brick accent in the dossier palette for article pages.
- **No tagline.** The sign-off shows the **descriptor**: *"Fact-checked
  stories. Every claim verified, every piece human-reviewed."*
- **The mark** = the real logo: ത + തെളിവ് + gold frame. Repo asset now at
  `branding/assets/logo-hires.png` (rescued from ~/Downloads 2026-07-26).
- **Reels are the default reach surface; carousels are optional** — the
  "receipts" deep-dive for stories that merit it (already reflected in the
  carousel code + CC copy).
- **Silent sign-off** on reels: TTS can't pronounce "തെളിവ്"; a spliced
  real-voice read failed (reel #8 pulled). The card is shown, nothing spoken.

## Do

1. Read `engine/BRAND.md` as-is. Add/replace a "Reels & sign-off (2026-07-26)"
   section with the above; reconcile any stale palette/tagline lines.
2. Confirm the palette hexes in BRAND.md match `publishing/slides.py PALETTE`
   (kraft `#E6DCC3` / ink `#17140D`/`#1B1710` / brick `#8C2A1B` / dark accent
   gold `#D2AA6D`) — if they drift, slides.py is authoritative for rendering;
   BRAND.md documents it.
3. Keep `branding/assets/logo-hires.png` committed (already copied in). If the
   reel sign-off should read the logo from a file rather than redraw the ത
   glyph, point plan 02's `_signoff_card` at this asset.
4. Delete the now-redundant brand-lock paragraph from `~/HANDOFF.md` once
   BRAND.md carries it (that file is the laptop-level living doc; the repo
   should own repo facts).

## Test

Doc-only. `git status` clean except the intended files; BRAND.md reads
coherently; no code imports changed.
