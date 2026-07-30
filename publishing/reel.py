"""Reels V1 — a captioned, voiceover-only vertical reel from a video-script.

Local and free: Piper TTS for the voice, Pillow for the Dossier-look frames (same
palette/fonts as publishing.slides), ffmpeg to animate + mux. No avatar, no paid
API. Output is a 1080x1920 H.264+AAC MP4, 5-90s, Instagram-Reel eligible. See
docs/reels-v1-build.md.

The human gate is unchanged: this only RENDERS the MP4. Posting a reel is a gated
action (same as a carousel) and happens elsewhere, on approval.

CLI:
  python -m publishing.reel --script path/to/script.md --out articles/reels/r.mp4 [--dark]
"""
import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from publishing.slides import (
    SERIF_BOLD, MONO, MONO_BOLD, PALETTE, _font, _wrap_to_width,
)

# 9:16 for Reels. IG overlays UI on the bottom ~15% and right edge — keep text out.
W, H = 1080, 1920
# TTS backend is pluggable: 'piper' (local, robotic, zero-setup) or 'omnivoice'
# (OmniVoice Studio's OpenAI-compatible sidecar on :3900 — better voice, still
# local/free; run KittenTTS there for CPU-realtime English narration).
TTS_BACKEND = os.environ.get("TTS_BACKEND", "piper")
PIPER_BIN = os.path.expanduser("~/.local/bin/piper")
PIPER_VOICE = os.path.expanduser("~/.jarvis/voices/en_GB-alan-medium.onnx")
OMNIVOICE_URL = os.environ.get("OMNIVOICE_URL", "http://127.0.0.1:3900")
OMNIVOICE_MODEL = os.environ.get("OMNIVOICE_MODEL", "kittentts")
OMNIVOICE_VOICE = os.environ.get("OMNIVOICE_VOICE", "default")
# chatterbox: Anil's cloned voice via the persistent Chatterbox server
# (publishing/chatterbox_server.py, runs in the ~/cbx venv). Local, free, CPU.
CHATTERBOX_URL = os.environ.get("CHATTERBOX_URL", "http://127.0.0.1:3901")
GAP_SECS = 0.35          # silence between beats; also the caption hold padding
FPS = 30


# ── script parsing ────────────────────────────────────────────────────────────
def parse_script(text):
    """Parse the video-script skill output into ordered (spoken, caption) beats.

    Returns {"title", "stamp"?, "beats": [(spoken, caption), ...], "hashtags"}.
    Hook and close are just the first/last beats — same rendering, so they collapse
    into one ordered list."""
    # The gap after the colon is `[ \t]*`, NOT `\s*`. `\s` matches newlines, so with
    # MULTILINE `^LABEL:\s*(.+)$` reached PAST an empty label line and captured the next
    # line's text: a bare `HOOK:` silently stole BEAT 1's sentence as the hook (and then
    # BEAT 1 was spoken twice), and a bare `CLOSE:` stole the HASHTAGS line. An empty
    # label must read as empty.
    def one(label):
        m = re.search(rf"^{label}:[ \t]*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    title = one("TITLE")
    kicker = one("KICKER")   # small context tag shown on every slide
    beats = []
    # Optional per-beat scene description for the illustrated look. Absent in
    # older scripts (and when a model skips it) — publishing.illustrate falls
    # back to deriving a scene from the caption.
    images = []

    hook, hook_cap = one("HOOK"), one("HOOK_CAPTION")
    if hook:
        beats.append((hook, hook_cap or hook))
        images.append(one("HOOK_IMAGE"))

    # BEAT 1 / BEAT 1 CAPTION / BEAT 1 IMAGE, BEAT 2 / ... in order
    # Same horizontal-only whitespace rule as `one()` — an empty `BEAT 2:` must not
    # swallow the `BEAT 2 CAPTION:` line below it.
    spoken = {int(m.group(1)): m.group(2).strip()
              for m in re.finditer(r"^BEAT[ \t]+(\d+):[ \t]*(.+)$", text, re.IGNORECASE | re.MULTILINE)}
    caps = {int(m.group(1)): m.group(2).strip()
            for m in re.finditer(r"^BEAT[ \t]+(\d+)[ \t]+CAPTION:[ \t]*(.+)$", text, re.IGNORECASE | re.MULTILINE)}
    imgs = {int(m.group(1)): m.group(2).strip()
            for m in re.finditer(r"^BEAT[ \t]+(\d+)[ \t]+IMAGE:[ \t]*(.+)$", text, re.IGNORECASE | re.MULTILINE)}
    for i in sorted(spoken):
        beats.append((spoken[i], caps.get(i, spoken[i])))
        images.append(imgs.get(i, ""))

    close, close_cap = one("CLOSE"), one("CLOSE_CAPTION")
    if close:
        beats.append((close, close_cap or close))
        images.append(one("CLOSE_IMAGE"))

    hashtags = one("HASHTAGS")
    # Whether the script actually opened on a HOOK, reported separately because the
    # beats list alone can't tell you: a script whose HOOK line is missing still
    # produces beats (BEAT 1…n) and renders happily, opening the reel on a mid-story
    # beat. The hook IS the reel — callers must be able to reject a script without one.
    # The Instagram description = the FULL narration (all spoken lines as prose),
    # so the whole story is in the caption for readers/muted viewers and every
    # acronym/number is correct in text. Built here so post-time can reuse it.
    narration = " ".join(sp for sp, _ in beats)
    return {"title": title, "kicker": kicker, "beats": beats, "images": images,
            "hashtags": hashtags, "narration": narration, "hook": hook}


# ── frame rendering (Dossier look, 9:16) ────────────────────────────────────────
def _is_highlight_token(tok):
    """A token to render in the accent colour: a number, a ₹-amount, or an
    ALL-CAPS acronym (KIIFB, CAG, RBI…). These are exactly the things the voice
    can mangle, so showing them — emphasised — on the slide is the fix."""
    core = tok.strip('.,;:!?—-–"\'()')
    if not core:
        return False
    if "₹" in tok or any(c.isdigit() for c in tok):
        return True
    letters = [c for c in core if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def _draw_emph_block(d, caption, font, line_h, max_w, top_y, fg, accent, size=None):
    """Word-wrap `caption` to max_w and draw it centred from top_y, colouring
    highlight tokens (numbers/₹/acronyms) in `accent`. Returns block height.

    Tokens carrying a glyph the serif lacks (the math operators) are drawn from
    the mono face so the symbol survives — measurement and drawing must use the
    SAME font per token or the centring drifts.
    """
    fb = None
    if size and any(_needs_fallback(w) for w in caption.split()):
        # Mono runs visually larger than the serif at the same nominal size.
        fb = _font(MONO_BOLD, int(size * 0.88))

    def tf(token):
        return fb if (fb and _needs_fallback(token)) else font

    space = d.textlength(" ", font=font)
    words = caption.split()
    lines, cur, cur_w = [], [], 0.0
    for wtok in words:
        wtw = d.textlength(wtok, font=tf(wtok))
        add = wtw + (space if cur else 0)
        if cur and cur_w + add > max_w:
            lines.append(cur); cur, cur_w = [wtok], wtw
        else:
            cur.append(wtok); cur_w += add
    if cur:
        lines.append(cur)
    y = top_y
    for ln in lines:
        line_w = sum(d.textlength(w, font=tf(w)) for w in ln) + space * (len(ln) - 1)
        x = (W - line_w) / 2
        for w in ln:
            f_tok = tf(w)
            # Nudge the mono glyph down so it sits on the serif baseline.
            dy = int(line_h * 0.06) if f_tok is fb else 0
            d.text((x, y + dy), w, font=f_tok,
                   fill=accent if _is_highlight_token(w) else fg)
            x += d.textlength(w, font=f_tok) + space
        y += line_h
    return line_h * len(lines)


# The caption face (NotoSerif-Bold) has no math operators — they would draw as
# an empty "tofu" box. Verified against the bundled font's cmap 2026-07-28: it
# DOES have … ’ ‘ “ ” – — × ₹, which an earlier version was substituting away
# for no reason (curly quotes became straight, en-dashes became hyphens).
# DejaVuSansMono has all six operators, so captions render them from the mono
# face instead of degrading "promised ≠ withdrawn" into "promised != withdrawn"
# — which reads as code on an editorial slide.
_SERIF_MISSING = set("≠≈→←≤≥")

# Last-resort ASCII, only for single-font contexts that can't fall back per
# token (the kicker). Captions go through _draw_emph_block and keep the symbol.
_GLYPH_SUB = {
    "≈": "~", "≤": "<=", "≥": ">=", "≠": "!=", "→": "->", "←": "<-",
}


def _font_safe(text):
    for bad, good in _GLYPH_SUB.items():
        text = text.replace(bad, good)
    return text


def _needs_fallback(token):
    return any(c in _SERIF_MISSING for c in token)


def _render_frame(caption, dark, idx, total, kicker, out_png):
    # The caption keeps its symbols — _draw_emph_block falls back to the mono
    # face per token. The kicker is drawn with a single font, so it takes the
    # ASCII substitution.
    kicker = _font_safe(kicker or "")
    pal = PALETTE["dark" if dark else "light"]
    bg, fg, accent = pal["bg"], pal["fg"], pal["accent"]
    muted = (150, 138, 110) if dark else (150, 136, 104)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    pad_x = 96
    max_w = W - 2 * pad_x
    # top: THELIVU wordmark + a thin rule
    mark_f = _font(MONO_BOLD, 40)
    d.text((pad_x, 150), "THELIVU", font=mark_f, fill=accent)
    d.text((pad_x + d.textlength("THELIVU", font=mark_f) + 22, 158),
           "· reel", font=_font(MONO, 32), fill=fg)
    d.line([(pad_x, 235), (W - pad_x, 235)], fill=accent, width=3)

    # optional kicker: a small uppercase tag under the rule (story context)
    if kicker:
        kf = _font(MONO_BOLD, 34)
        d.text((pad_x, 270), kicker.upper(), font=kf, fill=muted)

    # centre band: the highlight, big serif, wrapped, emphasis on numbers/acronyms
    size = 122
    while size >= 60:
        f = _font(SERIF_BOLD, size)
        line_h = int(size * 1.14)
        # measure wrapped height by a dry run at this size
        words, cur, cur_w, nlines = caption.split(), [], 0.0, 0
        space = d.textlength(" ", font=f)
        fits = True
        for wtok in words:
            wtw = d.textlength(wtok, font=f)
            if wtw > max_w:
                fits = False; break
            add = wtw + (space if cur else 0)
            if cur and cur_w + add > max_w:
                nlines += 1; cur, cur_w = [wtok], wtw
            else:
                cur.append(wtok); cur_w += add
        if cur:
            nlines += 1
        if fits and line_h * nlines <= 920:
            break
        size -= 4
    f = _font(SERIF_BOLD, size)
    line_h = int(size * 1.14)
    # vertically centre the block
    tmp_words, tmp_cur, tmp_w, nlines = caption.split(), [], 0.0, 0
    space = d.textlength(" ", font=f)
    for wtok in tmp_words:
        add = d.textlength(wtok, font=f) + (space if tmp_cur else 0)
        if tmp_cur and tmp_w + add > max_w:
            nlines += 1; tmp_cur, tmp_w = [wtok], d.textlength(wtok, font=f)
        else:
            tmp_cur.append(wtok); tmp_w += add
    if tmp_cur:
        nlines += 1
    top_y = (H - line_h * nlines) // 2 - 40
    _draw_emph_block(d, caption, f, line_h, max_w, top_y, fg, accent, size=size)

    # bottom: thin progress bar (cleaner than dots) + source line
    bar_y = H - 300
    bar_w = W - 2 * pad_x
    d.line([(pad_x, bar_y), (pad_x + bar_w, bar_y)],
           fill=muted, width=3)
    if total > 1:
        filled = bar_w * (idx + 1) / total
        d.line([(pad_x, bar_y), (pad_x + filled, bar_y)], fill=accent, width=7)
    src = "thelivu.reports · sources in bio"
    sf = _font(MONO, 28)
    d.text(((W - d.textlength(src, font=sf)) / 2, bar_y + 34), src, font=sf, fill=muted)

    img.save(out_png)


# ── TTS ─────────────────────────────────────────────────────────────────────────
SILENT_BEAT_SECONDS = 2.8   # how long a no-speech beat (the sign-off card) holds


def _write_silence(wav_path, secs):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{secs:.2f}", str(wav_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _synth(text, wav_path, backend=None):
    """Synthesize one line to a wav via the configured backend. Returns seconds.
    `backend` overrides the module-level TTS_BACKEND (env is bound at import time,
    so a caller that only sets os.environ afterwards can't change it — passing it
    explicitly is how the dashboard forces 'chatterbox')."""
    # An empty beat is a deliberate SILENT hold, not a mistake: the sign-off card
    # is shown with no speech over it (the cloned voice can't say "തെളിവ്" and a
    # spliced real-voice read failed badly — reel #8 was pulled over it). Writing
    # the silence here keeps the frame/audio timing in one place.
    if not (text or "").strip():
        _write_silence(wav_path, SILENT_BEAT_SECONDS)
        return SILENT_BEAT_SECONDS
    backend = backend or TTS_BACKEND
    if backend == "chatterbox":
        _synth_chatterbox(text, wav_path)
    elif backend == "omnivoice":
        _synth_omnivoice(text, wav_path)
    else:
        _synth_piper(text, wav_path)
    return _duration(wav_path)


def _synth_chatterbox(text, wav_path):
    """POST to the Chatterbox voice server (Anil's cloned voice) → write a wav.
    Generation is ~5x realtime on CPU, so the timeout is generous."""
    import requests
    r = requests.post(f"{CHATTERBOX_URL}/synth", json={"text": text}, timeout=600)
    r.raise_for_status()
    Path(wav_path).write_bytes(r.content)


def _synth_piper(text, wav_path):
    subprocess.run(
        [PIPER_BIN, "--model", PIPER_VOICE, "--output_file", str(wav_path)],
        input=text.encode("utf-8"), check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _synth_omnivoice(text, wav_path):
    """POST to OmniVoice Studio's OpenAI-compatible sidecar → write a wav."""
    import requests
    r = requests.post(
        f"{OMNIVOICE_URL}/v1/audio/speech",
        json={"model": OMNIVOICE_MODEL, "voice": OMNIVOICE_VOICE,
              "input": text, "response_format": "wav"},
        timeout=120,
    )
    r.raise_for_status()
    Path(wav_path).write_bytes(r.content)


def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ── assembly ──────────────────────────────────────────────────────────────────
def build_reel(fields, dark, out_mp4, kicker=None, backend=None, render_frame=None):
    """Render frames + VO for each beat, animate with a gentle zoom, mux to MP4.
    `fields` is parse_script() output. `backend` overrides the module TTS_BACKEND
    for the voice (see _synth). `render_frame` overrides the frame renderer —
    `reel_illustrated.make_renderer()` passes the illustrated look; the default is
    the text-slide frame. Returns the out path."""
    draw_frame = render_frame or _render_frame
    beats = fields["beats"]
    if not beats:
        raise ValueError("no beats in script")
    if kicker is None:
        kicker = fields.get("kicker", "")
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="reel_"))
    try:
        seg_paths, wav_paths = [], []
        n = len(beats)
        for i, (spoken, caption) in enumerate(beats):
            png = work / f"f{i}.png"
            wav = work / f"a{i}.wav"
            draw_frame(caption, dark, i, n, kicker, png)
            dur = _synth(spoken, wav, backend) + GAP_SECS  # hold the frame through the gap too
            wav_paths.append((wav, dur))
            seg = work / f"s{i}.mp4"
            frames = max(int(round(dur * FPS)), 1)
            # gentle Ken-Burns zoom-in on the still (retention on a static frame)
            vf = (f"zoompan=z='min(zoom+0.0006,1.08)':d={frames}"
                  f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
                  f"format=yuv420p")
            subprocess.run(
                ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-t", f"{dur:.3f}",
                 "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 str(seg)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            seg_paths.append(seg)

        # concat video segments
        concat_list = work / "segs.txt"
        concat_list.write_text("".join(f"file '{s}'\n" for s in seg_paths))
        video = work / "video.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(video)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # build the VO track: each line's wav + a gap of silence, concatenated
        a_list = work / "aud.txt"
        silence = work / "gap.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=22050:cl=mono", "-t", f"{GAP_SECS:.3f}", str(silence)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        a_list.write_text("".join(f"file '{w}'\nfile '{silence}'\n" for w, _ in wav_paths))
        vo = work / "vo.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(a_list),
             str(vo)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # mux
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video), "-i", str(vo),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-movflags", "+faststart", str(out_mp4)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return str(out_mp4)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── carousel-to-video (the trending-audio workhorse) ────────────────────────────
def build_carousel_reel(image_paths, dark, out_mp4, secs_per=2.8):
    """Animate existing carousel slides into a 9:16 SILENT motion video, for posting
    in the IG app with a trending sound added there (the API can't attach library
    audio; see docs/reels-v1-build.md). Each 4:5 slide is centred on a 9:16 canvas
    in the slide's own bg colour with a gentle zoom, cut to the next. Silent by
    design — you add the sound at post time.

    A silent AAC track is muxed in anyway: some uploaders/players reject a
    video-only MP4, and IG replaces the audio when you pick a sound regardless."""
    if not image_paths:
        raise ValueError("no slide images")
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    bg = "0x171410" if dark else "0xE6DCC3"   # matches PALETTE ink / kraft
    y_off = (H - 1350) // 2                     # centre the 1080x1350 slide vertically
    work = Path(tempfile.mkdtemp(prefix="creel_"))
    try:
        seg_paths = []
        frames = max(int(round(secs_per * FPS)), 1)
        for i, img in enumerate(image_paths):
            seg = work / f"s{i}.mp4"
            # zoom within the slide, then pad to 9:16 with the slide's bg (static letterbox)
            vf = (f"scale=1080:1350,"
                  f"zoompan=z='min(zoom+0.0007,1.09)':d={frames}"
                  f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1350:fps={FPS},"
                  f"pad={W}:{H}:0:{y_off}:color={bg},format=yuv420p")
            subprocess.run(
                ["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-t", f"{secs_per:.3f}",
                 "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 str(seg)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            seg_paths.append(seg)

        concat_list = work / "segs.txt"
        concat_list.write_text("".join(f"file '{s}'\n" for s in seg_paths))
        video = work / "video.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(video)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        total = len(image_paths) * secs_per
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video),
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
             "-shortest", "-movflags", "+faststart", str(out_mp4)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return str(out_mp4)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", help="path to a video-script output file (narrated reel)")
    ap.add_argument("--carousel-slides", nargs="+", help="slide image paths (carousel reel)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--secs-per", type=float, default=2.8)
    a = ap.parse_args()
    if a.carousel_slides:
        path = build_carousel_reel(a.carousel_slides, a.dark, a.out, secs_per=a.secs_per)
        print("carousel reel:", path)
    elif a.script:
        fields = parse_script(Path(a.script).read_text())
        path = build_reel(fields, a.dark, a.out)
        print("narrated reel:", path)
    else:
        ap.error("give --script or --carousel-slides")
