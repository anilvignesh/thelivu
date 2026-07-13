"""Render a Thelivu Instagram slide in the "Dossier" visual identity — the
kraft-paper, redaction-stamp case-file look locked in engine/BRAND.md.

Pure Pillow (no browser). This runs unattended on the orchestrator's Railway
service on every article approval, so it deliberately avoids Playwright/
Chromium — a headless-browser dependency would mean apt-level system packages
in the build and a real chance of a broken deploy that's hard to debug
remotely. Pillow is pure Python; fonts are bundled in publishing/fonts/
(Liberation Serif for headlines, DejaVu Sans Mono for body/stamp/footer — both
permissively licensed, see publishing/fonts/*.txt) so rendering never depends
on what fonts (if any) happen to be installed in the container.

Headline and sub-line are pulled from an approved article draft via
publishing.parser (same parser telegram.py uses) so a slide always says the
same thing the article says — no separate copy to keep in sync. They can also
be passed directly for one-off slides.

Usage:
  python -m publishing.slides --draft articles/drafts/thelivu-kerala-health-audit-ENGINE.md --out out/slide.png
  python -m publishing.slides --headline "..." --sub "..." --stamp "FACT vs ALLEGATION" --dark --out out/slide.png
"""
import argparse
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from publishing.parser import parse_article

WIDTH, HEIGHT = 1080, 1350
PAD_X, PAD_TOP, PAD_BOTTOM = 90, 100, 90

FONT_DIR = Path(__file__).parent / "fonts"
SERIF_BOLD = FONT_DIR / "LiberationSerif-Bold.ttf"
# DejaVu Sans Mono, not Liberation Mono — Liberation Mono is missing ₹ (U+20B9)
# and other currency/Indic-adjacent glyphs, which given this is Kerala/India
# financial reporting shows up constantly (rendered as a tofu box otherwise).
MONO       = FONT_DIR / "DejaVuSansMono.ttf"
MONO_BOLD  = FONT_DIR / "DejaVuSansMono-Bold.ttf"

PALETTE = {
    "light": {"bg": (230, 220, 195), "fg": (27, 23, 16),  "accent": (140, 42, 27)},
    "dark":  {"bg": (23, 20, 13),    "fg": (233, 224, 200), "accent": (210, 170, 109)},
}


def _font(path, size):
    return ImageFont.truetype(str(path), size)


def _text_w(draw, text, font):
    return draw.textlength(text, font=font)


def _wrap_to_width(draw, text, font, max_width):
    """Greedy word-wrap using actual glyph metrics."""
    words = text.split()
    if not words:
        return []
    lines, current = [], words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_w(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_block(draw, text, font_path, max_width, max_height, start_size, min_size, line_gap=1.18):
    """Shrink font size until the wrapped text block fits max_width x max_height."""
    size = start_size
    while size >= min_size:
        font = _font(font_path, size)
        lines = _wrap_to_width(draw, text, font, max_width)
        line_h = int(size * line_gap)
        block_h = line_h * len(lines)
        if block_h <= max_height:
            return font, lines, line_h
        size -= 2
    font = _font(font_path, min_size)
    lines = _wrap_to_width(draw, text, font, max_width)
    return font, lines, int(min_size * line_gap)


def _draw_spaced(draw, xy, text, font, fill, spacing=3):
    """Draw text with manual letter-spacing (Pillow has no native support)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += _text_w(draw, ch, font) + spacing
    return x - xy[0] - spacing


def _draw_dashed_line(draw, x0, x1, y, fill, dash=14, gap=10, width=2):
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash, x1), y)], fill=fill, width=width)
        x += dash + gap


def _draw_stamp(canvas, draw, text, x, y, accent, mono_bold_size=24):
    """Rotated bordered stamp, top-left. Returns nothing; draws in place."""
    label = text.upper()
    font = _font(MONO_BOLD, mono_bold_size)
    pad_x, pad_y, border = 22, 14, 3
    text_w = sum(_text_w(draw, ch, font) + 3 for ch in label) - 3
    text_h = mono_bold_size
    box_w, box_h = int(text_w + pad_x * 2), int(text_h + pad_y * 2)

    stamp_img = Image.new("RGBA", (box_w + 8, box_h + 8), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(stamp_img, "RGBA")
    sdraw.rectangle([4, 4, box_w + 3, box_h + 3], outline=accent + (255,), width=border)
    _draw_spaced(sdraw, (4 + pad_x, 4 + pad_y - 2), label, font, accent + (255,), spacing=3)

    stamp_img = stamp_img.rotate(3, expand=True, resample=Image.BICUBIC)
    canvas.paste(stamp_img, (x, y), stamp_img)


def render_dossier_slide(headline, sub="", stamp="VERIFIED",
                          footer="Thelivu · link in bio", dark=False,
                          out="slide.png"):
    """Render one Dossier-style slide PNG (1080x1350) to `out`. Returns `out`."""
    colors = PALETTE["dark"] if dark else PALETTE["light"]
    bg, fg, accent = colors["bg"], colors["fg"], colors["accent"]

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img, "RGBA")
    content_w = WIDTH - 2 * PAD_X

    cursor_y = PAD_TOP
    if stamp:
        _draw_stamp(img, draw, stamp, PAD_X, cursor_y, accent)
        cursor_y += 90

    # Reserve space at the bottom for sub + footer before laying out the headline,
    # so the headline never collides with them.
    bottom_h = 0
    sub_lines, sub_font, sub_line_h = [], None, 0
    if sub:
        sub_font = _font(MONO, 28)
        sub_lines = _wrap_to_width(draw, sub, sub_font, content_w)
        sub_line_h = int(28 * 1.5)
        bottom_h += 30 + sub_line_h * len(sub_lines)  # dashed rule + gap + lines
    foot_font = _font(MONO, 20)
    if footer:
        bottom_h += 32 + 20  # margin + line height

    headline_top = cursor_y + 48
    headline_max_h = HEIGHT - PAD_BOTTOM - bottom_h - headline_top
    hl_font, hl_lines, hl_line_h = _fit_block(
        draw, headline, SERIF_BOLD, content_w, headline_max_h,
        start_size=76, min_size=40,
    )
    hl_block_h = hl_line_h * len(hl_lines)
    # Center the headline in the space between the stamp and the bottom block.
    available_h = HEIGHT - PAD_BOTTOM - bottom_h - headline_top
    hl_y = headline_top + max(0, (available_h - hl_block_h) // 2)
    for line in hl_lines:
        draw.text((PAD_X, hl_y), line, font=hl_font, fill=fg + (255,))
        hl_y += hl_line_h

    bottom_y = HEIGHT - PAD_BOTTOM - bottom_h
    if sub:
        _draw_dashed_line(draw, PAD_X, WIDTH - PAD_X, bottom_y, accent + (170,))
        y = bottom_y + 30
        for line in sub_lines:
            draw.text((PAD_X, y), line, font=sub_font, fill=fg + (255,))
            y += sub_line_h
        bottom_y = y + 32
    elif footer:
        bottom_y += 32

    if footer:
        _draw_spaced(draw, (PAD_X, bottom_y), footer.upper(), foot_font,
                     fg + (190,), spacing=2)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def from_draft(draft_path, stamp="VERIFIED", footer="Thelivu · link in bio",
                dark=False, out="slide.png", headline=None, sub=None):
    """Derive headline/sub from an article draft's title/hook and render."""
    md = Path(draft_path).read_text(encoding="utf-8")
    article = parse_article(md)
    return render_dossier_slide(
        headline=headline or article.title,
        sub=sub if sub is not None else article.hook,
        stamp=stamp, footer=footer, dark=dark, out=out,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draft", help="article draft (.md) to pull headline/sub from")
    ap.add_argument("--headline", help="override, or standalone headline text")
    ap.add_argument("--sub", help="override, or standalone supporting line")
    ap.add_argument("--stamp", default="VERIFIED",
                     help='top-left stamp text, e.g. "VERIFIED", "FACT vs ALLEGATION" (empty string hides it)')
    ap.add_argument("--footer", default="Thelivu · link in bio")
    ap.add_argument("--dark", action="store_true", help="use the dark-kraft variant")
    ap.add_argument("--out", default="slide.png")
    args = ap.parse_args()

    if args.draft:
        out = from_draft(args.draft, stamp=args.stamp, footer=args.footer,
                          dark=args.dark, out=args.out,
                          headline=args.headline, sub=args.sub)
    elif args.headline:
        out = render_dossier_slide(args.headline, sub=args.sub or "", stamp=args.stamp,
                                    footer=args.footer, dark=args.dark, out=args.out)
    else:
        sys.exit("Provide --draft or --headline.")

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
