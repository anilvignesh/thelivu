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


def render_kinetic_subshot_clip(image_path, caption, duration_s, out_mp4, dark=True,
                                idx=0, n_total=1):
    """One sub-shot's silent clip. Returns out_mp4 on success, None on any
    failure — caller (build_reel) falls back to the static renderer for this
    sub-shot when this returns None.

    `idx`/`n_total` drive the progress bar — same meaning as draw_illustrated_
    frame's idx/n_illustrated (beat position, not sub-shot position: the
    static style's own comment on this is "sub-shots are one idea seen from
    two angles, so counting them would tell the viewer the story is longer
    than it is" — kinetic keeps that same rule)."""
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
        # First test render (2026-08-19) caught this: a scrim close in hue to
        # the art's OWN sky tone barely shows even at high opacity — a same-
        # hue wash over a same-hue background is nearly a no-op. These are
        # deliberately a clear step darker/more saturated than either
        # STYLE's ground tone, at opacity high enough to guarantee contrast
        # regardless of what's underneath — the one job a scrim has.
        scrim_hex = "#0A0806" if dark else "#D9C79A"
        scrim_opacity = 0.88
        muted_hex = "#C8C0AF" if dark else "#5A4E38"
        kraft_dim_hex = "#968A6E"
        # t2c: Manim colours by exact substring match, so build it from the
        # SAME per-word highlight test the static caption uses.
        t2c = {w: accent_hex for w in set(caption.split()) if _is_highlight_token(w)}
        bar_frac = max(0.0, min((idx + 1) / max(n_total, 1), 1.0))

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

        # Top AND bottom scrims — content-agnostic legibility for the masthead
        # and caption respectively, same job the static style's gradient scrim
        # does (publishing/reel_illustrated.py _scrims). A first test render
        # caught the masthead going nearly invisible with no top scrim at all.
        bottom_scrim = Rectangle(width=config.frame_width, height=config.frame_height * 0.42,
                                 fill_color={scrim_hex!r}, fill_opacity={scrim_opacity},
                                 stroke_width=0)
        bottom_scrim.to_edge(DOWN, buff=0)
        bottom_scrim.set_z_index(1)
        self.add(bottom_scrim)

        top_scrim = Rectangle(width=config.frame_width, height=config.frame_height * 0.16,
                              fill_color={scrim_hex!r}, fill_opacity={scrim_opacity} * 0.8,
                              stroke_width=0)
        top_scrim.to_edge(UP, buff=0)
        top_scrim.set_z_index(1)
        self.add(top_scrim)

        mark = Text("THELIVU", font="DejaVu Sans Mono", weight=BOLD, font_size=34,
                    color={accent_hex!r})
        mark.set_z_index(2)
        mark.to_corner(UL, buff=0.55)
        self.add(mark)
        dot = Text(" · reel", font="DejaVu Sans Mono", font_size=28, color={fg_hex!r})
        dot.set_z_index(2)
        dot.next_to(mark, RIGHT, buff=0.05)
        dot.align_to(mark, DOWN)
        self.add(dot)

        caption = Text({wrapped!r}, font={FONT_FAMILY!r}, weight=BOLD,
                       font_size={font_size}, color={fg_hex!r}, line_spacing=1.15,
                       t2c={t2c!r})
        caption.width = min(caption.width, config.frame_width * 0.82)
        caption.move_to(bottom_scrim.get_center() + UP * 0.35)
        caption.set_z_index(2)

        # Progress bar + sources footer — reel_illustrated.py's own docstring
        # calls these "signature elements, not theme variables"; kinetic
        # carries them exactly like the static style does, not as an option.
        bar_y = -config.frame_height / 2 + 1.55
        bar_w = config.frame_width * 0.80
        left_x = -bar_w / 2
        bar_track = Line([left_x, bar_y, 0], [left_x + bar_w, bar_y, 0],
                         stroke_color={kraft_dim_hex!r}, stroke_width=3)
        bar_track.set_z_index(2)
        self.add(bar_track)
        bar_fill = Line([left_x, bar_y, 0], [left_x + bar_w * {bar_frac}, bar_y, 0],
                        stroke_color={accent_hex!r}, stroke_width=6)
        bar_fill.set_z_index(2)
        self.add(bar_fill)
        footer = Text("thelivu.reports · sources in bio", font="DejaVu Sans Mono",
                      font_size=24, color={muted_hex!r})
        footer.move_to([left_x + footer.width / 2, bar_y - 0.45, 0])
        footer.set_z_index(2)
        self.add(footer)

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
