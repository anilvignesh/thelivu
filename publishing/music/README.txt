Bundled reel background music — added 2026-08-19, closing a gap found while
evaluating MoneyPrinterTurbo (github.com/harry0703/MoneyPrinterTurbo): reels
had narration but no music bed, unlike most reels/shorts that perform well.

Both tracks are CC BY 3.0 (commercial use + remixing allowed, attribution
required) from Wikimedia Commons — trimmed to a clean 100s loopable segment
(covers the full 90s Instagram cap plus buffer), fade in/out added, loudness-
normalized to -23 LUFS so it sits consistently under narration regardless of
the source track's original mastering. Picked "dark ambient" deliberately —
matches the locked house style's "night-toned and serious" illustration look
(publishing/illustrate.py), not generic upbeat stock music.

- dark-ambient-01.mp3 — "Deep" by Alex-Productions (No Copyright Music)
  Source: https://commons.wikimedia.org/wiki/File:Alex-Productions_-_Deep_(Dark_Ambient_Background_music).oga
  License: CC BY 3.0 — https://creativecommons.org/licenses/by/3.0/
  Attribution: "Deep" by Alex-Productions (No Copyright Music)

- dark-ambient-02.mp3 — "Zero Point" by Dreamstate Logic
  Source: https://commons.wikimedia.org/wiki/File:Dreamstate_Logic_-_Zero_Point_(space_ambient,_dark_ambient).ogg
  License: CC BY 3.0 — https://creativecommons.org/licenses/by/3.0/
  Attribution: "Zero Point" by Dreamstate Logic

Attribution is carried automatically in the reel caption (publishing/music.py
::pick_track() returns the credit line, publishing/make_reel.py appends it) —
no on-screen watermark needed, same reasoning as the font licenses above:
the requirement is satisfied, not decorative.

Add more tracks here (same trim/normalize/attribute pattern) as the rotation
needs variety — see publishing/music.py TRACKS.
