# animate pilot: Nagaland MGNREGS (2026-10-14)

First Thelivu piece made with github.com/cth9191/animate (MIT), math style re-themed to the Thelivu ink ground (#17140D),
gold = money released, red = late or missing, cream = rule/neutral. 33s, 9:16, 5 hard cuts on the 8th grid, synthesized score.

Facts (all from the findings table, source CAG Audit Report year ended 31 March 2024, Nagaland, paras 3.2.8.5-3.2.8.6):
- Funds must be passed on within 3 days (15 days from 2022-23).
- Rs 1,710.34 crore released with delays of 4 to 238 days (238 days = 34 weeks, derived).
- Rs 22.37 crore interest liability, 2019-20 and 2020-21; the "12%" is in the audit text, "a year" is not, so it is not on screen.
- State share: Rs 338.09 crore due, Rs 233.70 crore released (69%), Rs 104.39 crore short (31%). 338.09 - 233.70 = 104.39.
- Government reply (Dec 2024): noted, to be pursued; 2023-24 share released in full.

Rebuild: copy the animate skill (plugins/animate/skills/animate), put this folder at pieces/nagaland-mgnregs,
`node tools/build.mjs pieces/nagaland-mgnregs && node tools/export.mjs pieces/nagaland-mgnregs --share && node tools/review.mjs pieces/nagaland-mgnregs`.
Measured on a 12-core laptop with --workers 2: 33s of video exports in about 39s.

## v2 (2026-10-14): Thelivu frame + cloned voice-over, rendered on the Oracle VM
- Frame per BRAND.md: ink ground, gold stamp "CAG AUDIT · NAGALAND", THELIVU wordmark, progress line, handle footer,
  word-by-word captions, silent sign-off card using branding/assets/logo-hires.png (copy it to the piece's assets/logo.png).
- Voice: `voice/script.json` lines synthesised by the VM's Chatterbox (`POST localhost:3901/synth {"text","voice":"anil"}`),
  saved as voice/<id>.wav (not committed: it is a recording of Anil's voice). Word times: faster-whisper (VM venv ~/fwenv, needs `av<16`).
  Numbers are spoken in words, no bare acronyms (BRAND.md); the sign-off is silent.
- VM setup (done): Node 22 in /usr/local, Playwright chromium in /opt/pw (PLAYWRIGHT_BROWSERS_PATH), the skill in ~ubuntu/animate.
  Run: `node tools/voice.mjs P && node tools/build.mjs P && node tools/export.mjs P --share --workers 2 && node tools/review.mjs P`.
- Measured on the 2-OCPU VM: 44.5s video exports in 1m46s. Review: cuts, arc, text, dead beats PASS; -13.9 LUFS; loudest hit 30.6s after 0.5s of silence.
