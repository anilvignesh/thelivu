"""Assemble the illustrated Varkala reel: 6 style-A conceptual illustrations as beat
frames + a fixed SIGNATURE SIGN-OFF card as the final frame, voiced in Anil's cloned
voice, muxed by the existing reel pipeline. Saves to prod DB (kind='illustrated') for
preview. Does NOT post.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, "/home/jarvis/thelivu")
from publishing.slides import SERIF_BOLD, MONO, MONO_BOLD, PALETTE, _font
_ML_FONT = "/usr/share/fonts/truetype/noto/NotoSerifMalayalam-Bold.ttf"
import publishing.reel as reel
from publishing.reel import _draw_emph_block, W, H, parse_script
from publishing.make_reel import _build_caption
import shared.db as db

ILL = Path("/tmp/claude-1000/-home-jarvis/7bcbbf6e-3847-49fd-bf65-487d4effd64a/scratchpad/varkala_ill")
imgs = [Image.open(ILL / f"img_{i}.png").convert("RGB") for i in range(6)]
pal = PALETTE["dark"]; ACCENT = pal["accent"]
KRAFT = (230, 220, 195); INK = (27, 23, 16)

def _illustrated_frame(caption, dark, idx, total, kicker, out_png):
    n_ill = total - 1  # last frame is the sign-off card
    if idx >= n_ill:
        return _signoff_card(out_png)
    base = imgs[idx].resize((W, H))
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(scrim)
    for y in range(H):
        a = 0 if y < H * 0.50 else int(225 * (y - H * 0.50) / (H * 0.50))
        sd.line([(0, y), (W, y)], fill=(18, 15, 11, min(a, 225)))
    for y in range(0, int(H * 0.18)):
        sd.line([(0, y), (W, y)], fill=(18, 15, 11, int(150 * (1 - y / (H * 0.18)))))
    img = Image.alpha_composite(base.convert("RGBA"), scrim).convert("RGB")
    d = ImageDraw.Draw(img)
    pad_x = 96
    mark_f = _font(MONO_BOLD, 40)
    d.text((pad_x, 96), "THELIVU", font=mark_f, fill=ACCENT)
    d.text((pad_x + d.textlength("THELIVU", font=mark_f) + 22, 104), "· reel",
           font=_font(MONO, 32), fill=(238, 232, 222))
    f = _font(SERIF_BOLD, 92); line_h = int(92 * 1.14)
    _draw_emph_block(d, reel._font_safe(caption), f, line_h, W - 2 * pad_x,
                     int(H * 0.63), (245, 240, 230), ACCENT)
    bar_y = H - 300; bar_w = W - 2 * pad_x
    d.line([(pad_x, bar_y), (pad_x + bar_w, bar_y)], fill=(150, 138, 110), width=3)
    d.line([(pad_x, bar_y), (pad_x + bar_w * (idx + 1) / n_ill, bar_y)], fill=ACCENT, width=7)
    d.text((pad_x, bar_y + 34), "thelivu.reports · sources in bio",
           font=_font(MONO, 28), fill=(200, 192, 175))
    img.save(out_png)

def _signoff_card(out_png):
    """The recurring signature card — same every reel. Kraft ground, the wordmark
    lockup THELIVU + തെളിവ്, a redaction-seal rule, the tagline, sources-in-bio."""
    img = Image.new("RGB", (W, H), KRAFT); d = ImageDraw.Draw(img)
    cx = W // 2
    # seal circle (the recurring motif) centred high
    r = 90; cy = int(H * 0.34)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(140, 42, 27), width=8)
    sf = _font(MONO_BOLD, 30)
    d.text((cx - d.textlength("VERIFIED", font=sf) / 2, cy - 16), "VERIFIED",
           font=sf, fill=(140, 42, 27))
    # wordmark lockup
    wf = _font(SERIF_BOLD, 118)
    d.text((cx - d.textlength("THELIVU", font=wf) / 2, cy + r + 60), "THELIVU",
           font=wf, fill=INK)
    from PIL import ImageFont
    mf = ImageFont.truetype(_ML_FONT, 70)
    d.text((cx - d.textlength("തെളിവ്", font=mf) / 2, cy + r + 200), "തെളിവ്",
           font=mf, fill=(90, 78, 58))
    # rule
    d.line([(cx - 260, cy + r + 320), (cx + 260, cy + r + 320)], fill=(140, 42, 27), width=4)
    # tagline
    tf = _font(MONO, 40)
    tag = "The evidence, and what it means."
    d.text((cx - d.textlength(tag, font=tf) / 2, cy + r + 360), tag, font=tf, fill=INK)
    # footer
    ff = _font(MONO, 32)
    foot = "@thelivu.reports · sources in bio"
    d.text((cx - d.textlength(foot, font=ff) / 2, H - 300), foot, font=ff, fill=(120, 104, 78))
    img.save(out_png)

reel._render_frame = _illustrated_frame

fields = parse_script(Path(sys.argv[1]).read_text())
# append the signature sign-off beat (short spoken tag ties audio to the card)
fields["beats"].append(("Thelivu. The evidence, and what it means.",
                        "The evidence, and what it means."))

out = str(ILL / "varkala_illustrated_signed.mp4")
print(f"assembling {len(fields['beats'])} frames (6 illustrated + sign-off)…", flush=True)
reel.build_reel(fields, dark=True, out_mp4=out, backend="chatterbox")
print(f"built -> {Path(out).stat().st_size // 1024} KB", flush=True)

run = db.get_run(111)
# caption: drop the sign-off tag line from the narration so the IG description reads clean
narr_beats = fields["beats"][:-1]
fields_for_cap = dict(fields, narration=" ".join(s for s, _ in narr_beats))
cap = _build_caption(fields_for_cap, f"https://thelivu.up.railway.app/a/{run.get('slug')}")
rid = db.save_reel(111, Path(out).read_bytes(), cap, kind="illustrated")
print("SAVED_REEL_ID:", rid, flush=True)
print("PREVIEW: https://thelivu.up.railway.app/reel/%d.mp4" % rid, flush=True)
