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
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


def draw_illustrated_frame(image_path, caption, idx, n_illustrated, out_png, label="",
                           reveal_words=None):
    """One story frame: the illustration, scrims, masthead, caption, progress.

    `label` is the belief desk's shape-B view marker, drawn under the masthead on
    every frame. The top scrim already darkens that band, so an outlined pill
    reads over any illustration.
    """
    base = Image.open(image_path).convert("RGB").resize((W, H))
    img = _scrims(base)
    d = ImageDraw.Draw(img)
    pad_x = 96

    mark_f = _font(MONO_BOLD, 40)
    d.text((pad_x, 96), "THELIVU", font=mark_f, fill=ACCENT)
    d.text((pad_x + d.textlength("THELIVU", font=mark_f) + 22, 104), "· reel",
           font=_font(MONO, 32), fill=(238, 232, 222))
    if label:
        from publishing.reel import _draw_view_label
        _draw_view_label(d, label, pad_x, 160, ACCENT, ACCENT)

    f = _font(SERIF_BOLD, 92)
    # No _font_safe here — _draw_emph_block renders the serif's missing math
    # operators from the mono face instead of degrading them to ASCII.
    _draw_emph_block(d, caption, f, int(92 * 1.14),
                     W - 2 * pad_x, int(H * 0.63), (245, 240, 230), ACCENT, size=92,
                     reveal_words=reveal_words)

    bar_y = H - 300
    bar_w = W - 2 * pad_x
    d.line([(pad_x, bar_y), (pad_x + bar_w, bar_y)], fill=KRAFT_DIM, width=3)
    d.line([(pad_x, bar_y), (pad_x + bar_w * (idx + 1) / max(n_illustrated, 1), bar_y)],
           fill=ACCENT, width=7)
    d.text((pad_x, bar_y + 34), "thelivu.reports · sources in bio",
           font=_font(MONO, 28), fill=(200, 192, 175))
    img.save(out_png)


def render_house_ground(out_png, *, variant=0, bright=False):
    """The inked field one beat falls back to when FLUX will not illustrate it.

    Why this exists: covert action, coups and violence are a whole class of subject
    the belief desks work, and they sit against the image model's refusal boundary.
    Reel #27 (Guatemala 1954) lost its entire illustrated look to one refusal out of
    eight. The all-or-nothing rule that caused that is still right — a reel with
    three illustrations and two text slides reads as a bug — so the fix is not to
    ship the mix. It is to give the one refused beat a picture that BELONGS: same
    ink ground, same grain, same scrims, masthead, serif caption and progress bar,
    drawn by the same `draw_illustrated_frame`. What changes is that the art on it
    is a texture instead of a metaphor, which in a screenprint/riso system is an
    ordinary editorial move — an inked field between images, not a missing one.

    It is deliberately mute. A device with meaning (a redaction bar was the obvious
    candidate, and the brand owns one) would be the frame saying something about the
    story — "this was hidden" — that no verifier passed. A texture claims nothing.

    Rendered locally, so a refusal costs no further FLUX call. Deterministic per
    `variant`: the same beat gets the same field every rebuild.

    `bright` (2026-08-19) swaps the ink-dark gradient for the warm cream/kraft
    ground of the STYLE_BRIGHT experiment (publishing/illustrate.py) — without
    this, a beat FLUX refused on a bright-style reel would fall back to a dark
    card and break that reel's own consistency, the exact failure this
    function exists to prevent for the dark style.
    """
    rng = random.Random(9173 + variant)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)

    if bright:
        # Warm cream at the edges, a shade deeper kraft through the middle —
        # same depth idea as the dark gradient, lit the other way.
        top, mid, bot = (232, 222, 197), (218, 202, 168), (226, 214, 186)
        disc_fill = (140, 42, 27)  # deep-red accent, matches PALETTE['light']['accent']
    else:
        # Vertical ink gradient — near-black at the edges, a shade warmer through the
        # middle, so the field has depth instead of reading as a black slug.
        top, mid, bot = (14, 12, 9), (34, 29, 21), (12, 10, 8)
        disc_fill = (74, 61, 40)
    for y in range(H):
        t = y / (H - 1)
        a, b, f = (top, mid, t / 0.55) if t < 0.55 else (mid, bot, (t - 0.55) / 0.45)
        d.line([(0, y), (W, y)],
               fill=tuple(int(a[c] + (b[c] - a[c]) * f) for c in range(3)))

    # One soft disc where an illustration's subject would sit, high in the frame and
    # off-centre. Gives the eye a centre without depicting anything.
    cx = int(W * (0.42 + 0.16 * rng.random()))
    cy = int(H * 0.34)
    r = int(W * 0.34)
    disc = Image.new("L", (W, H), 0)
    ImageDraw.Draw(disc).ellipse([cx - r, cy - r, cx + r, cy + r], fill=140)
    disc = disc.filter(ImageFilter.GaussianBlur(int(W * 0.09)))
    img = Image.composite(Image.new("RGB", (W, H), disc_fill), img, disc)

    # Paper grain, the one thing every FLUX frame in this style has. Drawn from the
    # seeded RNG rather than `Image.effect_noise`, which draws on PIL's own
    # unseedable generator and made the same beat render a different field every
    # time. Uniform bytes average ~128, so a low-alpha blend adds tooth without
    # lifting the ink off the palette.
    grain = Image.frombytes("L", (W, H), rng.randbytes(W * H)).convert("RGB")
    img = Image.blend(img, grain, 0.055)

    img.save(out_png)
    return out_png


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

    `image_paths` is per story beat. Each entry is EITHER a single path (one
    illustration for that beat) or a list of paths — the sub-shots a long beat is cut
    into, so the picture changes every ~4s instead of once per 9-second beat. The reel
    is assembled with one extra beat on the end (empty spoken text → a silent hold),
    and that last frame is the sign-off card.

    The progress dots read the number of BEATS, not sub-shots: sub-shots are one idea
    seen from two angles, so counting them would tell the viewer the story is longer
    than it is.
    """
    n_ill = len(image_paths)

    def render(caption, dark, idx, total, kicker, out_png, shot=0, label="",
              reveal_words=None):
        if idx >= n_ill:
            # The sign-off card carries no label: it makes no claim to qualify.
            return draw_signoff_card(out_png)
        entry = image_paths[idx]
        shots = entry if isinstance(entry, (list, tuple)) else [entry]
        # Clamp rather than trust: if a beat got fewer illustrations than the split
        # asked for (a FLUX refusal on one sub-shot), hold the last good one instead
        # of raising in the middle of a 15-minute render.
        path = shots[min(shot, len(shots) - 1)]
        return draw_illustrated_frame(path, caption, idx, n_ill, out_png, label=label,
                                      reveal_words=reveal_words)

    return render
