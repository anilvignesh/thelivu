"""Kinetic-motion reel style — built on Manim Community
(github.com/ManimCommunity/manim, MIT, CPU-only), picked after checking
GitHub for existing tools rather than hand-rolling ffmpeg motion (2026-08-19,
Anil's ask — see docs/style-experiments.md).

Renders ONE beat sub-shot as a self-contained silent clip: the FLUX
illustration with a continuous gentle Ken-Burns zoom, the caption written on
in one motion, and a brief emphasis pulse on highlighted tokens (numbers,
₹-amounts, acronyms — the SAME _is_highlight_token detector the static style
uses, publishing/reel.py — not a second implementation). The clip drops
straight into build_reel()'s existing seg_paths list, so concatenation, VO
muxing, and the background-music bed downstream are completely unchanged.

Scope note (deliberate, not an oversight): the static style's per-word
progressive reveal — tightly synced to speech, and the exact thing that had
a reflow bug found and fixed earlier this session — is NOT replicated here.
Kinetic's caption writes on as one wrapped block via Manim's own Write
animation, then holds. What makes kinetic "kinetic" is the continuous zoom +
write-on + emphasis pulse, not reveal granularity; porting the wrap-once/
reveal-N-words mechanism onto Manim's character-indexed Text slicing is real
extra work, worth doing later if real engagement data asks for it — not
required to ship a genuine, distinct second style now.

Falls back to returning None on any failure (bad font registration, a Manim
subprocess error, a timeout) rather than raising — build_reel then uses the
static renderer for that one sub-shot. A kinetic problem costs one cut's
worth of motion, never the reel, same resilience pattern as the illustration
and music-mix fallbacks elsewhere in this pipeline.
"""
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
ZOOM_TARGET = 1.07  # total zoom over the WHOLE clip — same order as the static style's ZOOM_MAX
FONT_FILE = Path(__file__).parent / "fonts" / "NotoSerif-Bold.ttf"
FONT_FAMILY = "Noto Serif"
RENDER_TIMEOUT_S = 90

_font_registered = False


def _ensure_font():
    global _font_registered
    if _font_registered:
        return
    import manimpango
    manimpango.register_font(str(FONT_FILE))
    _font_registered = True


def _wrapped_caption(caption, font_size, max_width_px):
    """Wrap `caption` the same way the static style does — publishing.slides'
    _wrap_to_width, exact glyph metrics from the SAME font file — so kinetic's
    line breaks land where a viewer of the rest of the feed would expect,
    not from a second, differently-tuned wrap implementation."""
    from PIL import Image, ImageDraw
    from publishing.slides import SERIF_BOLD, _font, _wrap_to_width
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _font(SERIF_BOLD, font_size)
    lines = _wrap_to_width(d, caption, font, max_width_px)
    return "\n".join(lines)


def render_kinetic_subshot_clip(image_path, caption, duration_s, out_mp4, dark=True):
    """One sub-shot's silent clip. Returns out_mp4 on success, None on any
    failure — caller (build_reel) falls back to the static renderer for this
    sub-shot when this returns None."""
    work = None
    try:
        _ensure_font()
        from publishing.reel import _is_highlight_token

        font_size = 78
        max_w = int(W * 0.82)
        wrapped = _wrapped_caption(caption, font_size, max_w)

        accent_hex = "#D2AA6D" if dark else "#8C2A1B"
        fg_hex = "#E9E0C8" if dark else "#1B1710"
        bg_hex = "#171410" if dark else "#E8DCC3"
        scrim_hex = "#0F0D09" if dark else "#EBE0C5"
        # t2c: Manim colours by exact substring match, so build it from the
        # SAME per-word highlight test the static caption uses.
        t2c = {w: accent_hex for w in set(caption.split()) if _is_highlight_token(w)}

        work = Path(tempfile.mkdtemp(prefix="kinetic_"))
        scene_py = work / "scene.py"
        media_dir = work / "media"
        hold = max(duration_s - 0.7, 0.3)
        zoom_rate = (ZOOM_TARGET - 1.0) / max(duration_s, 0.1)

        scene_src = f'''
import manimpango
manimpango.register_font({str(FONT_FILE)!r})
from manim import *

class Beat(Scene):
    def construct(self):
        self.camera.background_color = {bg_hex!r}
        bg = ImageMobject({str(image_path)!r})
        bg.height = config.frame_height
        if bg.width < config.frame_width:
            bg.width = config.frame_width
        bg.set_z_index(0)
        self.add(bg)
        bg.add_updater(lambda m, dt: m.scale(1 + {zoom_rate} * dt))

        scrim = Rectangle(width=config.frame_width, height=config.frame_height * 0.40,
                          fill_color={scrim_hex!r}, fill_opacity=0.78, stroke_width=0)
        scrim.to_edge(DOWN, buff=0)
        scrim.set_z_index(1)
        self.add(scrim)

        mark = Text("THELIVU", font="DejaVu Sans Mono", weight=BOLD, font_size=34,
                    color={accent_hex!r})
        mark.set_z_index(2)
        mark.to_corner(UL, buff=0.6)
        self.add(mark)

        caption = Text({wrapped!r}, font={FONT_FAMILY!r}, weight=BOLD,
                       font_size={font_size}, color={fg_hex!r}, line_spacing=1.15,
                       t2c={t2c!r})
        caption.width = min(caption.width, config.frame_width * 0.82)
        caption.to_edge(DOWN, buff=1.1)
        caption.set_z_index(2)

        self.play(Write(caption), run_time=0.7)
        self.play(Indicate(caption, scale_factor=1.04, color={accent_hex!r}), run_time=0.5)
        self.wait(max({hold} - 0.5, 0.1))
'''
        scene_py.write_text(scene_src)

        result = subprocess.run(
            [sys.executable, "-m", "manim", "-qh", "--resolution", f"{W},{H}",
             "--fps", str(FPS), "--format=mp4", "-o", "beat.mp4",
             "--media_dir", str(media_dir), str(scene_py), "Beat"],
            cwd=work, capture_output=True, text=True, timeout=RENDER_TIMEOUT_S,
        )
        produced = list(media_dir.rglob("beat.mp4"))
        if result.returncode != 0 or not produced:
            log.warning("kinetic render failed (rc=%s): %s", result.returncode,
                       (result.stderr or "")[-800:])
            return None
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(produced[0], out_mp4)
        return out_mp4
    except Exception as e:
        log.warning("kinetic render raised: %s", e)
        return None
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
