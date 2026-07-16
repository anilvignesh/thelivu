# Thelivu — AI-avatar Reels: research & build plan

*Research doc, 2026-07-16. Goal (Anil): short AI-avatar videos — someone speaks the
story, under ~1 minute, "nothing fancy," same posts as the carousels but as Reels.
"Do research, build, take a call later." This is the plan + a ready-to-wire script
skill; the paid/expensive integration is deferred to Anil's call.*

## Why Reels
Instagram pushes **Reels to non-followers** far harder than carousels — it's the
discovery/reach surface. A <60s explainer reel per story is the single biggest reach
lever we have, and it reuses the verified article we already produce.

## The pipeline (5 stages)
```
verified article ─► 1. SCRIPT ─► 2. VOICE ─► 3. AVATAR ─► 4. ASSEMBLE ─► gate ─► 5. POST(Reel)
```
1. **Script** — new `video-script` skill: article → ~40–50s spoken script (~110–130
   words) + on-screen caption beats. Same discipline as everything else: sourced, no
   fabrication, transparent perspective. (Skill written, not yet wired — see
   `engine/skills/video-script/SKILL.md`.)
2. **Voice (TTS)** — turn the script into audio. Options below.
3. **Avatar** — a talking head from a **brand presenter image** + the voice audio.
   This is the one genuinely new capability. Options below.
4. **Assemble** — ffmpeg: 9:16 canvas, dossier framing, **burned-in captions**
   (most watch muted — non-negotiable for reach + accessibility), Thelivu logo, one
   source line. Also satisfies the IG rule that audio must be embedded in the file.
5. **Post** — Reels via Graph API, video served from our own slide/file server
   (same public-URL pattern as carousel images).

## Stage options + cost

**Voice (TTS):**
| Option | Cost | Notes |
|---|---|---|
| **Piper (local)** | **free** | Anil already runs it for Jarvis. Zero marginal cost. Good enough for VO. ← recommended start |
| ElevenLabs API | ~$5–22/mo | Best-in-class natural voice; paid |
| OpenAI / Azure TTS | ~cheap/usage | Good, paid per char |

**Avatar (the talking head):**
| Option | Cost | Effort | Notes |
|---|---|---|---|
| **HeyGen API** | pay-as-you-go from $5; Creator ~$29/mo | **lowest** | script→avatar in one call, natural lip-sync, 175+ langs. Easiest path. |
| D-ID API | credit-based | low | talking head from a photo + audio; streaming too |
| **Open-source via Replicate** (Wav2Lip / MuseTalk) | **~$0.01–0.05 per run** | medium | run the OS models on rented GPU — no local GPU needed; brand still-image + Piper audio → lip-synced clip. Cheapest at scale, most control. MuseTalk = near-photoreal (2026). |
| Local (Wav2Lip/SadTalker/MuseTalk) | free | high | needs a capable GPU — Anil's hardware is modest (Ollama was dropped as too slow), so **local is likely impractical**. |
| VEED Fabric 1.0 API | $0.08/sec (480p) | low | ~$3.60 for a 45s clip — pricey for daily |

**Post (Instagram Reels API) — confirmed workable:**
- 3-step publish: `POST /{ig-user-id}/media` with `media_type=REELS` + public
  `video_url` → poll container `status_code` until `FINISHED` → `media_publish`.
- **Eligibility: 5–90s, 9:16 aspect ratio** — our <60s target fits perfectly.
- Audio must be **baked into the file** (no IG music library via API — fine, we use VO).
- We already host public assets → serve the MP4 the same way we serve slide PNGs.

## Recommendation — two paths, your call

- **Path A — cheapest, most control (recommended MVP):** `video-script` skill →
  **Piper (free) VO** → **open-source lip-sync via Replicate (~cents/run)** on a
  fixed **brand presenter image** → ffmpeg framing + captions → Reels API. Marginal
  cost ≈ **a few cents per video**; no local GPU, no monthly floor.
- **Path B — easiest, highest quality:** `video-script` skill → **HeyGen API**
  (script→avatar in one call, ~$29/mo for daily shorts) → light ffmpeg framing →
  Reels API. Least engineering, cleanest output, predictable monthly cost.

Start A to validate cheaply; switch to B if the OS avatar quality disappoints.

## Brand & trust caveat (important for a *journalism* outlet)
A photorealistic AI human that looks like a real person **undercuts a
verification-first brand** — it reads as a deepfake. Recommendation: a **clearly
stylized / illustrated brand presenter** (obviously an animation, not a real
person), keep the existing "AI-assisted, human-reviewed" label, and never
face-clone a real individual. The dossier aesthetic suits a stylized anchor well.
(If we ever want zero avatar: a faceless kinetic-typography reel with Piper VO +
animated dossier slides is an even simpler fallback — but Anil asked for a speaker.)

## Build plan (phased; each stage testable alone)
- **V0 (free, no decision needed):** ship the `video-script` skill; generate + eyeball
  scripts from real articles. Validates the writing before spending on video.
- **V1:** Piper VO + ffmpeg → a **captioned, VO-only motion reel** (dossier slides +
  voice, no avatar yet). Already postable as a Reel; proves the pipeline + posting.
- **V2:** add the avatar (Path A Replicate, or Path B HeyGen) on the brand presenter.
- **V3:** wire the human gate (review MP4 in Telegram) + Reels auto-publish on approve.

The human gate stays absolute here too — a reel posts only on Anil's approval.

## The call to make later
1. Path A (OS/Replicate, cents) vs Path B (HeyGen, ~$29/mo).
2. The presenter: stylized illustrated anchor vs faceless kinetic-typography.
3. Which voice (Piper free vs ElevenLabs paid).
4. Cadence: every story gets a reel, or only the strongest?

Sources: [HeyGen API](https://developers.heygen.com/) · [HeyGen pricing](https://www.heygen.com/pricing) · [Best avatar APIs 2026 (VEED)](https://www.veed.io/learn/best-avatar-apis) · [Open-source lip-sync compared](https://lipsync.com/blog/open-source-lip-sync) · [SadTalker](https://github.com/OpenTalker/SadTalker) · [Instagram Reels API guide 2026](https://postproxy.dev/blog/instagram-reels-api-publishing-guide/) · [Meta content-publishing docs](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
