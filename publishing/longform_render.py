"""Rendering a long-form video: script in, MP4 out.

Deliberately the SMALLEST thing that closes the chain, because long-form is
occasional (Anil, 2026-09-11: "if we find something substantial which needs a
long video we do that"). The reel pipeline can be elaborate because it runs
daily and every bug surfaces within a day. Something that runs monthly and is
elaborate will bit-rot between uses and fail on the one night it matters,
against a story that took a month to stand up.

So: reuse everything, invent as little as possible.

  reused unchanged   reel.synth_beats()      narration, real durations
                     illustrate.py           FLUX images, free
                     slides.py               fonts and palette
                     ffmpeg concat           the same two-pass assembly

  genuinely new      1920x1080 landscape composition (reels are 1080x1920)
                     chapter title cards

  deliberately NOT   RECORD document frames — the first video can hold an
                       illustration, and evidence_shot.py is ready when wanted
                     transitions, motion, kinetic captions
                     chapter timestamps corrected against real audio — the
                       word-count estimate is close enough to hand-check once

## Why landscape is not a parameter

It would have been tempting to give the reel renderer a size argument. But
every composition constant in reel_illustrated.py — scrim geometry, caption
wrap width, the 0.63 vertical anchor, padding — is tuned for a tall frame, and
a width/height swap does not transpose them. A separate small module that
borrows the palette and fonts is honest about that; one shared renderer with a
flag would quietly produce a badly-laid-out frame in whichever mode was tested
less. And the reel path is the one that must not break.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw

from publishing.slides import SERIF_BOLD, MONO, MONO_BOLD, PALETTE, _font

log = logging.getLogger("longform_render")

# YouTube long-form. The reel path is 1080x1920; nothing here is shared with it
# beyond palette and fonts.
W, H = 1920, 1080
FPS = 24

ACCENT = PALETTE["dark"]["accent"]        # gold
INK = (27, 23, 16)
PAPER = (245, 240, 230)
MUTED = (200, 192, 175)

CHAPTER_CARD_SECONDS = 2.5
# A clip is a shot, not a segment of its own — 15 seconds of someone else's
# footage is a repost. The cap is on the DOWNLOAD, so a 2GB source file
# cannot take the box down on a render that runs monthly.
MAX_CLIP_BYTES = 120_000_000
MAX_PHOTO_BYTES = 25_000_000


def _scrim(base):
    """Darken top and bottom so type reads over any illustration."""
    img = base.convert("RGB")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(int(H * 0.22)):
        a = int(190 * (1 - i / (H * 0.22)))
        d.line([(0, i), (W, i)], fill=(0, 0, 0, a))
    for i in range(int(H * 0.34)):
        y = H - 1 - i
        a = int(215 * (1 - i / (H * 0.34)))
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_chapter_card(n, title, out_png):
    """A plain title card between chapters.

    The one piece of structure long-form needs and a reel does not: eight
    minutes without visible sections reads as one undifferentiated block, and a
    viewer who loses the thread has no landmark to recover at.
    """
    img = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(img)
    d.text((120, 110), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    d.text((120, H // 2 - 150), f"{n:02d}", font=_font(MONO_BOLD, 120), fill=ACCENT)
    f = _font(SERIF_BOLD, 88)
    y = H // 2 - 10
    for line in _wrap(d, title, f, W - 240)[:3]:
        d.text((120, y), line, font=f, fill=PAPER)
        y += 108
    d.line([(120, y + 40), (120 + 220, y + 40)], fill=ACCENT, width=7)
    img.save(out_png)
    return out_png


def _ground(out_png, variant=0):
    """A landscape inked field. The reel's render_house_ground is 1080x1920 and
    a transposed crop of it shows a third of a gradient built for a tall frame —
    the same mistake the illustration aspect ratio made. Small enough to draw
    here rather than parameterise a renderer the daily path depends on."""
    import random

    rng = random.Random(9173 + variant)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    top, mid, bot = (14, 12, 9), (34, 29, 21), (12, 10, 8)
    for y in range(H):
        t = y / H
        a, b = (top, mid) if t < 0.5 else (mid, bot)
        k = (t if t < 0.5 else t - 0.5) * 2
        d.line([(0, y), (W, y)],
               fill=tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    for _ in range(9000):
        x, y = rng.randrange(W), rng.randrange(H)
        v = rng.randint(-9, 9)
        px = img.getpixel((x, y))
        img.putpixel((x, y), tuple(max(0, min(255, c + v)) for c in px))
    img.save(out_png)
    return out_png


def draw_data_card(figure, out_png, chapter_label=""):
    """The number, as type, at the size it deserves.

    This is the frame the first sample did not have and needed most. A story
    whose whole argument is 2,732 against 780 cannot put those on screen as a
    symbolic illustration of a ledger — the viewer has to READ them, and a
    generated picture is forbidden from containing legible text for good
    reasons (BRAND.md) and is bad at it anyway.

    Drawn, not generated, so the number on screen is exactly the number the
    script declared and a reviewer approved.
    """
    img = Image.open(_ground(out_png.with_name(out_png.stem + "_bg.png"),
                             variant=1)).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((120, 96), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    if chapter_label:
        d.text((120, 148), chapter_label.upper()[:60],
               font=_font(MONO, 30), fill=MUTED)

    value = (figure.get("value") or "").strip()
    # Fit rather than assume: "2,732 crore" and "71%" want very different sizes,
    # and a fixed size either clips the long one or wastes the frame on the short.
    size = 220
    f = _font(SERIF_BOLD, size)
    while size > 90 and d.textlength(value, font=f) > W - 240:
        size -= 10
        f = _font(SERIF_BOLD, size)
    y = H // 2 - size // 2 - 40
    d.text((120, y), value, font=f, fill=PAPER)
    # A serif at 200pt has a deep descender; 1.15 put the label inside it.
    y += int(size * 1.34)
    d.line([(120, y), (300, y)], fill=ACCENT, width=6)
    y += 40

    label = (figure.get("label") or "").strip()
    if label:
        lf = _font(SERIF_BOLD, 54)
        for line in _wrap(d, label, lf, W - 240)[:2]:
            d.text((120, y), line, font=lf, fill=ACCENT)
            y += 66

    source = (figure.get("source") or "").strip()
    if source:
        # The source line is what separates a figure from a poster. Small, always
        # present, never the same colour as the number.
        d.text((120, H - 120), source.upper()[:90],
               font=_font(MONO, 28), fill=MUTED)
    img.save(out_png)
    return out_png


def draw_quote_frame(text, out_png, chapter_label="", attribution=""):
    """The sentence being spoken, as type. The default connective frame.

    Replaces the generated illustration as the thing that fills a shot with
    nothing else to show, because generated illustrations kept being worse than
    nothing. Measured on the first three samples, every time the same way:
    diffusion renders the generic NOUN and drops the distinguishing detail that
    made the shot worth taking.

      "a wide ledger, one column far taller than the other"  -> a blank book
      "a filing drawer, ONE folder left in it"               -> a full drawer
      "a large invoice stamped PAID IN FULL"                 -> a broken column

    The middle one is the argument for this frame. The close says the record is
    absent; the picture said the file was full. A frame that contradicts the
    narration is not decoration, it is a false statement in the most-watched
    part of the video.

    A line of narration cannot do that. It IS the narration, it is always
    legible, always relevant, and costs no model call. Anil, 2026-09-11: "there
    should be things valid on the screen, its a video at the end of the day."
    """
    img = Image.open(_ground(out_png.with_name(out_png.stem + "_bg.png"),
                             variant=1)).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((120, 96), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    if chapter_label:
        d.text((120, 148), chapter_label.upper()[:60],
               font=_font(MONO, 30), fill=MUTED)

    text = (text or "").strip()
    if not text:
        img.save(out_png)
        return out_png

    # Fit rather than truncate: a sentence cut mid-clause on screen while the
    # voice says the rest of it is the worst of both.
    size, lines = 84, []
    while size > 34:
        f = _font(SERIF_BOLD, size)
        lines = _wrap(d, text, f, W - 300)
        if len(lines) * int(size * 1.34) <= H - 460:
            break
        size -= 4
    f = _font(SERIF_BOLD, size)
    lead = int(size * 1.34)
    y = max(250, (H - len(lines) * lead) // 2 - 30)
    d.line([(120, y - 46), (300, y - 46)], fill=ACCENT, width=6)
    for line in lines:
        d.text((120, y), line, font=f, fill=PAPER)
        y += lead
    if attribution:
        d.text((120, H - 110), attribution.upper()[:100],
               font=_font(MONO, 28), fill=MUTED)
    img.save(out_png)
    return out_png


def draw_table_frame(table, out_png, chapter_label=""):
    """A short ranked list with one row lit up.

    The frame that answers "there should be things valid on the screen". A rank
    stated as a figure — "23rd of 26" — asks the viewer to take it on trust. The
    same claim as a list they can read down, with the row that matters in the
    accent colour, is checkable with their eyes while the narration is still
    talking. For a story whose whole argument is that a raw count and a rate
    rank the same state at opposite ends, this is the argument, not decoration.

    Rows are drawn as given. The renderer does not sort, compute or round: every
    number on screen is one the script declared and a reviewer approved at gate
    1, which is the same rule FIGURE lines follow and for the same reason.
    """
    img = Image.open(_ground(out_png.with_name(out_png.stem + "_bg.png"),
                             variant=0)).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((120, 96), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    if chapter_label:
        d.text((120, 148), chapter_label.upper()[:60],
               font=_font(MONO, 30), fill=MUTED)

    title = (table.get("title") or "").strip()
    y = 250
    if title:
        tf = _font(SERIF_BOLD, 60)
        for line in _wrap(d, title, tf, W - 240)[:2]:
            d.text((120, y), line, font=tf, fill=PAPER)
            y += 72
        y += 20

    rows = table.get("rows") or []
    # Fit the rows into what is left rather than assuming a count: five states
    # and twelve want different leading, and a fixed one either overflows the
    # frame or strands the list in its top third.
    avail = H - y - 150
    size = 52
    while size > 26 and len(rows) * int(size * 1.55) > avail:
        size -= 2
    lead = int(size * 1.55)
    rf, rfb = _font(MONO, size), _font(MONO_BOLD, size)

    for row in rows:
        if row.get("elision"):
            # Say the list is cut rather than implying it is whole.
            d.text((140, y + lead // 4), "·  ·  ·", font=_font(MONO, size),
                   fill=(90, 80, 62))
            y += lead
            continue
        if row.get("highlight"):
            d.rectangle([108, y - 8, W - 120, y + size + 10], fill=(48, 40, 26))
            d.rectangle([108, y - 8, 116, y + size + 10], fill=ACCENT)
            d.text((140, y), row["text"][:60], font=rfb, fill=ACCENT)
        else:
            d.text((140, y), row["text"][:60], font=rf, fill=PAPER)
        y += lead

    source = (table.get("source") or "").strip()
    if source:
        d.text((120, H - 110), source.upper()[:100],
               font=_font(MONO, 26), fill=MUTED)
    img.save(out_png)
    return out_png


def draw_record_frame(page_png, caption, out_png, chapter_label="", quote=""):
    """The actual page of the actual document, with the line that matters beside it.

    Not an illustration OF a record — the record. evidence_shot.py renders it
    from the PDF we fetched; this only places it.

    Two columns, because one does not work. A full A4 page letterboxed into 16:9
    is a narrow strip of unreadable grey with dead space either side, and it
    tells the viewer nothing about WHICH of the forty lines on it is the point.
    So the page sits on the right at the largest size the frame allows, and the
    left carries the sentence the narration is saying — lifted verbatim from
    that page, never paraphrased. The layout is the argument: here is the claim,
    and here, beside it, is the document it came off.

    Never cropped to fill. A document page cropped to fit a frame is a document
    page with its top or bottom cut off, and which part got cut is exactly the
    question a sceptical viewer is asking.
    """
    img = Image.open(_ground(out_png.with_name(out_png.stem + "_bg.png"),
                             variant=2)).convert("RGB")
    d = ImageDraw.Draw(img)

    page = Image.open(page_png).convert("RGB")
    col_w, top, bottom = 620, 170, 90
    scale = min(col_w / page.width, (H - top - bottom) / page.height)
    page = page.resize((max(1, int(page.width * scale)),
                        max(1, int(page.height * scale))))
    px = W - 120 - page.width
    py = top + ((H - top - bottom) - page.height) // 2
    d.rectangle([px - 5, py - 5, px + page.width + 4, py + page.height + 4],
                fill=(120, 100, 66))
    img.paste(page, (px, py))

    d.text((120, 96), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    if chapter_label:
        d.text((120, 148), chapter_label.upper()[:60],
               font=_font(MONO, 30), fill=MUTED)

    text_w = px - 240
    y = 320
    if quote:
        # Quotation marks, because this is the document's wording and not ours.
        qf, size = None, 58
        while size > 30:
            qf = _font(SERIF_BOLD, size)
            lines = _wrap(d, f"\u201c{quote}\u201d", qf, text_w)
            if len(lines) * int(size * 1.30) <= H - 520:
                break
            size -= 4
        for line in lines:
            d.text((120, y), line, font=qf, fill=PAPER)
            y += int(size * 1.30)
        y += 24
        d.line([(120, y), (260, y)], fill=ACCENT, width=5)
        y += 36

    if caption:
        cf = _font(MONO, 26)
        for line in _wrap(d, caption, cf, text_w)[:4]:
            d.text((120, y), line, font=cf, fill=MUTED)
            y += 36
    img.save(out_png)
    return out_png


def draw_story_frame(image_path, caption, out_png, chapter_label="", credit=""):
    """One illustrated frame with the spoken line beneath it."""
    base = Image.open(image_path).convert("RGB")
    # cover-fit into landscape without distorting the illustration
    bw, bh = base.size
    scale = max(W / bw, H / bh)
    base = base.resize((int(bw * scale), int(bh * scale)))
    left, top = (base.width - W) // 2, (base.height - H) // 2
    base = base.crop((left, top, left + W, top + H))

    img = _scrim(base)
    d = ImageDraw.Draw(img)
    d.text((120, 96), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    if chapter_label:
        d.text((120, 148), chapter_label.upper()[:60],
               font=_font(MONO, 30), fill=MUTED)

    if caption:
        f = _font(SERIF_BOLD, 62)
        lines = _wrap(d, caption, f, W - 240)[:3]
        y = H - 150 - len(lines) * 78
        for line in lines:
            d.text((120, y), line, font=f, fill=PAPER)
            y += 78
    if credit:
        # A licence condition, not a nicety — it is the reason we may show the
        # picture at all. Held for the whole shot, small, always present.
        #
        # Its own scrim band: a real photograph is often bright where a
        # generated illustration is not, and the first one tested had the
        # masthead and the credit washing out against a daylit street.
        band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        bd.rectangle([0, 0, W, 210], fill=(0, 0, 0, 140))
        bd.rectangle([0, H - 120, W, H], fill=(0, 0, 0, 165))
        img = Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")
        d = ImageDraw.Draw(img)
        d.text((120, 96), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
        if chapter_label:
            d.text((120, 148), chapter_label.upper()[:60],
                   font=_font(MONO, 30), fill=MUTED)
        cf = _font(MONO, 26)
        lines = _wrap(d, credit, cf, W - 240)[:2]
        y = H - 40 - len(lines) * 34
        for line in lines:
            d.text((120, y), line, font=cf, fill=MUTED)
            y += 34
    img.save(out_png)
    return out_png


def _ffmpeg(args, what):
    r = subprocess.run(["ffmpeg", "-y", "-nostdin", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{what} failed: {r.stderr[-400:]}")


# Motion. Anil, 2026-09-11, after watching the second sample: "the video should
# also be moving or show meaningful things to hook the viewer. We can[\'t] keep
# static images like in the reels and expect users to watch it for 10 minutes."
#
# That overrides the original call, and correctly. A reel's stillness works
# because the whole thing is over in ninety seconds; ten minutes of held stills
# is a slideshow with a voice-over, however good the stills are.
#
# A slow push or pull, inside each shot. Deliberately not cross-dissolves
# between shots: xfade would mean re-encoding the entire timeline in one
# filter_complex instead of concat-copying eleven independent segments, which
# turns a resumable render into an all-or-nothing one. Motion within a shot buys
# most of the life for none of that.
#
# The upscale before zoompan is not optional. zoompan samples the SOURCE frame,
# so zooming a 1920-wide image steps whole pixels at a time and the result
# visibly judders; feeding it 2x and letting it scale down makes the steps
# sub-pixel. This is the single most common way this filter is got wrong.
ZOOM_MAX = 1.12          # 12% over the shot. More reads as a Ken Burns parody.
ZOOM_SUPERSAMPLE = 2


def _motion_filter(kind, duration):
    """The -vf chain for one shot. `kind` is 'in', 'out' or 'none'."""
    frames = max(1, int(round(duration * FPS)))
    if kind == "none" or frames < FPS:
        # Under a second there is no room for a move; a jump is worse than a hold.
        return f"scale={W}:{H}"
    big_w, big_h = W * ZOOM_SUPERSAMPLE, H * ZOOM_SUPERSAMPLE
    step = (ZOOM_MAX - 1.0) / frames
    if kind == "out":
        z = f"if(eq(on,0),{ZOOM_MAX},max(zoom-{step:.8f},1.0))"
    else:
        z = f"min(zoom+{step:.8f},{ZOOM_MAX})"
    return (f"scale={big_w}:{big_h},"
            f"zoompan=z='{z}':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={W}x{H}:fps={FPS},"
            f"setsar=1")


def _clip_segment(clip_path, wav, out_mp4, duration, audio_start=0.0,
                  caption="", chapter_label=""):
    """A real piece of footage, letterboxed onto the house ground, over narration.

    The clip's OWN audio is dropped and the narration continues over it. That is
    not a shortcut — an eight-second burst of someone else's ambient sound in the
    middle of a read is jarring, and more importantly the licence we hold is
    usually for the pictures.

    Letterboxed, never cropped to fill: a 4:3 phone clip cropped to 16:9 loses
    the top and bottom of the thing it was shown to prove. `force_original_aspect_ratio`
    plus `pad` keeps it whole on the ink ground.

    The caption is burned in for the whole clip because attribution that appears
    for two seconds is attribution nobody read. It carries what the footage shows
    and under what licence — see BRAND.md.
    """
    ink = f"{INK[0]:02x}{INK[1]:02x}{INK[2]:02x}"
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{ink},"
          f"setsar=1,fps={FPS}")
    args = ["-stream_loop", "-1", "-i", str(clip_path)]
    if wav:
        args += ["-ss", f"{audio_start:.3f}", "-i", str(wav)]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    args += ["-map", "0:v:0", "-map", "1:a:0",
             "-t", f"{duration:.3f}", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-vf", vf,
             "-af", "apad", "-ar", "44100", "-ac", "2",
             "-c:a", "aac", "-b:a", "160k",
             str(out_mp4)]
    _ffmpeg(args, f"clip {Path(clip_path).name}")


def _overlay_caption(clip_mp4, out_mp4, caption, chapter_label=""):
    """Burn the masthead and the attribution onto an encoded clip.

    Drawn as a PNG and overlaid rather than with drawtext: drawtext needs the
    font path escaped through two layers of shell and filter quoting, and gets
    the ₹ glyph wrong. Compositing a transparent PNG uses the same PIL text
    path every other frame in this file uses, so the type matches exactly.
    """
    strip = Path(out_mp4).with_suffix(".strip.png")
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 200], fill=(0, 0, 0, 150))
    d.rectangle([0, H - 150, W, H], fill=(0, 0, 0, 175))
    d.text((120, 70), "THELIVU", font=_font(MONO_BOLD, 38), fill=ACCENT)
    if chapter_label:
        d.text((120, 122), chapter_label.upper()[:60],
               font=_font(MONO, 30), fill=MUTED)
    if caption:
        cf = _font(MONO, 28)
        lines = _wrap(d, caption, cf, W - 240)[:2]
        y = H - 40 - len(lines) * 38
        for line in lines:
            d.text((120, y), line, font=cf, fill=PAPER)
            y += 38
    img.save(strip)
    _ffmpeg(["-i", str(clip_mp4), "-i", str(strip),
             "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
             "-map", "[v]", "-map", "0:a:0",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "copy", str(out_mp4)],
            f"caption {Path(clip_mp4).name}")


def _segment(png, wav, out_mp4, duration, audio_start=0.0, motion="in"):
    """One frame, moving slowly, over a slice of narration.

    `audio_start` exists because a chapter is voiced in ONE call — splitting the
    text would give each part its own prosody contour — and then cut into
    several shots against that single continuous take. Each shot seeks into the
    same wav rather than owning its own.

    `apad` rather than `-shortest`: the planned duration includes reel.GAP_SECS
    of breathing room that the wav itself does not contain, so `-shortest` would
    quietly trim every segment back to its audio and delete the gap. Padding
    with silence keeps the video timeline and the parts-sum exact.
    """
    args = ["-loop", "1", "-i", str(png)]
    if wav:
        args += ["-ss", f"{audio_start:.3f}", "-i", str(wav)]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    args += ["-t", f"{duration:.3f}", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-vf", _motion_filter(motion, duration),
             "-af", "apad", "-ar", "44100", "-ac", "2",
             "-c:a", "aac", "-b:a", "160k",
             str(out_mp4)]
    _ffmpeg(args, f"segment {Path(png).name}")


# How often the picture should change. Anil, 2026-09-11: "it shouldnt end up
# like an audio book" — which is what a long chapter on one frame is, however
# good the frame. A flat cap got this wrong in the other direction: five shots
# over a 110-second chapter is 22 seconds a frame, no better than three over 66.
# So the cut rate follows the narration, and the cap is only a safety rail.
TARGET_SHOT_SECONDS = 13.0
MAX_IMAGES_PER_UNIT = 1
# A unit shorter than this has no slot to spare on atmosphere.
MIN_SHOTS_FOR_IMAGE = 4
MAX_SHOTS_PER_UNIT = 8
# Below this a shot is a flicker. Lower than the illustration-only 12s, because a
# number or a quoted line is READ — four or five seconds is enough for a figure
# where a scene needs dwelling on.
MIN_SHOT_SECONDS = 8.0


def _shot_count(duration, available):
    """How many cuts a unit of `duration` seconds earns, given `available`
    assets.

    Three things bound it and all three matter: what the writer supplied, how
    fast a viewer can absorb a change (the floor), and how long anyone will look
    at one picture (the target). A chapter with two assets gets two shots however
    long it runs — the fix for that is a TABLE or a FIGURE line, not a longer
    hold, and the gate-1 blockers say so.
    """
    if available <= 1:
        return 1
    wanted = max(1, round(duration / TARGET_SHOT_SECONDS))
    k = min(available, MAX_SHOTS_PER_UNIT, wanted, int(duration // MIN_SHOT_SECONDS))
    return max(1, k)


def _sentences(text):
    """Narration split into sentences, long ones only. Short connectives ("That
    figure is real.") are true but make a weak frame."""
    import re as _re
    parts = [p.strip() for p in _re.split(r"(?<=[.?!])\s+", (text or "").strip())]
    return [p for p in parts if len(p.split()) >= 6]


def quote_fill(text, have, want):
    """Quote frames to fill the shots a unit earned but did not declare assets for.

    Position-matched, not arbitrary: shots run sequentially over one continuous
    narration take, so the frame occupying slot j of k shows a sentence from
    about j/k of the way through the text. The line on screen therefore tracks
    what is being said without any word-level timing — the same approximation
    plan_cuts makes about pauses, and good enough for the same reason.
    """
    need = max(0, want - have)
    sents = _sentences(text)
    if not need or not sents:
        return []
    out, used = [], set()
    for i in range(need):
        frac = (have + i + 0.5) / max(1, want)
        idx = min(len(sents) - 1, int(frac * len(sents)))
        # Never show the same sentence twice in one unit.
        while idx in used and idx + 1 < len(sents):
            idx += 1
        while idx in used and idx > 0:
            idx -= 1
        if idx in used:
            break
        used.add(idx)
        out.append({"kind": "quote", "text": sents[idx]})
    return out


def plan_assets(chapter, fallback_image=None):
    """What this unit puts on screen, hardest evidence first.

    Anil, 2026-09-11, after watching the first sample: *"this only has generated
    images, which are not great... we need to print out numbers, facts,
    screenshots, evidences. generated images like these won't work."*

    So the order is a policy, not an accident. When a chapter declares more
    assets than its narration has room for, the ones that get dropped are the
    illustrations — a symbolic picture of a ledger is the most expendable thing
    on the list, and the figure and the document page are the reason anyone is
    still watching at minute six.

    Within a kind, declaration order is kept, so a writer who lists the figures
    in the order the narration says them gets them in that order. That is the
    only alignment available without word-level timing, and it is worth saying
    in the skill rather than pretending the renderer can infer it.
    """
    figures = [{"kind": "figure", "figure": f} for f in (chapter.get("figures") or [])]
    tables = [{"kind": "table", "table": t} for t in (chapter.get("tables") or [])]
    records = [{"kind": "record", "record": r} for r in (chapter.get("records") or [])]
    # Footage ranks with the records: it is the thing itself, not a picture of
    # the idea of it. A clip with no licence is dropped here rather than
    # rendered — see _prepare_clip and BRAND.md.
    clips = [{"kind": "clip", "clip": c} for c in (chapter.get("clips") or [])
             if media_licence_status(c)[0]]
    photos = [{"kind": "photo", "photo": ph} for ph in (chapter.get("photos") or [])
              if media_licence_status(ph)[0]]
    images = [{"kind": "image", "prompt": p} for p in (chapter.get("images") or [])]
    if not images and fallback_image:
        images = [{"kind": "image", "prompt": fallback_image}]
    # Generated illustrations are NOT returned here. They rank below quote
    # frames and are added last, by `with_filler`, and only in a unit long
    # enough to spare a slot.
    #
    # Ranking them with the evidence was wrong in a way the fourth sample made
    # obvious: the close declares a CLOSE_IMAGE and earns exactly one shot, so
    # the picture beat the words on the single most important frame in the
    # video. The line being spoken was "that part has not been published" and
    # the screen showed a filing cabinet.
    return figures + tables + photos + clips + records


def with_filler(assets, text, want, images=()):
    """Fill a unit's shot budget: evidence, then narration, then at most one
    picture — and the picture only if the unit can spare a slot.

    `MIN_SHOTS_FOR_IMAGE` is the whole policy. A generated scene is atmosphere,
    and atmosphere is what you add once the argument is already on screen; in a
    unit with two or three shots there is nothing to spare, and a quote frame
    beats a picture of the idea of a quote every time.
    """
    out = list(assets[:want])
    room = want - len(out)
    if room <= 0:
        return out[:want]
    picture = (list(images)[:MAX_IMAGES_PER_UNIT]
               if want >= MIN_SHOTS_FOR_IMAGE else [])
    quotes = quote_fill(text, len(out), want - len(picture))
    out += quotes
    out += [{"kind": "image", "prompt": p} for p in picture]
    # A unit with nothing to say and nothing declared still needs one frame.
    if not out:
        out = [{"kind": "image", "prompt": (list(images) or [None])[0]}]
    return out[:want]


# What makes a clip usable, and which of those needs a human to say yes.
#
# Anil: "if we give appropriate credits, cant we use them?" The honest answer is
# in two halves, and conflating them is how a channel gets a strike:
#
#   Credit IS the licence condition   GODL-India, CC-BY, CC-BY-SA, a commercial
#                                     licence, our own footage. Attribute as the
#                                     licence requires and it is settled.
#
#   Credit is NOT permission          Ordinary copyrighted news or social footage.
#                                     Crediting the owner does not create a right
#                                     to use it, and YouTube's Content ID does not
#                                     read credits — it matches audio and video
#                                     fingerprints and files a claim automatically.
#
# Between them sits **fair dealing** (India, s.52(1)(a)(ii) Copyright Act 1957 —
# reporting current events) and fair use in the US, which is the law YouTube's
# dispute process actually runs on. A short excerpt of newsworthy footage, used
# with commentary that transforms it, credited, is a recognised journalistic
# practice. It is a DEFENCE, assessed case by case, not a permission — and
# Content ID will claim it first and ask later.
#
# So this is not a binary. A clip declares its basis; the settled ones render
# without comment, and a fair-dealing claim renders but is surfaced at gate 1 so
# the person carrying the risk decides knowingly. None of this is legal advice.
SETTLED_LICENCES = ("godl", "cc-by", "cc0", "public domain", "licensed", "own",
                    "pib", "gov")
FAIR_DEALING_PREFIX = "fair-dealing"


def media_licence_status(item):
    """(ok, needs_human_call, why) for a CLIP or a PHOTO.

    Photographs go through publishing/photos.usable() as well, because the
    Commons licences have teeth the clip list does not cover: NonCommercial and
    NoDerivatives both bite here — the channel carries ads, and every frame is
    cropped and composited onto the house ground.
    """
    lic = (item.get("licence") or "").strip()
    if lic and not lic.lower().startswith(FAIR_DEALING_PREFIX):
        try:
            from publishing.photos import usable
            ok, why = usable(lic)
            if ok:
                return True, False, ""
            # Fall through: the clip list recognises bases photos.py does not
            # (a commercial licence from an outlet, our own footage).
            if "NonCommercial" in why or "NoDerivatives" in why:
                return False, False, why
        except Exception:
            pass
    return clip_licence_status(item)


def clip_licence_status(clip):
    """(ok_to_render, needs_human_call, why)."""
    lic = (clip.get("licence") or "").strip().lower()
    if not lic:
        return False, False, "no licence recorded"
    if lic.startswith(FAIR_DEALING_PREFIX):
        return True, True, "relies on fair dealing — a defence, not a permission"
    if any(tok in lic for tok in SETTLED_LICENCES):
        return True, False, ""
    return False, False, (f"licence {clip.get('licence')!r} is not a recognised "
                          f"basis; use a settled licence or declare "
                          f"'{FAIR_DEALING_PREFIX}: <why>'")


def _clip_caption(clip):
    """What the footage shows, where it came from, and under what licence.

    All three, always. Attribution is a licence condition for most of what we
    can legally use, and provenance is what stops a correctly licensed clip of
    the wrong flyover becoming a false claim.
    """
    bits = [(clip.get("shows") or "").strip()]
    if clip.get("provenance"):
        bits.append(clip["provenance"].strip())
    if clip.get("licence"):
        bits.append(clip["licence"].strip())
    return " · ".join(b for b in bits if b)


def _prepare_photo(photo, out_dir, stem):
    """Download a licensed photograph. Same licence gate as a clip."""
    ok, _needs_call, why = media_licence_status(photo)
    if not ok:
        log.warning("photo %r not usable: %s", photo.get("shows"), why)
        return None
    src = (photo.get("src") or "").strip()
    if not src:
        return None
    try:
        if not src.lower().startswith(("http://", "https://")):
            local = Path(src).expanduser()
            return local if local.exists() else None
        from engine.digger import fetch as digfetch
        suffix = Path(urlparse(src).path).suffix or ".jpg"
        return digfetch.fetch_file(src, Path(out_dir) / f"{stem}{suffix}",
                                   max_bytes=MAX_PHOTO_BYTES)
    except Exception as e:
        log.warning("photo %s unusable (%s: %s)", src, type(e).__name__, e)
        return None


def _prepare_clip(clip, out_dir, stem):
    """Get a usable local video file for a CLIP, or None.

    Refuses, loudly, anything with no licence recorded. That check also lives in
    plan_assets so an unlicensed clip never reaches a shot slot at all; it is
    repeated here because this is the function that would otherwise download it,
    and a rule that matters is worth enforcing at the point of the act as well
    as the point of the plan.
    """
    ok, needs_call, why = clip_licence_status(clip)
    if not ok:
        log.warning("clip %r not usable: %s", clip.get("shows"), why)
        return None
    if needs_call:
        log.info("clip %r %s — flagged for review", clip.get("shows"), why)
    src = (clip.get("src") or "").strip()
    if not src:
        return None
    out_dir = Path(out_dir)
    try:
        if not src.lower().startswith(("http://", "https://")):
            local = Path(src).expanduser()
            return local if local.exists() else None
        from engine.digger import fetch as digfetch
        return digfetch.fetch_file(src, out_dir / f"{stem}{Path(src).suffix or '.mp4'}",
                                   max_bytes=MAX_CLIP_BYTES)
    except Exception as e:
        log.warning("clip %s unusable (%s: %s)", src, type(e).__name__, e)
        return None


def _render_record(record, out_dir, stem):
    """Fetch a RECORD's document and render the page that carries its quote.

    Returns {path, caption} or None. Never raises: a source that is down, a URL
    that moved, a PDF with no text layer — none of those are worth failing a
    render that has already spent an hour of the voice server. The shot is
    demoted to an illustration and the video is one frame weaker, which is a
    thing a reviewer can see at gate 2.
    """
    url = (record.get("url") or "").strip()
    if not url:
        return None
    try:
        from engine.digger import fetch as digfetch
        from publishing import evidence_shot

        out_dir = Path(out_dir)
        pdf = digfetch.fetch_file(url, out_dir / f"{stem}.pdf")
        pages = _page_texts(pdf)
        shots = evidence_shot.from_source(
            pdf, out_dir, url, record.get("description") or "",
            quote=record.get("quote") or "", pdf_text_by_page=pages, stem=stem)
        return shots[0] if shots else None
    except Exception as e:
        log.warning("record %s could not be shown (%s: %s)", url, type(e).__name__, e)
        return None


def _page_texts(pdf_path):
    """Per-page text, so find_pages() can put the RIGHT page on screen.

    The digger's pdf_to_text returns one blob, which makes every quote land on
    page 1 — evidence_shot says so out loud rather than showing the wrong page
    silently, but "page 1 of a five-page answer while the narration quotes the
    annexure" is a prop, not evidence. Returns [] when per-page text is not
    available, which is the same honest fallback.
    """
    try:
        import liteparse
        lp = liteparse.LiteParse(ocr_enabled=False, num_workers=1, pool_size=1,
                                 quiet=True, parse_timeout=90)
        try:
            result = lp.parse(str(pdf_path))
            pages = getattr(result, "pages", None) or []
            return [(getattr(pg, "text", "") or "") for pg in pages]
        finally:
            try:
                lp.close()
            except Exception:
                pass
    except Exception as e:
        log.info("no per-page text for %s (%s) — quotes will fall back to page 1",
                 pdf_path, type(e).__name__)
        return []


def render(parsed, out_mp4, work_dir=None, voice=None, illustrate=True,
           progress=None):
    """Render a parsed long-form script to `out_mp4`.

    Returns {ok, path, seconds, chapters:[(start_seconds, title)]}. The chapter
    marks come back measured from the REAL audio, not estimated — a mark that
    lands mid-sentence is worse than no mark, and the estimate is only good
    enough to plan with.
    """
    from publishing.reel import plan_cuts, synth_beats

    def _p(frac, msg):
        if progress:
            try:
                progress(frac, msg)
            except Exception:
                pass
        log.info("%s", msg)

    tmp = Path(work_dir or tempfile.mkdtemp(prefix="longform_"))
    tmp.mkdir(parents=True, exist_ok=True)
    chapters = parsed.get("chapters", [])
    if not chapters:
        return {"ok": False, "error": "script has no chapters"}

    # 1. Narration first, for the same reason the reel path does it first: the
    #    voice is the only thing that knows real durations, and everything
    #    downstream — shot counts, cut points, chapter marks — is planned from
    #    them. A whole unit is voiced in one call; cuts come later.
    units = [("cold_open", None, parsed.get("cold_open", ""))]
    for c in chapters:
        units.append((f"ch{c['n']}", c, c["text"]))
    units.append(("close", None, parsed.get("close", "")))
    units = [u for u in units if (u[2] or "").strip()]

    _p(0.05, f"Voicing {len(units)} sections…")
    voiced = synth_beats([(text, "") for _k, _c, text in units],
                         "chatterbox", tmp / "vo", voice=voice)

    # 2. Plan what each unit puts on screen, against those real durations.
    #    Figures and records first, illustrations last — see plan_assets.
    plans = []          # per unit: [(asset, seconds)]
    for (key, chap, text), (_wav, dur, pauses) in zip(units, voiced):
        if chap:
            unit, fallback = chap, None
        else:  # noqa: E701
            # The bookends carry the same vocabulary as a chapter — see
            # parse_script. A 46-second close on one frame is the audio-book
            # failure on the unit a viewer judges the video by.
            unit = {"figures": parsed.get(f"{key}_figures") or [],
                    "images": parsed.get(f"{key}_images") or []}
            fallback = parsed.get(f"{key}_image")
        assets = plan_assets(unit, fallback_image=fallback)
        if not assets:
            assets = [{"kind": "image", "prompt": None}]
        # Quote frames fill whatever the writer did not declare, and a picture
        # gets the last slot only in a unit long enough to spare one. Before
        # 2026-09-11 the filler was a generated illustration and they kept being
        # worse than nothing — see draw_quote_frame. A shot budget is now always
        # fillable, so a unit never holds one frame for a minute either.
        want = _shot_count(dur, max(len(assets) + 1, _shot_count(dur, 99)))
        declared_images = ((chap or {}).get("images")
                           or ([fallback] if fallback else []))
        assets = with_filler(assets, text, want, images=declared_images)
        k = min(want, len(assets)) or 1
        plans.append(list(zip(assets[:k], plan_cuts(dur, k, pauses))))

    # 3. Fetch and render the documents. Before illustration, because a record
    #    that fails to fetch demotes its shot to an illustration and that has to
    #    be known before the batch is sent — one batched FLUX call is the whole
    #    reason illustration is cheap.
    n_ev = sum(1 for pl in plans for a, _ in pl if a["kind"] in ("record", "clip"))
    if n_ev:
        _p(0.20, f"Fetching {n_ev} record(s) and clip(s)…")
    for i, pl in enumerate(plans):
        for j, (asset, _secs) in enumerate(pl):
            got = None
            if asset["kind"] == "record":
                got = _render_record(asset["record"], tmp / "records", f"u{i}_{j}")
                if got:
                    asset["shot"] = got
            elif asset["kind"] == "clip":
                got = _prepare_clip(asset["clip"], tmp / "clips", f"u{i}_{j}")
                if got:
                    asset["file"] = got
            elif asset["kind"] == "photo":
                got = _prepare_photo(asset["photo"], tmp / "photos", f"u{i}_{j}")
                if got:
                    asset["file"] = got
            else:
                continue
            if not got:
                # Demote rather than fail. A missing document or an unusable
                # clip costs the frame its evidence, not the video its render.
                asset["kind"] = "image"
                asset["prompt"] = None

    # 4. Illustrate every remaining image shot in ONE batched call —
    #    generate_beat_images() warms up once and walks illustrate.prompt_ladder
    #    per scene, so a scene FLUX refuses costs a few rungs and comes back
    #    None rather than failing the render.
    img_slots = [(i, j) for i, pl in enumerate(plans)
                 for j, (a, _s) in enumerate(pl) if a["kind"] == "image"]
    _p(0.35, f"Illustrating {len(img_slots)} of "
             f"{sum(len(pl) for pl in plans)} shots…")
    from publishing.illustrate import (LANDSCAPE, STYLE, generate_beat_images,
                                       scene_from_beat)
    scenes = [plans[i][j][0].get("prompt") or scene_from_beat("", units[i][2][:120])
              for i, j in img_slots]
    arts = [None] * len(scenes)
    if illustrate and scenes:
        try:
            # LANDSCAPE, not the reel default. A portrait illustration
            # cover-cropped into 1920x1080 shows only the middle third of a
            # composition the model built for a tall frame — on the first real
            # render that put the cold open's subject below the crop and left
            # 90% of the frame empty. Ask for the aspect ratio you are going to
            # show; do not crop your way to it.
            arts = generate_beat_images(scenes, tmp / "art",
                                        place=parsed.get("place"),
                                        ground=STYLE, size=LANDSCAPE) or arts
        except Exception as e:
            log.warning("illustration batch failed (%s) — falling back to grounds", e)
            arts = [None] * len(scenes)
    for (i, j), art in zip(img_slots, arts):
        plans[i][j][0]["art"] = art

    # 5. Compose frames and assemble: chapter card, then the chapter's shots.
    _p(0.6, "Assembling…")

    segs, marks, clock = [], [], 0.0
    for i, ((key, chap, _t), (wav, _dur, _pauses)) in enumerate(zip(units, voiced)):
        label = (chap or {}).get("title", "")
        if chap:
            card = draw_chapter_card(chap["n"], chap["title"],
                                     tmp / f"card_{i:03d}.png")
            seg = tmp / f"seg_card_{i:03d}.mp4"
            _segment(card, None, seg, CHAPTER_CARD_SECONDS)
            segs.append(seg)
            # The mark points at the CARD, not at the first spoken word: a
            # viewer who jumps to a chapter should land on its title.
            marks.append((int(clock), chap["title"]))
            clock += CHAPTER_CARD_SECONDS
        elif key == "cold_open":
            marks.append((0, "Introduction"))

        offset = 0.0
        for j, (asset, secs) in enumerate(plans[i]):
            png = tmp / f"frame_{i:03d}_{j}.png"
            if asset["kind"] == "figure":
                draw_data_card(asset["figure"], png, chapter_label=label)
            elif asset["kind"] == "photo":
                draw_story_frame(asset["file"], "", png, chapter_label=label,
                                 credit=_clip_caption(asset["photo"]))
            elif asset["kind"] == "quote":
                draw_quote_frame(asset["text"], png, chapter_label=label)
            elif asset["kind"] == "table":
                draw_table_frame(asset["table"], png, chapter_label=label)
            elif asset["kind"] == "clip":
                clip = asset["clip"]
                raw = tmp / f"clipseg_{i:03d}_{j}.mp4"
                _clip_segment(asset["file"], wav, raw, secs, audio_start=offset)
                seg = tmp / f"seg_{i:03d}_{j}.mp4"
                _overlay_caption(raw, seg, _clip_caption(clip), chapter_label=label)
                segs.append(seg)
                offset += secs
                clock += secs
                continue
            elif asset["kind"] == "record":
                shot = asset["shot"]
                draw_record_frame(shot["path"], shot["caption"], png,
                                  chapter_label=label,
                                  quote=asset["record"].get("quote", ""))
            else:
                art = asset.get("art") or _ground(
                    tmp / f"ground_{i:03d}_{j}.png", variant=(i + j) % 3)
                draw_story_frame(art, "", png, chapter_label=label)
            seg = tmp / f"seg_{i:03d}_{j}.mp4"
            _segment(png, wav, seg, secs, audio_start=offset)
            segs.append(seg)
            offset += secs
            clock += secs

    listfile = tmp / "concat.txt"
    listfile.write_text("".join(f"file '{s}'\n" for s in segs))
    _p(0.85, "Muxing…")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listfile),
             "-c", "copy", str(out_mp4)], "concat")

    _p(1.0, f"Rendered {clock/60:.1f} min in {len(segs)} shots")
    return {"ok": True, "path": str(out_mp4), "seconds": clock,
            "chapters": marks, "shots": len(segs)}
