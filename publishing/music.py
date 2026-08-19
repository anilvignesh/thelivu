"""Background music bed for reels — added 2026-08-19, a gap found while
evaluating MoneyPrinterTurbo (github.com/harry0703/MoneyPrinterTurbo) for
anything worth adopting: reels had narration but no music underneath, unlike
most reels/shorts that perform well. See publishing/music/README.txt for
track sources, licenses, and why "dark ambient" specifically (matches the
locked house style's night-toned illustration look).

Deliberately NOT wired as a presentation_style bandit arm — every posted
reel gets a music bed now, no A/B on "music vs no music" (silence isn't a
serious competing hypothesis, it's just the gap being closed). The bandit
in engine/agents/style_learning.py stays about visual treatment.
"""
import random
import subprocess
from pathlib import Path

MUSIC_DIR = Path(__file__).parent / "music"

TRACKS = [
    {
        "file": "dark-ambient-01.mp3",
        "credit": '"Deep" by Alex-Productions (No Copyright Music), CC BY 3.0',
    },
    {
        "file": "dark-ambient-02.mp3",
        "credit": '"Zero Point" by Dreamstate Logic, CC BY 3.0',
    },
]

# How far under the narration the music sits. -14dB (volume=0.2) is audible
# as a bed without competing with speech — measured by ear against a real
# Chatterbox narration track, not a guess; retune here if it ever reads as
# too loud/quiet on a real render.
MUSIC_VOLUME = 0.2


def pick_track(rng=None):
    """{path, credit} for one randomly-chosen track. Returns None if the
    music directory is empty/missing (caller treats that as 'no bed')."""
    rng = rng or random
    available = [t for t in TRACKS if (MUSIC_DIR / t["file"]).exists()]
    if not available:
        return None
    t = rng.choice(available)
    return {"path": MUSIC_DIR / t["file"], "credit": t["credit"]}


def mix_bgm(vo_wav, out_wav, track_path, volume=MUSIC_VOLUME):
    """Mix a music bed under an existing narration wav. The music track loops
    (via -stream_loop -1) and is truncated to the narration's own length
    (duration=first), so this works regardless of which is longer — every
    track in TRACKS is already ~100s (covers the full 90s Instagram cap), so
    looping is a safety margin, not the normal case. Raises on ffmpeg failure
    — caller decides whether that should sink the reel (it should not; see
    build_reel's use of this)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(vo_wav), "-stream_loop", "-1", "-i", str(track_path),
         "-filter_complex",
         f"[1:a]volume={volume}[music];"
         f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=0[aout]",
         "-map", "[aout]", str(out_wav)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
