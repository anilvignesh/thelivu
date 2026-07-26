"""Illustrated reel frames + the sign-off card — the reel #9 look, productionized.

Ported from `docs/plans/reel-prototype/assemble_v2_inkdark.py`, which built the
first published illustrated reel by monkeypatching `reel._render_frame`. Same
geometry and type; the monkeypatching is gone — `build_reel` takes a renderer.

Every frame: full-bleed illustration, a top and bottom scrim so type stays
legible over any art, the `THELIVU · reel` masthead, the serif caption with
numbers/₹/acronyms emphasised, a progress bar, and the sources footer. The reel
closes on a fixed sign-off card. See engine/BRAND.md — the mark, the wordmark,
the type pairing and the sign-off are signature elements, not theme variables.

LAPTOP-ONLY: the Malayalam glyphs come from system Noto fonts that are not
bundled in the repo (the repo serif has no Malayalam coverage). Railway never
renders reels, so that is fine — but fail loudly rather than draw tofu.
"""

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from publishing.slides import SERIF_BOLD, MONO, MONO_BOLD, PALETTE, _font
import publishing.reel as reel
from publishing.reel import W, H, _draw_emph_block

log = logging.getLogger("reel_illustrated")

ACCENT = PALETTE["dark"]["accent"]        # gold — caption highlights over the art
INK = (27, 23, 16)
CREAM = (233, 224, 201)
KRAFT_DIM = (150, 138, 110)
GOLD = (182, 158, 108)
GOLD_DIM = (150, 132, 96)

# System Noto — the repo's bundled fonts have no Malayalam glyphs.
ML_SANS_BOLD = "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Bold.ttf"
ML_SANS = "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Regular.ttf"

DESCRIPTOR = ("Fact-checked stories.",
              "Every claim verified, every piece human-reviewed.")
HANDLE = "@thelivu.reports"

# The sign-off is SILENT — see engine/BRAND.md. This is how long the card holds.
SIGNOFF_SECONDS = 2.8


def malayalam_fonts_available():
    return Path(ML_SANS_BOLD).exists() and Path(ML_SANS).exists()


def _scrims(base):
    """Darken top and bottom so the masthead and caption stay readable over any
    illustration, without flattening the middle of the art."""
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(H):
        a = 0 if y < H * 0.50 else int(230 * (y - H * 0.50) / (H * 0.50))
        sd.line([(0, y), (W, y)], fill=(18, 15, 11, min(a, 230)))
    for y in range(0, int(H * 0.18)):
        sd.line([(0, y), (W, y)], fill=(18, 15, 11, int(155 * (1 - y / (H * 0.18)))))
    return Image.alpha_composite(base.convert("RGBA"), scrim).convert("RGB")


def draw_illustrated_frame(image_path, caption, idx, n_illustrated, out_png):
    """One story frame: the illustration, scrims, masthead, caption, progress."""
    base = Image.open(image_path).convert("RGB").resize((W, H))
    img = _scrims(base)
    d = ImageDraw.Draw(img)
    pad_x = 96

    mark_f = _font(MONO_BOLD, 40)
    d.text((pad_x, 96), "THELIVU", font=mark_f, fill=ACCENT)
    d.text((pad_x + d.textlength("THELIVU", font=mark_f) + 22, 104), "· reel",
           font=_font(MONO, 32), fill=(238, 232, 222))

    f = _font(SERIF_BOLD, 92)
    _draw_emph_block(d, reel._font_safe(caption), f, int(92 * 1.14),
                     W - 2 * pad_x, int(H * 0.63), (245, 240, 230), ACCENT)

    bar_y = H - 300
    bar_w = W - 2 * pad_x
    d.line([(pad_x, bar_y), (pad_x + bar_w, bar_y)], fill=KRAFT_DIM, width=3)
    d.line([(pad_x, bar_y), (pad_x + bar_w * (idx + 1) / max(n_illustrated, 1), bar_y)],
           fill=ACCENT, width=7)
    d.text((pad_x, bar_y + 34), "thelivu.reports · sources in bio",
           font=_font(MONO, 28), fill=(200, 192, 175))
    img.save(out_png)


def draw_signoff_card(out_png):
    """The closing card: the real logo mark (ത + തെളിവ് in a gold frame), then the
    brand descriptor and handle. No tagline — see engine/BRAND.md."""
    if not malayalam_fonts_available():
        raise RuntimeError(
            f"Malayalam fonts missing ({ML_SANS_BOLD}). The sign-off card draws "
            f"ത/തെളിവ് and the bundled repo fonts have no Malayalam coverage. "
            f"Install fonts-noto (laptop-only step) or the card renders as tofu.")

    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)

    # Badge built at 800px then downscaled — keeps the glyph edges crisp.
    B = 800
    badge = Image.new("RGB", (B, B), INK)
    bd = ImageDraw.Draw(badge)
    bd.rectangle([70, 70, B - 70, B - 70], outline=GOLD, width=4)
    tha = ImageFont.truetype(ML_SANS_BOLD, 300)
    tb = bd.textbbox((0, 0), "ത", font=tha)
    bd.text(((B - (tb[2] - tb[0])) / 2 - tb[0], B * 0.30 - tb[1]), "ത", font=tha, fill=CREAM)
    nm = ImageFont.truetype(ML_SANS, 96)
    nb = bd.textbbox((0, 0), "തെളിവ്", font=nm)
    bd.text(((B - (nb[2] - nb[0])) / 2 - nb[0], B * 0.60), "തെളിവ്", font=nm, fill=CREAM)

    LW = 560
    lx = (W - LW) // 2
    ly = int(H * 0.18)
    img.paste(badge.resize((LW, LW), Image.LANCZOS), (lx, ly))

    cx = W // 2
    y = ly + LW + 90
    sf = _font(MONO, 30)
    for line in DESCRIPTOR:
        d.text((cx - d.textlength(line, font=sf) / 2, y), line, font=sf, fill=GOLD_DIM)
        y += 48
    d.text((cx - d.textlength(HANDLE, font=sf) / 2, H - 280), HANDLE, font=sf, fill=GOLD_DIM)
    img.save(out_png)


def make_renderer(image_paths):
    """Build the `render_frame` callable `build_reel` expects.

    `image_paths` is one illustration per story beat. The reel is assembled with
    one extra beat on the end (empty spoken text → a silent hold), and that last
    frame is the sign-off card.
    """
    n_ill = len(image_paths)

    def render(caption, dark, idx, total, kicker, out_png):
        if idx >= n_ill:
            return draw_signoff_card(out_png)
        return draw_illustrated_frame(image_paths[idx], caption, idx, n_ill, out_png)

    return render
