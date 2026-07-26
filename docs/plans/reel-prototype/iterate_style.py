"""Style iteration for Thelivu reel illustrations — find the on-brand 'Dossier' look.
Generates the SAME 6 Varkala scenes under N style variants (FLUX.1-dev / NVIDIA, free)
so I can compare and pick. No voice/assembly here — pure visual iteration.
"""
import os, sys, base64, time, requests
from pathlib import Path
from PIL import Image

KEY = os.environ["NVIDIA_API_KEY"]
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
VARIANT = sys.argv[2]

SCENES = [
  "An iconic red laterite sea-cliff like a postcard emblem, a single hairline fracture across it, a landmark quietly under threat.",
  "Cross-section of a coastal laterite cliff: hard rock cap over soft pale clay, rainwater seeping down cracks, one block slumping toward the sea.",
  "A layered sea-cliff as a treasured natural monument, a single falling water drop motif, tiny abstract beach umbrellas below: rare heritage and livelihood.",
  "A small excavator silhouette digging on a fragile cliff top beside a simple south-indian temple gopuram outline, thin pipes trailing wastewater over the edge.",
  "Empty balanced scales of justice standing over a small sea-cliff, a heavy horizontal bar of shadow halting motion: restraint imposed from outside.",
  "Dark monsoon storm clouds gathering over a lone sea-cliff, a faint hourglass in the sky: time running out before the rains.",
]

# Variant B — 'Dossier': redaction-red single accent, kraft + ink, print grain, gravity.
STYLE_B = ("Editorial screenprint illustration in a restrained case-file palette: "
    "kraft-paper cream background (#E6DCC3), deep ink near-black (#1B1710), and ONE "
    "accent of muted redaction red (#8C2A1B). No bright orange, no teal, desaturated. "
    "Flat vector shapes, heavy grain and halftone paper texture, lots of negative space, "
    "stark grave composition, the subject small and vulnerable in the frame. Symbolic not "
    "literal. No text, no lettering, no numbers, no logos, no real faces. Somber "
    "investigative newspaper art, vertical 9:16.")

STYLES = {"B": STYLE_B}
style = STYLES[VARIANT]

def gen(scene, idx, seed=11):
    r = requests.post("https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev",
        headers={"Authorization": f"Bearer {KEY}", "Accept":"application/json"},
        json={"prompt": f"{scene} {style}", "width":768, "height":1344,
              "steps":40, "cfg_scale":3.0, "seed":seed}, timeout=120)
    r.raise_for_status()
    b64 = r.json()["artifacts"][0]["base64"]
    p = OUT / f"img_{idx}.png"; p.write_bytes(base64.b64decode(b64)); return p

imgs=[]
for i, sc in enumerate(SCENES):
    t=time.time(); p=gen(sc,i); imgs.append(p)
    print(f"  beat {i}: {p.name} ({time.time()-t:.0f}s)", flush=True)

# contact sheet
tw=360; th=int(tw*1344/768)
sheet=Image.new("RGB",(tw*3+40, th*2+30),(230,224,205))
for i,p in enumerate(imgs):
    im=Image.open(p).convert("RGB").resize((tw,th)); r,c=divmod(i,3)
    sheet.paste(im,(10+c*(tw+10), 10+r*(th+10)))
sheet.save(OUT/"contact.png"); print("contact:", OUT/"contact.png", flush=True)
