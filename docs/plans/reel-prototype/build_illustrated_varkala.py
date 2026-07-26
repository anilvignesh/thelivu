"""Prototype: illustrated Varkala reel — one conceptual illustration per beat
(FLUX.1-dev on NVIDIA NIM, free), composited caption frames, + a signature sign-off
card, run through the existing reel voice+ffmpeg pipeline by monkeypatching the frame
renderer. Saves to prod DB as a new reel for run 111 for preview. NOT posted.
"""
import os, sys, base64, time, requests
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, "/home/jarvis/thelivu")
from publishing.slides import SERIF_BOLD, MONO, MONO_BOLD, PALETTE, _font
import publishing.reel as reel
from publishing.reel import _draw_emph_block, W, H, parse_script
from publishing.make_reel import _build_caption
import shared.db as db

WORK = Path("/tmp/claude-1000/-home-jarvis/7bcbbf6e-3847-49fd-bf65-487d4effd64a/scratchpad/varkala_ill")
WORK.mkdir(exist_ok=True)
KEY = os.environ["NVIDIA_API_KEY"]

STYLE = ("Editorial conceptual illustration, textured screenprint / risograph style, "
         "muted kraft-paper and deep ink palette with a single warm ochre accent. "
         "Flat vector shapes, grainy paper texture, strong simple symbolic composition, "
         "symbolic not literal, no text, no lettering, no numbers, no logos, no "
         "recognisable real faces. Serious newspaper editorial art, vertical 9:16.")

# One scene per beat (index order matches parse_script beats: hook,1,2,3,4,close)
SCENES = [
  "An iconic red laterite sea-cliff like a postcard emblem, a single hairline fracture running across it, quiet sense of a landmark under threat.",
  "Cross-section of a coastal laterite cliff: hard red-brown rock cap over soft pale clay, rainwater seeping down through cracks, one block slumping toward a stylised sea.",
  "A layered sea-cliff drawn as a treasured natural monument, glowing rock strata, a single water drop motif and tiny abstract beach umbrellas below, rare heritage and livelihood.",
  "A small excavator silhouette digging on a fragile cliff top beside a simple south-indian temple gopuram outline, thin pipes trailing wastewater over the cliff edge.",
  "Balanced scales of justice standing over a small sea-cliff, a heavy horizontal bar of shadow halting motion across the scene, restraint imposed from outside.",
  "Dark monsoon storm clouds gathering over a lone sea-cliff, a faint hourglass shape in the sky, a sense of time running out before the rains.",
]

def gen(scene, idx, seed=7):
    r = requests.post("https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
        headers={"Authorization": f"Bearer {KEY}", "Accept":"application/json"},
        json={"prompt": f"{scene} {STYLE}", "width":768, "height":1344,
              "steps":35, "cfg_scale":3.5, "seed":seed}, timeout=120)
    r.raise_for_status()
    b64 = r.json()["artifacts"][0]["base64"]
    p = WORK / f"img_{idx}.png"; p.write_bytes(base64.b64decode(b64)); return p

# --- generate all beat images up front ---
print("generating illustrations…", flush=True)
imgs = []
for i, sc in enumerate(SCENES):
    t=time.time(); p=gen(sc, i); imgs.append(p)
    print(f"  beat {i}: {p.name} ({time.time()-t:.0f}s)", flush=True)

pal = PALETTE["dark"]; ACCENT = pal["accent"]

def _illustrated_frame(caption, dark, idx, total, kicker, out_png):
    base = Image.open(imgs[idx]).convert("RGB").resize((W, H))
    # bottom scrim for legibility
    scrim = Image.new("RGBA", (W, H), (0,0,0,0)); sd = ImageDraw.Draw(scrim)
    for y in range(H):
        a = 0 if y < H*0.50 else int(225*(y-H*0.50)/(H*0.50))
        sd.line([(0,y),(W,y)], fill=(18,15,11, min(a,225)))
    # small top scrim so the wordmark reads on light skies
    for y in range(0, int(H*0.18)):
        a = int(150*(1-(y/(H*0.18))))
        sd.line([(0,y),(W,y)], fill=(18,15,11, a))
    img = Image.alpha_composite(base.convert("RGBA"), scrim).convert("RGB")
    d = ImageDraw.Draw(img)
    pad_x = 96
    mark_f = _font(MONO_BOLD, 40)
    d.text((pad_x, 96), "THELIVU", font=mark_f, fill=ACCENT)
    d.text((pad_x + d.textlength("THELIVU", font=mark_f)+22, 104), "· reel",
           font=_font(MONO,32), fill=(238,232,222))
    f = _font(SERIF_BOLD, 92); line_h=int(92*1.14)
    _draw_emph_block(d, reel._font_safe(caption), f, line_h, W-2*pad_x, int(H*0.63),
                     (245,240,230), ACCENT)
    bar_y=H-300; bar_w=W-2*pad_x
    d.line([(pad_x,bar_y),(pad_x+bar_w,bar_y)], fill=(150,138,110), width=3)
    if total>1:
        d.line([(pad_x,bar_y),(pad_x+bar_w*(idx+1)/total,bar_y)], fill=ACCENT, width=7)
    d.text((pad_x,bar_y+34), "thelivu.reports · sources in bio", font=_font(MONO,28),
           fill=(200,192,175))
    img.save(out_png)

reel._render_frame = _illustrated_frame  # swap only the frame renderer

fields = parse_script(Path(sys.argv[1]).read_text())
out = str(WORK / "varkala_illustrated.mp4")
print("voicing + assembling…", flush=True)
t=time.time(); reel.build_reel(fields, dark=True, out_mp4=out, backend="chatterbox")
print(f"built in {time.time()-t:.0f}s -> {Path(out).stat().st_size//1024} KB", flush=True)

run = db.get_run(111)
cap = _build_caption(fields, f"https://thelivu.up.railway.app/a/{run.get('slug')}")
rid = db.save_reel(111, Path(out).read_bytes(), cap, kind="illustrated")
print("SAVED_REEL_ID:", rid, flush=True)
print("PREVIEW: https://thelivu.up.railway.app/reel/%d.mp4" % rid, flush=True)
