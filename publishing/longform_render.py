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

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import wave
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


def fit_block(d, text, box_w, box_h, font_name, max_size=170, min_size=30,
              leading=1.34):
    """Largest size at which `text` wraps into box_w x box_h. (size, lines).

    GROWS as well as shrinks, which is the whole point. Every frame here used to
    start at a fixed size and only ever step DOWN until the text fit — so a long
    sentence was handled correctly and a short one kept the starting size and
    left the rest of the frame empty.

    Measured against ColdFusion on 2026-09-14, sampling vertical content
    coverage: theirs 94%, ours 74%. Our quote and table frames put everything in
    the top half and left the bottom 40% dark. Anil, watching the cut: "there is
    a huge gap where nothing is shown... lots of blank part, just audio." A
    frame with text on it can still read as empty, and ours did.
    """
    best = (min_size, _wrap(d, text, _font(font_name, min_size), box_w))
    lo, hi = min_size, max_size
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _font(font_name, mid)
        lines = _wrap(d, text, f, box_w)
        if len(lines) * int(mid * leading) <= box_h:
            best = (mid, lines)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def stamp_source(d, source, extra=""):
    """The source, bottom-left, on every evidence frame. Always.

    ColdFusion burns the provenance into the corner of every archival shot —
    `cnet`, `CBS News Archives`, `CNN Business` — rather than leaving it to the
    description. On an accountability channel that matters more, not less: the
    claim and the thing it rests on should be legible in the same frame, so a
    viewer who screenshots one number still has where it came from.
    """
    if not source:
        return
    line = source.upper()[:96]
    d.text((120, H - 118), line, font=_font(MONO, 28), fill=MUTED)
    if extra:
        d.text((120, H - 78), extra.upper()[:96], font=_font(MONO, 24),
               fill=(96, 86, 68))


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
    # Fit to the frame in BOTH directions, growing as well as shrinking. A fixed
    # 220pt ceiling meant the long values were already at the width limit and
    # looked right, while a short one like "38.86%" used 756px of 1680 and left
    # the card at ~78% coverage. The number is the hero of this frame; it should
    # be as large as the frame allows.
    label_room = 230 if (figure.get("label") or "").strip() else 40
    max_value_h = H - 250 - 190 - label_room
    size = 110
    while size < 400:
        nxt = size + 10
        nf = _font(SERIF_BOLD, nxt)
        if d.textlength(value, font=nf) > W - 240:
            break
        if int(nxt * 1.34) > max_value_h:
            break
        size = nxt
    f = _font(SERIF_BOLD, size)

    # CENTRE THE WHOLE BLOCK, not just the number. Centring the value on H//2
    # and hanging the label below it put the optical centre of the card too low
    # and left a band of nothing between the label and the source line — this
    # card sat at ~80% coverage while the quote frame reached 100%. Measure what
    # is actually drawn, then place all of it.
    label = (figure.get("label") or "").strip()
    lsize, llines = (0, [])
    if label:
        lsize, llines = fit_block(d, label, W - 240, 190, SERIF_BOLD,
                                  max_size=72, min_size=44, leading=1.22)
        llines = llines[:2]

    TOP, BOTTOM = 250, 190
    avail = H - TOP - BOTTOM
    value_h = int(size * 1.34)
    label_h = len(llines) * int(lsize * 1.22)
    block = value_h + 80 + label_h

    # A long value is capped by WIDTH and cannot grow to fill the card. The first
    # attempt SPREAD the block — value at the top, label pushed down to sit above
    # the source — which raised measured coverage from 78% to 89% and looked
    # worse: the label was marooned from the number it describes, with a void
    # and a stray rule between them. Coverage is a proxy for "the frame is
    # doing something", not for "the frame is good", and optimising it directly
    # broke the thing it was standing in for.
    #
    # The label belongs under its number. So the slack goes INTO the label
    # instead — it is re-fitted against whatever room the value left.
    if llines and block < avail * 0.82:
        room = avail - value_h - 80
        lsize, llines = fit_block(d, label, W - 240, room, SERIF_BOLD,
                                  max_size=96, min_size=lsize, leading=1.22)
        llines = llines[:3]
        label_h = len(llines) * int(lsize * 1.22)
        block = value_h + 80 + label_h
    y = TOP + max(0, (avail - block) // 2)
    label_y = None

    d.text((120, y), value, font=f, fill=PAPER)
    # A serif at 200pt has a deep descender; 1.15 put the label inside it.
    y += value_h
    d.line([(120, y), (300, y)], fill=ACCENT, width=6)
    y += 40

    if llines:
        lf = _font(SERIF_BOLD, lsize)
        y = label_y if label_y is not None else y
        for line in llines:
            d.text((120, y), line, font=lf, fill=ACCENT)
            y += int(lsize * 1.22)

    # The source line is what separates a figure from a poster. Small, always
    # present, never the same colour as the number.
    stamp_source(d, (figure.get("source") or "").strip())
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
    # voice says the rest of it is the worst of both. fit_block grows as well as
    # shrinks — the previous version started at 84 and only stepped down, so a
    # short sentence sat in the top third of a dark frame.
    TOP, BOTTOM = 250, 170
    size, lines = fit_block(d, text, W - 300, H - TOP - BOTTOM, SERIF_BOLD)
    f = _font(SERIF_BOLD, size)
    lead = int(size * 1.34)
    y = max(TOP, (H - BOTTOM - len(lines) * lead) // 2)
    d.line([(120, y - 46), (300, y - 46)], fill=ACCENT, width=6)
    for line in lines:
        d.text((120, y), line, font=f, fill=PAPER)
        y += lead
    stamp_source(d, attribution)
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
        tsize, tlines = fit_block(d, title, W - 240, 180, SERIF_BOLD,
                                  max_size=78, min_size=44)
        tf = _font(SERIF_BOLD, tsize)
        for line in tlines[:2]:
            d.text((120, y), line, font=tf, fill=PAPER)
            y += int(tsize * 1.2)
        y += 30

    rows = table.get("rows") or []
    # Fit the rows into what is left rather than assuming a count: five states
    # and twelve want different leading, and a fixed one either overflows the
    # frame or strands the list in its top third.
    #
    # This grows too. Capped at 52 only when the longest row would otherwise run
    # past the margin — a three-row list should fill the frame, not sit in it.
    avail = H - y - 170
    size = 26
    while size < 86:
        nxt = size + 2
        if len(rows) * int(nxt * 1.55) > avail:
            break
        if max((d.textlength(r.get("text", "")[:60], font=_font(MONO, nxt))
                for r in rows), default=0) > W - 300:
            break
        size = nxt

    # Type size here is bound by WIDTH, not height: these rows are monospaced
    # and already near the margin at 52pt, so growing them cannot fill the
    # frame. A short list therefore has to be SPREAD rather than enlarged —
    # otherwise three rows cluster under the title and leave the bottom third
    # dark, which is exactly what the first version of this fix missed.
    lead = int(size * 1.55)
    if rows:
        lead = max(lead, min(avail // len(rows), int(size * 3.2)))
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

    stamp_source(d, (table.get("source") or "").strip())
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


# Chatterbox generates a bounded number of tokens per call and silently returns
# whatever it managed — there is no error and no flag. A reel beat is ~30 words
# and always fits, so the daily path has never seen this. Long-form chapters run
# 130-210 words, and on the first real render two of them came back with NINE
# PERCENT of their audio: 1,157 words became 2.7 minutes, which is 421 words a
# minute. Nobody spoke most of that script.
#
# So a unit is synthesised in sentence-sized pieces and stitched. This is the
# one place long-form must NOT reuse reel.synth_beats as-is: that function
# deliberately voices a whole beat in one call to keep one prosody contour, and
# that is right for 30 words and impossible for 200.
MAX_SYNTH_WORDS = 34

# How far BEFORE the words a frame appears. A frame that cuts in exactly as the
# number is said reads as late, because the eye needs a beat to travel to it.
LEAD_IN = 2.0
# How long a shot must hold, BY WHAT IS ON IT. One number for everything was
# wrong in a way only watching catches — Anil, 2026-09-14: "figures disappear
# fast, the words stay longer."
#
# A quote frame is a sentence the narrator is reading aloud at that moment; the
# viewer is hearing it, and the frame only has to keep up. A figure is the
# opposite: a number, a label and a source, none of it spoken in full, and the
# viewer has to actually read it. A record is a page of a document. Giving them
# the same three seconds meant the evidence flashed past while the subtitles sat
# there.
MIN_SHOT_BY_KIND = {
    "record": 7.0,      # a page of a PDF, with a quote pulled out beside it
    "table":  7.0,      # rows to scan
    "figure": 6.0,      # number + label + source
    "photo":  5.0,
    "clip":   5.0,
    "quote":  3.5,      # being read aloud simultaneously
    "image":  2.5,      # atmosphere; the least of these
}
MIN_ANCHORED_SHOT = 3.0     # floor for anything not named above

# Longest an ILLUSTRATION may hold. Separate from MAX_HOLD because the problem
# is different: a long evidence shot is dwelling on the proof, a long
# illustration is the screen doing nothing. On the 44-shot cut six generated
# scenes took 79 seconds — 19% of the video — and read as dead air.
MAX_IMAGE_HOLD = 6.0

# Most of a unit's shots that may be quote frames. Not a style rule: subtitles
# are what the renderer reaches for when it has nothing to show, so an unbounded
# share is a silent measure of how little evidence the script actually carried.
QUOTE_SHARE = 0.40
MAX_QUOTE_HOLD = 10.0

# What a kind is WORTH when two assets want the same moment. Separate from the
# anchor score, which measures only how confident the match is — confidence and
# editorial priority are different questions and mixing them was a bug.
#
# A quote frame matches its own sentence exactly, so it scored the length of
# that sentence: ten to fifteen. A figure scores the number of distinctive terms
# it shares with a chunk: two to twenty, usually under six. _best_monotone
# maximises total score, so quote frames systematically won, and on the 44-shot
# cut the words took 34% of the screen against the figures' 21%. Anil, watching
# it: "the words take more precedence than the figures in some places."
#
# plan_assets already ranks evidence above illustration when handing out SLOTS.
# This is the same policy applied to TIME, which is the half that was missing.
KIND_WEIGHT = {
    "record": 4.0,
    "figure": 4.0,
    "table":  3.0,
    "photo":  3.0,
    "clip":   3.0,
    "quote":  1.0,
    "image":  0.5,
}
# Number of assets that must carry a believed anchor before reordering happens
# at all. Two is the minimum that can disagree about order.
#
# There is deliberately NO separate, higher score threshold for reordering. One
# was tried and it backfired: a figure whose anchor scored 2 was believed enough
# to pin but not enough to move, so it stayed in front of the quote frames, and
# _best_monotone then had to drop it to keep the rest in order. Being dropped
# turned it into a free asset, which landed it in the widest gap — the opening —
# 35 seconds before the sentence that says it. An anchor is either believed or
# it is not.
ANCHOR_REORDER_MIN = 2
# Past this, a stronger match is not a better claim on the moment — it just means
# a longer sentence. Capping first is what makes KIND_WEIGHT mean anything.
ANCHOR_SCORE_CAP = 6
# Longest any one frame may hold. Not a style preference — this is the number
# that decides whether the thing is a video or an audio-book with a cover. When
# every anchor in a chapter clumps late, placement alone cannot fix the dead air
# in front of them; the unit needs MORE frames, so fit_unit buys them.
MAX_HOLD = 20.0
# How many frames above the duration-derived budget fit_unit may buy. A cap, not
# a target: past this the unit is being cut faster than it is being spoken.
MAX_EXTRA_SHOTS = 4


def _chunk_for_synth(text, max_words=MAX_SYNTH_WORDS):
    """Sentence-aligned pieces, each small enough to survive the voice server.

    Split on sentence ends, never mid-clause: a chunk boundary is a breath, and
    a boundary inside a clause is audible. A single sentence longer than the cap
    is passed whole rather than cut — truncating it is the failure we are
    fixing, and a slightly long chunk is better than a severed one.
    """
    import re as _re

    out, cur = [], []
    for sent in _re.split(r"(?<=[.?!])\s+", (text or "").strip()):
        if not sent:
            continue
        if cur and len(" ".join(cur).split()) + len(sent.split()) > max_words:
            out.append(" ".join(cur))
            cur = []
        cur.append(sent)
    if cur:
        out.append(" ".join(cur))
    return out or [""]


def voice_cache_dir():
    """Where synthesised chunks are kept between renders.

    Beside the work directories rather than inside one, because the whole point
    is to outlive them: a work dir is per-render and timestamped (two renderers
    raced into the same one on 2026-09-12), and the audio is the part that does
    not change when a render is repeated.
    """
    return Path(os.environ.get(
        "LONGFORM_DIR", os.path.expanduser("~/.thelivu/longform"))) / "voice-cache"


def _synth_cached(chunk, dest, backend, voice):
    """Synthesise one chunk, or copy it from the cache if it has been said before.

    Chatterbox takes roughly seven minutes of wall clock per minute of speech on
    the worker box. Re-rendering long-form #1 to test a change to FRAME PLACEMENT
    — which cannot affect a single sample of audio — cost fifty minutes of that
    every time. The script is the same script; the voice is deterministic given
    the same text and speaker.

    Keyed on the text, the backend and the voice together, so changing the voice
    or the engine correctly misses. A corrupt or truncated cache entry is
    re-synthesised rather than trusted: silent truncation is exactly the failure
    this module already exists to work around.
    """
    key = hashlib.sha256(
        "\x00".join([chunk or "", backend or "", voice or ""]).encode("utf-8")
    ).hexdigest()
    cached = voice_cache_dir() / f"{key}.wav"

    if cached.exists():
        try:
            with wave.open(str(cached), "rb") as w:
                if w.getnframes() > 0:
                    shutil.copyfile(cached, dest)
                    return
            log.info("voice cache entry %s is empty — re-synthesising", key[:12])
        except (wave.Error, EOFError, OSError) as e:
            # EOFError is the zero-byte case, which is the LIKELY one: a render
            # killed mid-copy leaves exactly that behind. wave.open raises it
            # rather than wave.Error, so leaving it out made the cache trust a
            # file it had just decided it could not read.
            log.info("voice cache entry %s unreadable (%s) — re-synthesising",
                     key[:12], e)

    from publishing import reel
    reel._synth(chunk, dest, backend, voice=voice)
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".wav.part")
        shutil.copyfile(dest, tmp)
        tmp.rename(cached)
    except OSError as e:
        log.info("could not cache synthesised chunk: %s", e)


def synth_units(units, backend, work_dir, voice=None):
    """Voice each unit in pieces and stitch, returning reel.synth_beats' shape.

    [(wav_path, duration_including_gap, [pause_times], [(start, text), ...])],
    aligned with `units`. Pauses are found on the STITCHED wav so cut planning
    sees the real thing; the fourth element says when each chunk of text is
    actually spoken, which is what lets a figure appear as it is said.
    """
    from publishing import reel

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, text in enumerate(units):
        chunks = _chunk_for_synth(text)
        parts = []
        for j, chunk in enumerate(chunks):
            part = work_dir / f"a{i}_{j}.wav"
            _synth_cached(chunk, part, backend, voice)
            parts.append(part)

        joined = work_dir / f"a{i}.wav"
        with wave.open(str(parts[0]), "rb") as first:
            params = first.getparams()
        with wave.open(str(joined), "wb") as w:
            w.setparams(params)
            for part in parts:
                with wave.open(str(part), "rb") as r:
                    w.writeframes(r.readframes(r.getnframes()))

        # Where each chunk starts in the stitched take. This is REAL timing, not
        # an estimate: the chunks were synthesised separately, so their lengths
        # are known exactly. Anil, 2026-09-13: "in the first minute itself, i did
        # find places where proper alignment would have made it better." Placing
        # assets in declaration order threw this away.
        marks, t = [], 0.0
        for part in parts:
            marks.append((t, chunks[len(marks)]))
            t += reel._duration(part)

        dur = reel._duration(joined) + reel.GAP_SECS
        words = len((text or "").split())
        spoken = words / (dur / 60.0) if dur else 0
        if words > 20 and spoken > 260:
            # Loud, because this is exactly the failure that shipped silently.
            log.warning("unit %s reads at %.0f words/min over %d chunks — the "
                        "voice server is still dropping text", i, spoken, len(chunks))
        log.info("voiced unit %s: %d words, %d chunks, %.1fs (%.0f wpm)",
                 i, words, len(chunks), dur, spoken)
        out.append((joined, dur, reel.find_pauses(joined), marks))
    return out


def _sentences(text):
    """Narration split into sentences, long ones only. Short connectives ("That
    figure is real.") are true but make a weak frame."""
    import re as _re
    parts = [p.strip() for p in _re.split(r"(?<=[.?!])\s+", (text or "").strip())]
    return [p for p in parts if len(p.split()) >= 6]


def quote_fill(text, have, want, anchored=False):
    """Quote frames to fill the shots a unit earned but did not declare assets for.

    Two modes, because there are two ways the shots get timed.

    WITHOUT anchoring, shots run sequentially over one continuous take, so the
    frame in slot j of k shows a sentence from about j/k of the way through —
    the line on screen tracks what is being said with no word-level timing. The
    evidence occupies the first `have` slots, so the quotes start after them.

    WITH anchoring that reasoning inverts, and keeping it was a real bug. The
    evidence no longer occupies the leading slots; it lands wherever it is
    spoken, which is often late. Offering quotes only from the last
    (1 - have/want) of the text then left the OPENING with nothing to show but
    an illustration — chapter 6 of long-form #1 held one for 22 seconds while
    the narration laid out its whole argument, and the sentences that would have
    covered it were never candidates. So when the caller can anchor, quotes are
    drawn from the whole text and placed by where they are spoken.
    """
    need = max(0, want - have)
    sents = _sentences(text)
    if not need or not sents:
        return []
    out, used = [], set()
    for i in range(need):
        if anchored:
            frac = (i + 0.5) / need
        else:
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


# Words the narration spells out, so a figure written "₹39,230.33 crore" can be
# found in a sentence that says "thirty-nine thousand two hundred and thirty".
# Only the distinctive ones: "one" and "two" appear everywhere and anchor nothing.
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "to", "and", "or", "for",
              "it", "its", "that", "this", "as", "at", "by", "is", "was",
              "crore", "lakh", "rupees", "per", "cent", "percent"}


def _spell(n):
    """A number as the narration says it: 39230 -> 'thirty nine thousand two
    hundred thirty'.

    Needed because a FIGURE line carries digits and the script carries words —
    they are the same fact written for two different readers, and matching them
    is the whole basis of putting a figure on screen as it is spoken. Extracting
    only the leading tens ('thirty') was not enough: it lost to the label's
    rarer words and anchored the ₹39,230 card to the wrong sentence.
    """
    if n < 0 or n > 999_999:
        return []
    if n < 20:
        return [_ONES[n]] if n else []
    if n < 100:
        return [w for w in (_TENS[n // 10], _ONES[n % 10]) if w]
    if n < 1000:
        return [_ONES[n // 100], "hundred"] + _spell(n % 100)
    return _spell(n // 1000) + ["thousand"] + _spell(n % 1000)
def _anchor_terms(asset):
    """Distinctive words that should appear in the sentence where this asset
    belongs. Empty when there is nothing to go on, which means "do not guess"."""
    import re as _re

    if asset["kind"] == "quote":
        return [asset["text"]]            # exact — it IS a sentence of the take
    if asset["kind"] == "figure":
        f = asset["figure"]
        # The VALUE twice: a figure belongs where its number is spoken, not
        # where its label happens to echo. Without this weighting the ₹39,230
        # card anchored to the sentence describing KIIFB rather than the one
        # saying the amount, because the label simply has more rare words in it.
        src = f"{f.get('value','')} {f.get('value','')} {f.get('label','')}"
    elif asset["kind"] == "table":
        src = asset["table"].get("title", "")
    elif asset["kind"] == "record":
        src = asset["record"].get("quote") or asset["record"].get("description", "")
    else:
        return []

    terms = []
    for tok in _re.findall(r"[A-Za-z]{4,}|\d[\d,.]*", src):
        if tok.lower() in _STOPWORDS:
            continue
        if tok[0].isdigit():
            head = tok.replace(",", "").split(".")[0]
            try:
                words = _spell(int(head))
            except ValueError:
                words = []
            # The spoken form as ONE term where it is long enough to be
            # distinctive — "thirty nine thousand" matches a sentence, "thirty"
            # matches half the script — plus the individual words as backup.
            if len(words) >= 2:
                terms.append(" ".join(words[:3]))
            terms.extend(words)
        else:
            terms.append(tok.lower())
    return terms


def cuts_from_anchors(assets, marks, dur, pauses, plan_cuts):
    """Shot lengths that put each asset on screen while it is being spoken.

    The renderer used to place assets in declaration order and cut on a
    stopwatch, which is only right when the writer happens to list them in
    narration order. Now every chunk's start time is known exactly — the chunks
    were synthesised separately — so an asset that can be located in the text
    gets its shot boundary at that chunk.

    Two kinds of asset, treated differently on purpose:

      PINNED    A figure, record, table or quote frame whose content was found
                in the narration. It belongs at that moment and nowhere else.

      FREE      An illustration, or evidence whose anchor was too weak to
                believe. It has no opinion about when it appears, so it is put
                wherever the screen would otherwise sit longest on one frame.

    That second rule is the one that stops the audio-book feeling. Spreading
    free assets evenly in declaration order leaves the long holds exactly where
    the anchors happened to clump; spending them on the widest gaps is what a
    person cutting this by hand would do.

    Returns lengths summing to exactly `dur`, same contract as plan_cuts.
    """
    return _placements(assets, marks, dur, pauses, plan_cuts)[1]


def _placements(assets, marks, dur, pauses, plan_cuts):
    """(screen order as indices into `assets`, shot length per slot).

    The order is returned rather than applied so that the one caller who needs
    both — align_to_narration — cannot get them out of step.
    """
    k = len(assets)
    if k <= 1 or not marks:
        return list(range(k)), plan_cuts(dur, k, pauses)

    scored = [_anchor_score(a, marks) for a in assets]
    times = [marks[ci][0] if ci is not None else None for ci, _sc in scored]
    keep = _best_monotone(times, [_weighted(assets[i], scored[i][1])
                                  for i in range(k)])
    if not keep:
        return list(range(k)), plan_cuts(dur, k, pauses)

    # Pin the anchored ones. A frame that cuts in exactly as the number is said
    # reads as late — the eye needs a beat to travel to it — so LEAD_IN puts it
    # just before.
    #
    # Ties are spread across the chunk rather than stacked. A figure and the
    # record that evidences it cite the same number and therefore anchor to the
    # same chunk BY CONSTRUCTION; stacking them meant one of the two was
    # squeezed to the minimum shot length and effectively lost.
    start = {}
    by_chunk = {}
    for i in keep:
        by_chunk.setdefault(scored[i][0], []).append(i)
    for ci, group in by_chunk.items():
        head = max(0.0, marks[ci][0] - LEAD_IN)
        end = marks[ci + 1][0] if ci + 1 < len(marks) else dur
        span = max(end - marks[ci][0], MIN_ANCHORED_SHOT * len(group))
        for j, i in enumerate(sorted(group)):
            start[i] = head + span * j / len(group)

    # A free asset that HAS an anchor still goes where it was spoken. It is free
    # only because keeping it would have broken the running order, which is a
    # reason to place it loosely, not a reason to place it anywhere.
    for i in range(k):
        if i not in start and times[i] is not None:
            start[i] = max(0.0, times[i] - LEAD_IN)

    # Everything genuinely unplaced — illustrations — goes where the screen
    # would otherwise sit longest on one frame.
    free = [i for i in range(k) if i not in start]
    for i in free:
        edges = sorted(start.values()) + [dur]
        if edges[0] > MIN_ANCHORED_SHOT:
            edges = [0.0] + edges
        gaps = [(edges[j + 1] - edges[j], edges[j]) for j in range(len(edges) - 1)]
        width, at = max(gaps)
        start[i] = at + width / 2 if width > 2 * MIN_ANCHORED_SHOT else at + width

    order = sorted(range(k), key=lambda i: (start[i], i))
    starts = [start[i] for i in order]
    starts[0] = 0.0                      # something is on screen from frame one

    floors = [min_shot_for(assets[i]) for i in order]
    for i in range(1, k):
        if starts[i] - starts[i - 1] < floors[i - 1]:
            starts[i] = starts[i - 1] + floors[i - 1]
    # Pull back from the end if the floors have pushed past it, respecting each
    # remaining shot's own floor rather than one shared number.
    tail_need = 0.0
    for i in range(k - 1, 0, -1):
        tail_need += floors[i]
        starts[i] = min(starts[i], dur - tail_need)
    starts[0] = 0.0
    for i in range(1, k):
        starts[i] = max(starts[i], starts[i - 1] + 0.5)

    lengths = [round(starts[i + 1] - starts[i], 3) for i in range(k - 1)]
    lengths.append(round(dur - sum(lengths), 3))
    return order, lengths


def _weighted(asset, score):
    """Anchor confidence, scaled by what the asset is worth.

    The raw score is capped first. A quote frame's score is the length of the
    sentence it matched, which is unbounded and on a different scale from a
    figure's term count — left uncapped, one long sentence outweighs three
    figures no matter what the weights say.
    """
    return min(score, ANCHOR_SCORE_CAP) * KIND_WEIGHT.get(asset.get("kind"), 1.0)


def min_shot_for(asset):
    """How long this frame must stay up, by what is on it."""
    return MIN_SHOT_BY_KIND.get(asset.get("kind"), MIN_ANCHORED_SHOT)


def max_hold_for(asset):
    """How long this frame may stay up before the screen is doing nothing.

    An illustration gets a much shorter leash than evidence. Dwelling on a
    document page is the video doing its job; dwelling on a generated scene is
    dead air, and a unit that cannot fill the gap any other way should be buying
    another quote frame instead.
    """
    kind = asset.get("kind")
    if kind == "image":
        return MAX_IMAGE_HOLD
    if kind == "quote":
        # A subtitle tracks a sentence. Letting one absorb a fifteen-second gap
        # is the same dead air as a long illustration, just with text on it.
        return MAX_QUOTE_HOLD
    return MAX_HOLD


def _best_monotone(times, scores):
    """Indices of the highest-scoring non-decreasing run of anchors.

    NON-decreasing, not strictly increasing: a figure and the record that
    evidences it cite the same number and therefore anchor to the same chunk by
    construction. Forcing them apart here discarded one of them; letting them
    share a time and separating them afterwards with MIN_ANCHORED_SHOT keeps
    both, in the order the writer declared them.
    """
    idx = [i for i, t in enumerate(times) if t is not None]
    if not idx:
        return []
    best = {}
    for i in idx:
        run, sc = [i], scores[i]
        for j in idx:
            if j >= i:
                break
            if times[j] <= times[i] and j in best:
                cand_run, cand_sc = best[j]
                if cand_sc + scores[i] > sc:
                    run, sc = cand_run + [i], cand_sc + scores[i]
        best[i] = (run, sc)
    return max(best.values(), key=lambda rs: (rs[1], len(rs[0])))[0]


def fit_unit(assets, text, want, images, marks, dur, pauses, plan_cuts):
    """(assets in screen order, shot lengths) for one unit, with no long holds.

    `want` is a budget derived from duration alone, and duration alone cannot
    see that a chapter says all four of its numbers in the last twenty seconds.
    When it does, the frames pile up at the end and the opening sits on one
    image for half a minute — chapter 6 of long-form #1 held a generated
    illustration for 33 seconds while the narration laid out the whole argument.

    So the budget is not final. Place the shots, look at the longest hold, and
    if it is over MAX_HOLD buy another frame and try again. quote_fill runs out
    of unused sentences on its own, which is the natural stopping point: when
    there is nothing left to put on screen, holding is the honest answer.
    """
    def overrun(ordered, cuts):
        """Seconds by which the worst shot outstays what its kind is worth."""
        return max((c - max_hold_for(a) for a, c in zip(ordered, cuts)),
                   default=0.0)

    best = None
    for extra in range(0, MAX_EXTRA_SHOTS + 1):
        filled = with_filler(assets, text, want + extra, images=images,
                             anchored=bool(marks))
        k = min(want + extra, len(filled)) or 1
        ordered, cuts = align_to_narration(filled[:k], marks, dur, pauses, plan_cuts)
        over = overrun(ordered, cuts)
        if best is None or over < overrun(*best):
            best = (ordered, cuts)
        if over <= 0:
            return ordered, cuts
        if len(filled) < want + extra:
            break            # filler exhausted — holding is the honest answer
    return best


def align_to_narration(assets, marks, dur, pauses, plan_cuts):
    """(assets in the order they appear on screen, shot lengths for them).

    One entry point so the caller cannot reorder without recutting, or cut
    without reordering — the two have to agree or every frame is wrong by one.
    """
    ordered = order_by_narration(assets, marks)
    order, cuts = _placements(ordered, marks, dur, pauses, plan_cuts)
    return [ordered[i] for i in order], cuts


def anchor_chunk(asset, marks):
    """Index of the chunk where this asset's content is spoken, or None.

    None means "no evidence" — the caller then falls back to spreading assets
    evenly, which is what the renderer did for everything before this. Guessing
    an anchor is worse than admitting there isn't one: a figure placed on the
    strength of one shared common word lands somewhere arbitrary and looks
    deliberate.
    """
    return _anchor_score(asset, marks)[0]


def _anchor_score(asset, marks):
    """(chunk index, match score), or (None, 0).

    The score is kept and not thrown away because two assets regularly want the
    same chunk — a figure and the record that evidences it cite the same number
    by construction — and deciding which one keeps the anchor needs to be a
    judgement about match strength, not about which was declared first.
    """
    # An ENCORE never anchors. It is the same figure returning to the screen, so
    # it matches the same chunk as the original by construction — and letting it
    # claim that beat put two assets on one moment and pushed the original off
    # it. On-beat placement fell from 75% to 56% the first time encores existed.
    # A repeat is a gap-filler: it goes where the screen would otherwise be
    # empty, which is what free placement already does well.
    if asset.get("encore"):
        return None, 0
    terms = _anchor_terms(asset)
    if not terms or not marks:
        return None, 0
    if asset["kind"] == "quote":
        needle = " ".join(terms[0].lower().split())
        for i, (_t, text) in enumerate(marks):
            if needle[:40] in " ".join(text.lower().split()):
                return i, len(needle.split())
        return None, 0

    best, best_score = None, 0
    for i, (_t, text) in enumerate(marks):
        low = " ".join(text.lower().split())
        score = sum(1 for term in terms if term in low)
        if score > best_score:
            best, best_score = i, score
    # One shared word is coincidence; two is a match. A single term is accepted
    # only when that is all the asset had to offer.
    if best_score >= 2 or (best_score == 1 and len(terms) == 1):
        return best, best_score
    return None, 0


def order_by_narration(assets, marks):
    """Reorder assets into the order the narration actually reaches them.

    THIS REVERSES A DELIBERATE EARLIER DECISION, so the reasoning matters. The
    first version refused to reorder, on the grounds that "the script's order is
    the argument's order, and a figure jumping ahead of the sentence that sets
    it up reads as a mistake." That was right when anchors were unreliable — but
    it also meant declaration order silently overrode the narration, and the
    first real render showed what that costs.

    Chapter 1 of long-form #1 declared FIGURE, FIGURE, TABLE, RECORD. The
    narration reaches them at 10.7s, 29.3s, 0.0s and 10.7s. Because the two
    out-of-order anchors came later in the list, the old monotonic filter
    dropped BOTH of them, and the opening figure held the screen from 0 to
    29.3s — on screen eighteen seconds after it was spoken, which is the
    audio-book failure in its purest form.

    Narration order IS the argument's order. A writer listing evidence under a
    chapter heading is not choreographing it; the sentences are. So assets with
    a confident anchor are sorted by when they are spoken, and anything without
    one keeps its place relative to the anchored asset it followed — an
    illustration or a quote frame has no opinion about where it belongs, and
    moving it would be the guess this function is careful not to make.
    """
    if not marks or len(assets) < 2:
        return list(assets)

    scored = [_anchor_score(a, marks) for a in assets]
    # Every anchor _anchor_score accepted is used. If an anchor is good enough
    # to hang a shot on, it is good enough to say which shot comes first.
    strong = [i for i, (ci, _sc) in enumerate(scored) if ci is not None]
    if len(strong) < ANCHOR_REORDER_MIN:
        return list(assets)

    order = sorted(strong, key=lambda i: (marks[scored[i][0]][0], i))
    if order == strong:
        return list(assets)          # already in narration order

    # Carry each unanchored asset with the anchored one it trailed, so a quote
    # frame written to follow a figure still follows that figure.
    trailing = {i: [] for i in strong}
    head, current = [], None
    for i in range(len(assets)):
        if i in trailing:
            current = i
        elif current is None:
            head.append(i)
        else:
            trailing[current].append(i)

    out = [assets[i] for i in head]
    for i in order:
        out.append(assets[i])
        out.extend(assets[j] for j in trailing[i])
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


def with_filler(assets, text, want, images=(), anchored=False):
    """Fill a unit's shot budget: evidence, then narration, then at most one
    picture — and the picture only if the unit can spare a slot.

    `MIN_SHOTS_FOR_IMAGE` is the whole policy. A generated scene is atmosphere,
    and atmosphere is what you add once the argument is already on screen; in a
    unit with two or three shots there is nothing to spare, and a quote frame
    beats a picture of the idea of a quote every time.

    QUOTE_SHARE is the newer half. Filling every spare slot with a sentence of
    the narration meant that on a 7-minute cut the subtitles held the screen for
    52% of it against the figures' 20% — Anil, watching it: "the words take more
    precedence than the figures in some places." Past that share the unit
    re-shows evidence it has already earned instead. A figure coming back when
    the narration returns to it is the argument being made twice; a fifteenth
    quote frame is the screen giving up.
    """
    out = list(assets[:want])
    room = want - len(out)
    if room <= 0:
        return out[:want]
    quotes = quote_fill(text, len(out), want, anchored=anchored)
    encores = encore(assets, want)
    # An illustration only earns a slot in a unit with NO evidence to show
    # again. "Atmosphere is what you add once the argument is already on screen"
    # was always the rule; before encores existed there was nothing else to
    # reach for, so every long unit got one whether or not it had better. On the
    # 58-shot cut that was 64 seconds of generated scene competing with figures
    # for the same gaps — and when the daily image cap is spent, competing as a
    # blank background.
    picture = (list(images)[:MAX_IMAGES_PER_UNIT]
               if want >= MIN_SHOTS_FOR_IMAGE and not encores else [])
    budget = want - len(picture)

    # INTERLEAVED, evidence first. Appending the encores after the quotes left
    # the quotes holding every wide gap anyway — order decides what survives the
    # truncation to `want`, and it decides which asset lands in the dead air the
    # anchors left. Evidence goes first for both reasons.
    fill, qi, ei = [], 0, 0
    max_quotes = max(1, int(round(budget * QUOTE_SHARE)))
    while len(out) + len(fill) < budget and (qi < len(quotes) or ei < len(encores)):
        if ei < len(encores) and (qi >= max_quotes or qi >= len(quotes)):
            fill.append(encores[ei]); ei += 1
        elif qi < len(quotes):
            fill.append(quotes[qi]); qi += 1
        else:
            break
        # One quote, then one piece of evidence, so neither runs away.
        if ei < len(encores) and qi < max_quotes and len(out) + len(fill) < budget:
            fill.append(encores[ei]); ei += 1
    out += fill
    out += [{"kind": "image", "prompt": p} for p in picture]
    # A unit with nothing to say and nothing declared still needs one frame.
    if not out:
        out = [{"kind": "image", "prompt": (list(images) or [None])[0]}]
    return out[:want]


def encore(assets, n):
    """Evidence shown again, hardest first. Never the same thing twice running.

    A repeat is not padding. The narration comes back to a number — that is what
    a chapter DOES — and when it does, the number belongs on screen again. The
    alternative this replaced was another line of subtitles, which is the screen
    admitting it has nothing to show.
    """
    if n <= 0:
        return []
    pool = [a for a in assets if a.get("kind") in ("figure", "record", "table",
                                                   "photo")]
    if not pool:
        return []
    out = []
    for i in range(n):
        again = dict(pool[i % len(pool)])
        again["encore"] = True
        out.append(again)
    return out


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
    from publishing.reel import plan_cuts

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
    voiced = synth_units([text for _k, _c, text in units],
                         "chatterbox", tmp / "vo", voice=voice)

    # 2. Plan what each unit puts on screen, against those real durations.
    #    Figures and records first, illustrations last — see plan_assets.
    plans = []          # per unit: [(asset, seconds)]
    for (key, chap, text), (_wav, dur, pauses, marks) in zip(units, voiced):
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
        # NO "if not assets: use an image" here. That line survived the change
        # that made plan_assets return evidence only, and it silently undid the
        # whole ordering: any unit without a figure or a record had a picture
        # injected before with_filler ever ran, so the close — which declares no
        # CLOSE_FIGURE — took that path every single time. with_filler already
        # guarantees at least one frame.
        # Quote frames fill whatever the writer did not declare, and a picture
        # gets the last slot only in a unit long enough to spare one. Before
        # 2026-09-11 the filler was a generated illustration and they kept being
        # worse than nothing — see draw_quote_frame. A shot budget is now always
        # fillable, so a unit never holds one frame for a minute either.
        want = _shot_count(dur, max(len(assets) + 1, _shot_count(dur, 99)))
        declared_images = ((chap or {}).get("images")
                           or ([fallback] if fallback else []))
        ordered, cuts = fit_unit(assets, text, want, declared_images,
                                 marks, dur, pauses, plan_cuts)
        plans.append(list(zip(ordered, cuts)))

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
    for i, ((key, chap, _t), (wav, _dur, _pauses, _marks)) in enumerate(zip(units, voiced)):
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
