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


def draw_story_frame(image_path, caption, out_png, chapter_label=""):
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
    img.save(out_png)
    return out_png


def _ffmpeg(args, what):
    r = subprocess.run(["ffmpeg", "-y", "-nostdin", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{what} failed: {r.stderr[-400:]}")


def _segment(png, wav, out_mp4, duration, audio_start=0.0):
    """One still held over a slice of narration.

    No motion: a static frame held for twenty-odd seconds is what the
    illustration cadence already assumes, and every effect is another thing to
    break in a renderer that runs monthly.

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
             "-pix_fmt", "yuv420p", "-vf", f"scale={W}:{H}",
             "-af", "apad", "-ar", "44100", "-ac", "2",
             "-c:a", "aac", "-b:a", "160k",
             str(out_mp4)]
    _ffmpeg(args, f"segment {Path(png).name}")


# A chapter runs a minute or more. One illustration held that long is a still
# photograph with a voice-over, so the parser already collects 2-3 IMAGE lines
# per chapter; this is the cap on how many of them become shots.
MAX_SHOTS_PER_UNIT = 3
# Below this a shot is a flicker, not a shot — a short chapter stays on one frame.
MIN_SHOT_SECONDS = 12.0


def _shot_count(duration, available):
    """How many cuts a unit of `duration` seconds earns, given `available`
    illustrations. Long enough to need a second picture, or it keeps the first."""
    if available <= 1:
        return 1
    k = min(available, MAX_SHOTS_PER_UNIT, int(duration // MIN_SHOT_SECONDS))
    return max(1, k)


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

    # 2. Plan the shots against those real durations, then illustrate all of
    #    them in ONE batched call — generate_beat_images() warms up once and
    #    walks illustrate.prompt_ladder per scene, so a scene FLUX refuses costs
    #    a few rungs and comes back None rather than failing the render.
    plans = []          # per unit: [(scene_prompt, seconds)]
    for (key, chap, text), (_wav, dur, pauses) in zip(units, voiced):
        imgs = list((chap or {}).get("images") or [])
        if not imgs:
            one = (parsed.get("cold_open_image") if key == "cold_open"
                   else parsed.get("close_image") if key == "close" else None)
            imgs = [one] if one else []
        k = _shot_count(dur, len(imgs))
        parts = plan_cuts(dur, k, pauses)
        prompts = (imgs[:k] if imgs else [None] * k)
        plans.append(list(zip(prompts, parts)))

    _p(0.35, f"Illustrating {sum(len(pl) for pl in plans)} shots…")
    from publishing.illustrate import (STYLE, generate_beat_images,
                                       scene_from_beat)
    scenes = [pr or scene_from_beat("", units[i][2][:120])
              for i, pl in enumerate(plans) for pr, _sec in pl]
    arts = [None] * len(scenes)
    if illustrate:
        try:
            arts = generate_beat_images(scenes, tmp / "art",
                                        place=parsed.get("place"),
                                        ground=STYLE) or arts
        except Exception as e:
            log.warning("illustration batch failed (%s) — falling back to grounds", e)
            arts = [None] * len(scenes)

    # 3. Compose frames and assemble: chapter card, then the chapter's shots.
    _p(0.6, "Assembling…")
    from publishing.reel_illustrated import render_house_ground

    segs, marks, clock, n = [], [], 0.0, 0
    for i, ((key, chap, _t), (wav, _dur, _pauses)) in enumerate(zip(units, voiced)):
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
        for j, (_prompt, secs) in enumerate(plans[i]):
            art = arts[n] if n < len(arts) else None
            n += 1
            if not art:
                art = render_house_ground(str(tmp / f"ground_{i:03d}_{j}.png"),
                                          variant=(i + j) % 3)
            png = tmp / f"frame_{i:03d}_{j}.png"
            draw_story_frame(art, "", png,
                             chapter_label=(chap or {}).get("title", ""))
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
