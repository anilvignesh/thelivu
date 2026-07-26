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
_VOICE_LAUNCHER = "~/.jarvis/reel-voice.sh start"


def _voice_up():
    """True when the Chatterbox voice server answers /health with 200. Cheap probe
    so we fail fast with a helpful message instead of hanging 600s on a dead server
    deep inside build_reel's first _synth call."""
    import requests
    try:
        return requests.get(CHATTERBOX_HEALTH, timeout=3).status_code == 200
    except Exception:
        return False


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


def make_narrated_reel(run_id, *, dark=None, article_url=None, progress=None, mode=None):
    """Generate a narrated reel (Anil's cloned voice) for an approved run and store
    it. Returns a result dict — never raises for the expected failure modes so the
    dashboard can render a clean message:

      {ok:True,  reel_id, caption, beats, size_kb}
      {ok:False, needs_terminal:True, hint:<cmd>}      attended-only, run it in the terminal
      {ok:False, blocked:<reason>, until:<dt|None>}    api mode + quota breaker open
      {ok:False, voice_down:True, hint:<cmd>}          Chatterbox server not running
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

    # 2) Voice server — fail fast with the exact launcher command rather than hang.
    _p(0.02, "Checking the voice server…")
    if not _voice_up():
        return {"ok": False, "voice_down": True, "hint": _VOICE_LAUNCHER,
                "error": f"Chatterbox voice server is down — start it with `{_VOICE_LAUNCHER}`"}

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

    # 4) Render — local Chatterbox voice + ffmpeg. Force the chatterbox backend
    #    explicitly (the module TTS_BACKEND defaults to piper unless env-set).
    _p(0.35, f"Voicing {len(fields['beats'])} beats + rendering…")
    with tempfile.TemporaryDirectory(prefix="mkreel_") as tmp:
        out_mp4 = Path(tmp) / f"reel_run{run_id}.mp4"
        try:
            build_reel(fields, bool(dark), out_mp4, backend="chatterbox")
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
    caption = _build_caption(fields, article_url)
    reel_id = save_reel(run_id, mp4_bytes, caption, kind="narrated")

    _p(1.0, "Reel ready ✓")
    return {"ok": True, "reel_id": reel_id, "caption": caption,
            "beats": len(fields["beats"]), "size_kb": len(mp4_bytes) // 1024}
