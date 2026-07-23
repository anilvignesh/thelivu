# Reels V1 — build context (captioned VO motion reel)

*Built 2026-07-23, implementing V1 from `docs/video-reels-research.md`. No avatar, no
paid API — proves the pipeline end to end at zero marginal cost.*

## What V1 is
A `<60s`, 1080×1920 vertical MP4 per story: a Piper voiceover reading the
`video-script` output, over the Dossier-look frames (one per beat), with the CAPTION
text burned in for muted viewers, a gentle Ken-Burns zoom, and Thelivu branding.
Postable as an Instagram Reel via the same public-URL host we use for slides.

## Spine (reuses everything we already have)
```
approved article ─► video-script (attended, no API credit) ─► reel.build_reel()
                                                                 │
                     Piper TTS (en_GB-alan, local, free) ────────┤
                     Dossier frames (Pillow, same palette/fonts) ┤
                     ffmpeg (zoompan + concat + mux) ────────────┘
                                                                 ▼
                                          articles/reels/reel_<run>.mp4 ─► gate ─► Reel
```

## Contract
- Input: the `video-script` skill output (TITLE / HOOK / HOOK_CAPTION / BEAT n /
  BEAT n CAPTION / CLOSE / CLOSE_CAPTION / HASHTAGS), a `dark` bool, an out path.
- One frame per beat (hook + beats + close). Each frame shows its CAPTION (the
  3–6 word muted-viewer gist), NOT the full spoken line.
- Per-beat audio = Piper synth of the spoken line + a short gap; the frame is held
  for exactly that duration, so caption and voice stay in sync by construction.
- Output: H.264 yuv420p + AAC, 1080×1920, 30fps, 5–90s (IG Reels eligibility).

## Aesthetic (locked to BRAND.md via slides.py)
- Palette: light kraft `(230,220,195)` / ink dark `(23,20,13)`, accent per mode.
- Fonts: NotoSerif-Bold (caption headline), DejaVuSansMono (mark, stamp, source).
- Frame layout: THELIVU mark + stamp top · big serif caption centred in the safe
  band · source/kicker + progress dots bottom, clear of IG's bottom UI overlay.

## Human gate (unchanged, absolute)
V1 renders the MP4 and stops. Posting a Reel is the same gated action as a carousel
— it goes out only on Anil's explicit approval. Auto-publish-on-approve is V3.

## Deferred (later calls, per research doc)
- Avatar presenter (Path A Replicate ~cents, or Path B HeyGen ~$29/mo).
- Telegram MP4 review + Reels auto-publish on approve (V3).
- Cadence: every story vs strongest only.
