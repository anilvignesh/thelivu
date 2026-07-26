"""Make the Varkala reel AGAIN — script from the free NVIDIA Gemma 4 mode, illustrated,
now on the LOCKED single ink-dark theme. Reuses the 5 strong style-A illustrations
(maps to the Gemma script's 5 beats; drops the weak rainbow-strata frame) + an ink-dark
signature sign-off card. Saves to prod (kind='illustrated'). Does NOT post.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "/home/jarvis/thelivu")
from publishing.slides import SERIF_BOLD, MONO, MONO_BOLD, PALETTE, _font
import publishing.reel as reel
from publishing.reel import _draw_emph_block, W, H, parse_script
from publishing.make_reel import _build_caption
import shared.db as db

ILL = Path("/tmp/claude-1000/-home-jarvis/7bcbbf6e-3847-49fd-bf65-487d4effd64a/scratchpad/varkala_ill")
_ML_FONT = "/usr/share/fonts/truetype/noto/NotoSerifMalayalam-Bold.ttf"
# Gemma script beats → existing illustrations: hook=cliff/crack, b1=cross-section,
# b2=temple+excavator, b3=scales, close=storm. (img_2 rainbow-strata dropped.)
BEAT_IMGS = [ILL / f"img_{i}.png" for i in (0, 1, 3, 4, 5)]
imgs = [Image.open(p).convert("RGB") for p in BEAT_IMGS]

ACCENT = PALETTE["dark"]["accent"]     # ochre, for caption highlights over art
INK = (27, 23, 16); KRAFT = (230, 220, 195); KRAFT_DIM = (150, 138, 110)
RED = (140, 42, 27)                    # redaction-red — the fixed signature colour


def _illustrated_frame(caption, dark, idx, total, kicker, out_png):
    n_ill = total - 1
    if idx >= n_ill:
        return _signoff_card(out_png)
    base = imgs[idx].resize((W, H))
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(scrim)
    for y in range(H):
        a = 0 if y < H * 0.50 else int(230 * (y - H * 0.50) / (H * 0.50))
        sd.line([(0, y), (W, y)], fill=(18, 15, 11, min(a, 230)))
    for y in range(0, int(H * 0.18)):
        sd.line([(0, y), (W, y)], fill=(18, 15, 11, int(155 * (1 - y / (H * 0.18)))))
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
    d.line([(pad_x, bar_y), (pad_x + bar_w, bar_y)], fill=KRAFT_DIM, width=3)
    d.line([(pad_x, bar_y), (pad_x + bar_w * (idx + 1) / n_ill, bar_y)], fill=ACCENT, width=7)
    d.text((pad_x, bar_y + 34), "thelivu.reports · sources in bio",
           font=_font(MONO, 28), fill=(200, 192, 175))
    img.save(out_png)


_ML_SANS_B = "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Bold.ttf"
_ML_SANS   = "/usr/share/fonts/truetype/noto/NotoSansMalayalam-Regular.ttf"
GOLD = (182, 158, 108); GOLD_DIM = (150, 132, 96); CREAM = (233, 224, 201)


def _signoff_card(out_png):
    """Sign-off — the real brand logo (ത + തെളിവ് + gold frame) recreated crisp on
    ink (matches the IG profile mark, seamless), then the brand descriptor + handle.
    No tagline (Anil, 2026-07-26). Gold accent matches the actual logo, not red."""
    img = Image.new("RGB", (W, H), INK); d = ImageDraw.Draw(img)
    # logo badge (built at 800 then placed, matching the approved mockup)
    B = 800
    badge = Image.new("RGB", (B, B), INK); bd = ImageDraw.Draw(badge)
    bd.rectangle([70, 70, B - 70, B - 70], outline=GOLD, width=4)
    tha = ImageFont.truetype(_ML_SANS_B, 300)
    tb = bd.textbbox((0, 0), "ത", font=tha)
    bd.text(((B - (tb[2] - tb[0])) / 2 - tb[0], B * 0.30 - tb[1]), "ത", font=tha, fill=CREAM)
    nm = ImageFont.truetype(_ML_SANS, 96)
    nb = bd.textbbox((0, 0), "തെളിവ്", font=nm)
    bd.text(((B - (nb[2] - nb[0])) / 2 - nb[0], B * 0.60), "തെളിവ്", font=nm, fill=CREAM)
    LW = 560; lx = (W - LW) // 2; ly = int(H * 0.18)
    img.paste(badge.resize((LW, LW), Image.LANCZOS), (lx, ly))
    # descriptor + handle
    cx = W // 2; y = ly + LW + 90
    sf = _font(MONO, 30)
    for line in ("Fact-checked stories.",
                 "Every claim verified, every piece human-reviewed."):
        d.text((cx - d.textlength(line, font=sf) / 2, y), line, font=sf, fill=GOLD_DIM); y += 48
    ff = _font(MONO, 30)
    d.text((cx - d.textlength("@thelivu.reports", font=ff) / 2, H - 280),
           "@thelivu.reports", font=ff, fill=GOLD_DIM)
    img.save(out_png)


reel._render_frame = _illustrated_frame

# Sign-off = SILENT hold on the brand card (logo + descriptor shown, NO speech).
# The cloned TTS can't say the Malayalam 'Thelivu' and splicing his real clip in read
# badly, so the whole spoken sign-off is dropped (Anil, 2026-07-26). An empty-text beat
# just writes a fixed stretch of silence so the card holds cleanly at the end.
_SIGNOFF_SILENCE = 2.8
_orig_synth = reel._synth
def _synth_signoff(text, wav_path, backend=None):
    if not text.strip():
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", f"{_SIGNOFF_SILENCE:.2f}", str(wav_path)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return _SIGNOFF_SILENCE
    return _orig_synth(text, wav_path, backend)
reel._synth = _synth_signoff

fields = parse_script(Path(sys.argv[1]).read_text())
assert len(fields["beats"]) == len(imgs), f"{len(fields['beats'])} beats vs {len(imgs)} imgs"
# Sign-off = SILENT (empty spoken text → a silent hold). The logo card carries the
# brand + descriptor visually; no speech (see _synth_signoff).
fields["beats"].append(("", ""))

out = str(ILL / "varkala_v2_inkdark.mp4")
print(f"assembling {len(fields['beats'])} frames (5 illustrated + ink-dark sign-off)…", flush=True)
reel.build_reel(fields, dark=True, out_mp4=out, backend="chatterbox")
print(f"built -> {Path(out).stat().st_size // 1024} KB", flush=True)

run = db.get_run(111)
narr = " ".join(s for s, _ in fields["beats"][:-1])
cap = _build_caption(dict(fields, narration=narr), f"https://thelivu.up.railway.app/a/{run.get('slug')}")
rid = db.save_reel(111, Path(out).read_bytes(), cap, kind="illustrated")
print("SAVED_REEL_ID:", rid, flush=True)
print("PREVIEW: https://thelivu.up.railway.app/reel/%d.mp4" % rid, flush=True)
