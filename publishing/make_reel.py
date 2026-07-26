"""Build a narrated reel from an approved run — the glue the command-center
"🎬 Make reel" button calls.

This is the piece that was missing: `publishing.reel` can RENDER a reel from a
parsed video-script, and `shared.db.save_reel` / `publish.post_reel_run` can store
and post one — but nothing tied them together. Reel #2 was built by hand at the CLI.
This function is that orchestration, in ONE place both the dashboard and any future
caller share (same anti-drift rule as publish.py).

What it does NOT do: post. Rendering a reel is not a public action; posting is, and
that stays the gated tap (`post_reel_run`, from the dashboard's "Post reel" button,
which Anil clicks after previewing). Nothing here reaches Instagram.

Everything here runs LOCALLY on Anil's laptop: the video-script is a model call, the
voice is the local Chatterbox server (:3901), ffmpeg renders on CPU. Railway can't do
any of it (no GPU / no voice server) — so this is a local/attended step, and the
finished MP4 bytes are stored in the DB for the Railway fileserver to serve.
"""

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("make_reel")

CHATTERBOX_HEALTH = "http://127.0.0.1:3901/health"
_VOICE_SCRIPT = os.path.expanduser("~/.jarvis/reel-voice.sh")
_VOICE_LAUNCHER = "~/.jarvis/reel-voice.sh start"
# The launcher polls for readiness itself (24 x 5s); give it room to finish.
_VOICE_START_TIMEOUT = 180


def _voice_up():
    """True when the Chatterbox voice server answers /health with 200. Cheap probe
    so we fail fast with a helpful message instead of hanging 600s on a dead server
    deep inside build_reel's first _synth call."""
    import requests
    try:
        return requests.get(CHATTERBOX_HEALTH, timeout=3).status_code == 200
    except Exception:
        return False


def _ensure_voice(_p):
    """Make sure the voice server is answering, starting it if it isn't.

    The server is on-demand rather than boot-autostart because it holds ~2GB
    resident on a 14GB laptop — but that is a RAM decision, not a reason to make
    Anil go and start it by hand every time he asks for a reel. Triggering the
    build IS the intent to use the voice, so the build starts it.

    Returns (ok, error_message). The launcher blocks until /health answers, so a
    clean return means the model is loaded and ready. It is a no-op when the
    server is already up, and stays a clean error where the launcher doesn't
    exist (Railway never renders reels).
    """
    import subprocess

    if _voice_up():
        return True, None
    if not os.path.exists(_VOICE_SCRIPT):
        return False, f"voice launcher not found at {_VOICE_SCRIPT}"

    log.info("Voice server down — starting it")
    _p(0.03, "Starting the voice server (loads the model, ~10-20s)…")
    try:
        r = subprocess.run([_VOICE_SCRIPT, "start"], capture_output=True,
                           text=True, timeout=_VOICE_START_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"voice server did not start within {_VOICE_START_TIMEOUT}s"
    if _voice_up():
        log.info("Voice server ready")
        return True, None
    return False, ((r.stdout or "") + (r.stderr or "")).strip()[-400:] or \
        "voice server did not come up — check ~/.jarvis/chatterbox_server.log"


_NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NVIDIA_SCRIPT_MODEL = os.environ.get("NVIDIA_SCRIPT_MODEL", "google/gemma-4-31b-it")


def _gen_script_nvidia(draft, run_id=None):
    """Generate the video-script via NVIDIA-hosted Gemma 4 (free) instead of Claude.

    Charter-safe because the script is a POST-GATE step — it transforms an already
    verified + human-approved article, it does NOT touch the trust gate. So using a
    cheaper/free model here is a deliberate engine choice, not the silent-fallback the
    charter forbids. NVIDIA has its own key (NVIDIA_API_KEY), so this is independent of
    the Anthropic/Gemini quota breaker — the whole point: reels without Claude credit.
    Returns the raw script text (validated to contain a HOOK: line, one retry)."""
    import requests
    from shared.config import SKILLS_DIR
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY not set — cannot use nvidia reel mode")
    skill = (SKILLS_DIR / "video-script" / "SKILL.md").read_text(encoding="utf-8")
    system = ("You are a pipeline function, not a chat assistant. Output ONLY the "
              "structured script your instructions specify — no preamble, no commentary, "
              "no markdown fences.\n\n" + skill)

    def _call(extra=""):
        r = requests.post(
            _NVIDIA_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": _NVIDIA_SCRIPT_MODEL,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": draft + extra}],
                  "temperature": 0.5, "max_tokens": 1200},
            timeout=300,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    out = _call()
    if "HOOK:" not in out.upper():
        log.warning("nvidia video-script missing HOOK: — retrying once (run #%s)", run_id)
        out = _call("\n\n---\nYour previous reply lacked the required HOOK: line. Output "
                    "ONLY the structured script now, starting at TITLE:, no preamble.")
    # strip stray code fences some models wrap around the block
    return out.replace("```", "").strip()


def _build_caption(fields, article_url):
    """The IG description for the reel = the FULL narration (whole story, for muted
    viewers), then the sources link, then hashtags. Hashtags reuse the orchestrator's
    _build_hashtags so the brand/geo evergreen set + story tags are normalised and
    capped exactly as carousels do — no second implementation."""
    from engine.agents.orchestrator import _build_hashtags
    story_tags = [t for t in (fields.get("hashtags") or "").replace(",", " ").split() if t]
    bits = [fields.get("narration") or ""]
    if article_url:
        bits.append(f"Full story & sources: {article_url}")
    tags = _build_hashtags(story_tags)
    if tags:
        bits.append(tags)
    return "\n\n".join(b for b in bits if b)[:2200]


def _illustrate(fields, out_dir, _p):
    """One illustration per beat, or None if any beat failed.

    All-or-nothing on purpose: a reel with three illustrated frames and two text
    slides reads as a bug, not a style. The caller falls back to the text-slide
    look for the whole reel.
    """
    from publishing.illustrate import generate_beat_images, scene_from_beat
    from publishing.reel_illustrated import malayalam_fonts_available

    if not malayalam_fonts_available():
        log.warning("Malayalam fonts missing — the sign-off card can't render; "
                    "using text-slide frames")
        return None

    beats = fields["beats"]
    prompts = fields.get("images") or []
    scenes = []
    for i, (spoken, caption) in enumerate(beats):
        given = prompts[i].strip() if i < len(prompts) and prompts[i] else ""
        scenes.append(given or scene_from_beat(caption, spoken))

    def _step(i, total):
        _p(0.15 + 0.35 * (i / max(total, 1)), f"Illustrating beat {i + 1}/{total}…")

    images = generate_beat_images(scenes, out_dir, progress=_step)
    if any(p is None for p in images):
        missing = [i for i, p in enumerate(images) if p is None]
        log.warning("illustrations missing for beats %s — text-slide fallback", missing)
        return None
    return images


def make_narrated_reel(run_id, *, dark=None, article_url=None, progress=None,
                       mode=None, illustrated=True):
    """Generate a narrated reel (Anil's cloned voice) for an approved run and store
    it. Returns a result dict — never raises for the expected failure modes so the
    dashboard can render a clean message:

      {ok:True,  reel_id, caption, kind, beats, size_kb}
      {ok:False, needs_terminal:True, hint:<cmd>}      attended-only, run it in the terminal
      {ok:False, blocked:<reason>, until:<dt|None>}    api mode + quota breaker open
      {ok:False, voice_down:True, hint:<cmd>}          voice server wouldn't start
      {ok:False, error:<str>}                          anything else

    `mode` is "attended" (active) or "api" (kept but inactive) — defaults to
    config.REEL_MODE. In attended mode the video-script (a model step) is handed to
    the human-driven terminal session and NO API is used; it therefore only runs
    inside an attended process (`./attend reel <id>`), where the blocking wait is
    the compliance boundary. Called from the dashboard (a non-attended process) it
    returns needs_terminal with the exact command instead of ever touching the API.

    `progress(fraction, message)` is an optional UI callback (the dashboard passes one
    for its progress bar). `dark` picks the frame palette (reuse the carousel's mood);
    default light. Does NOT post — see module docstring.

    `illustrated` (default True) renders the ink-dark illustrated look: one
    conceptual FLUX illustration per beat plus the silent sign-off card. If any
    illustration fails it falls back to text-slide frames for the whole reel, so
    this never turns a working reel into a failed job.
    """
    from shared.db import get_run, save_reel
    from shared import quota
    from shared.config import REEL_MODE
    from engine.agents.skill_runner import attended_mode

    def _p(frac, msg):
        if progress:
            try:
                progress(frac, msg)
            except Exception:
                pass

    mode = (mode or REEL_MODE or "attended").strip().lower()
    attended = mode == "attended"
    nvidia = mode == "nvidia"

    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": f"run #{run_id} not found"}
    draft = run.get("draft_text") or ""
    if not draft:
        return {"ok": False, "error": f"run #{run_id} has no draft text to script from"}

    # 1) Route the model step (the video-script — a POST-GATE step; the article is
    #    already verified + human-approved, so which model writes the script never
    #    touches the trust gate).
    #  - nvidia mode: free hosted Gemma 4. Own key, no Anthropic/Gemini credit → the
    #    quota breaker doesn't apply; runs anywhere (dashboard included). No gate.
    #  - api mode (inactive by default): the script hits Claude → the quota breaker
    #    guards it; if open, don't hammer a dead API.
    #  - attended mode: no API at all; the script is a terminal handoff, which can
    #    only happen inside an attended process (the blocking wait is the compliance
    #    boundary). From the dashboard (non-attended) return the command, never the API.
    if nvidia:
        pass  # free engine, own key — no breaker, no attended requirement
    elif not attended:
        blocked = quota.is_blocked()
        if blocked:
            return {"ok": False, "blocked": blocked, "until": quota.blocked_until()}
    elif not attended_mode():
        return {"ok": False, "needs_terminal": True, "run_id": run_id,
                "hint": f"./attend reel {run_id}",
                "error": "Reels are attended-only right now — run it in the terminal "
                         f"with `./attend reel {run_id}`, then refresh to preview + post."}

    # 2) Voice server — start it if it's down. Asking for a reel is the intent to
    #    use the voice, so don't bounce the request back with a command to run.
    #    Only if it genuinely can't come up do we fail, and then with the reason.
    _p(0.02, "Checking the voice server…")
    ok, verr = _ensure_voice(_p)
    if not ok:
        return {"ok": False, "voice_down": True, "hint": _VOICE_LAUNCHER,
                "error": f"Chatterbox voice server could not be started: {verr}"}

    # 3) Script — video-script skill. run_structured_skill routes to the attended
    #    handoff automatically when THELIVU_ATTENDED=1 (the ./attend process), or to
    #    Claude in api mode. Either way the parsing/marker check is identical.
    _p(0.10, "Writing the reel script (free Gemma 4)…" if nvidia
             else "Writing the reel script…" if not attended
             else "Waiting for the script (attended handoff)…")
    from publishing.reel import parse_script, build_reel
    _M_SCRIPT = r"^HOOK:"  # the one line every valid video-script output must have
    try:
        if nvidia:
            script = _gen_script_nvidia(draft, run_id=run_id)
        else:
            from engine.agents.skill_runner import run_structured_skill
            script = run_structured_skill("video-script", draft, marker=_M_SCRIPT, run_id=run_id)
    except Exception as e:
        log.error("video-script failed for run #%s: %s", run_id, e)
        return {"ok": False, "error": f"script generation failed: {e}"}

    fields = parse_script(script)
    if not fields.get("beats"):
        return {"ok": False, "error": "video-script produced no usable beats"}
    # Captured before the silent sign-off beat is appended below.
    narration = fields.get("narration") or ""

    # 4) Illustrations — one conceptual image per beat (FLUX.1-dev on the free
    #    NVIDIA key). All-or-nothing: a reel that mixes illustrated and text-slide
    #    frames looks broken, so any missing image drops the WHOLE reel back to the
    #    text-slide look rather than shipping something half-styled.
    with tempfile.TemporaryDirectory(prefix="mkreel_") as tmp:
        tmpdir = Path(tmp)
        render_frame, kind, n_frames = None, "narrated", len(fields["beats"])
        if illustrated:
            _p(0.15, f"Illustrating {len(fields['beats'])} beats…")
            try:
                images = _illustrate(fields, tmpdir / "ill", _p)
            except Exception as e:
                log.warning("illustration step failed for run #%s: %s", run_id, e)
                images = None
            if images:
                from publishing.reel_illustrated import make_renderer
                render_frame = make_renderer(images)
                kind = "illustrated"
                # One extra beat with no spoken text = the silent sign-off hold.
                fields = dict(fields, beats=list(fields["beats"]) + [("", "")])
                n_frames = len(fields["beats"])
            else:
                log.info("run #%s: falling back to text-slide frames", run_id)

        # 5) Render — local Chatterbox voice + ffmpeg. Force the chatterbox backend
        #    explicitly (the module TTS_BACKEND defaults to piper unless env-set).
        _p(0.55 if illustrated else 0.35, f"Voicing {n_frames} beats + rendering…")
        out_mp4 = tmpdir / f"reel_run{run_id}.mp4"
        try:
            build_reel(fields, bool(dark), out_mp4, backend="chatterbox",
                       render_frame=render_frame)
        except Exception as e:
            log.error("build_reel failed for run #%s: %s", run_id, e)
            return {"ok": False, "error": f"reel render failed: {e}"}
        mp4_bytes = out_mp4.read_bytes()

    # 5) Caption + store. article_url falls back to the run's self-hosted page.
    _p(0.92, "Storing the reel…")
    if article_url is None:
        slug = run.get("slug")
        from shared.config import SLIDE_SERVER_BASE_URL
        article_url = (f"{SLIDE_SERVER_BASE_URL.rstrip('/')}/a/{slug}"
                       if slug and SLIDE_SERVER_BASE_URL else "")
    # The silent sign-off beat is not narration — keep it out of the description.
    caption = _build_caption(dict(fields, narration=narration), article_url)
    reel_id = save_reel(run_id, mp4_bytes, caption, kind=kind)

    _p(1.0, "Reel ready ✓")
    return {"ok": True, "reel_id": reel_id, "caption": caption, "kind": kind,
            "beats": n_frames, "size_kb": len(mp4_bytes) // 1024}
