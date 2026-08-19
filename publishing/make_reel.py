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
import re
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
# Switched off google/gemma-4-31b-it 2026-08-18 — found and verified the actual
# cause of 2026-08-17's stuck-reel incident: pinged it with a trivial 2-word
# reply and it took 17.8s, which is exactly why a full script generation kept
# blowing the 300s retry timeout under any real load. nemotron-3.5-lightning
# is a reasoning model (emits a long chain-of-thought before the answer, in a
# SEPARATE reasoning_content field once it actually finishes — see MAX_TOKENS
# below), verified end-to-end against this project's real skill + a real
# article before switching: clean, well-formed, on-spec output every time
# tested, ~45s total (vs. Gemma's unbounded/frequently-timing-out 300s+).
# Override via NVIDIA_SCRIPT_MODEL if this ever needs rolling back or swapping
# again — re-verify empirically before trusting a new one, the same way this
# one was checked (a model name alone doesn't tell you its real latency or
# whether its reasoning trace leaks into the content field under load).
_NVIDIA_SCRIPT_MODEL = os.environ.get("NVIDIA_SCRIPT_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
# Reasoning models spend real budget on reasoning_content before content even
# starts — verified 5000-5700 completion tokens of pure reasoning on a real
# script generation before the actual answer began. 1200 (the old Gemma
# budget) silently truncated mid-reasoning; this leaves real margin.
_NVIDIA_SCRIPT_MAX_TOKENS = int(os.environ.get("NVIDIA_SCRIPT_MAX_TOKENS", "10000"))

# The owner's revision notes from the remake box. Direction, NOT licence: the reel is a
# POST-GATE artefact, so nothing re-verifies it after he taps Post — a note that asks for
# a claim the article doesn't carry has to lose to the article. Stated here rather than
# trusted to the model's judgement, because "make the hook punchier" and "say they won the
# bill" arrive through the same textarea. (Reel #12 overstated a tabled Bill as passed;
# that was the generator compressing on its own. Notes must not reopen that door.)
_NOTES_HEADER = """
---
OWNER REVISION NOTES — the previous cut of this reel was reviewed and these changes were
asked for. Apply them to the script you write now:

{notes}

How to apply them: these notes direct emphasis, structure, pacing, tone, which beats to
keep or cut, and how lines are phrased. They do NOT change what the story establishes.
Your hard rules still govern and outrank every note: never upgrade a procedural status,
never add a claim, number or quote the article does not contain, never narrate the
editorial process. If a note asks for something the article does not support, follow the
article and write the closest accurate line instead.
"""


def _notes_block(notes):
    """The delimited revision-notes block appended to the script prompt, or "" when
    there are none — so an ordinary build sends the exact prompt it always did."""
    notes = (notes or "").strip()
    return _NOTES_HEADER.format(notes=notes) if notes else ""


# A reel lives or dies in its first three seconds, so the hook is the one structural
# element every path validates. Anchored to line-start so a stray "HOOK:" inside prose
# can't satisfy it, and it must carry actual words — `HOOK:` followed by nothing is the
# same failure as no HOOK at all. The gap is `[ \t]*`, NOT `\s*`: `\s` matches newlines,
# so `\s*\S` happily accepted a bare `HOOK:` line by reaching down to the text on the
# NEXT line — which is exactly the hookless script this check exists to reject.
_HOOK_RE = re.compile(r"^HOOK:[ \t]*\S", re.IGNORECASE | re.MULTILINE)


def _has_hook(script):
    return bool(_HOOK_RE.search(script or ""))


def _hook_line(script):
    m = re.search(r"^HOOK:[ \t]*(.+)$", script or "", re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


# Words that mark a stake without naming one: a contradiction, a reversal, a
# denial. Paired with digits and proper nouns below, these cover what a hook has
# to contain to be worth three seconds. Deliberately a HEURISTIC — it cannot
# judge whether a line is interesting, only whether it is empty of specifics.
_STAKE_WORDS = {"but", "not", "never", "no", "none", "instead", "while",
                "despite", "although", "though", "yet", "without", "failed",
                "refused", "denied", "says", "found", "ruled", "shows",
                "wrong", "cost", "spent", "lost", "took", "crore", "lakh",
                "crores", "lakhs", "million", "billion", "percent"}


def hook_is_sharp(hook):
    """Does the hook carry a specific — a number, a named thing, or a
    contradiction — rather than merely introducing the story?

    "Karnataka promised farmers a highway" passes every structural check the
    engine had and is still a setup line: it tells the viewer nothing is at
    stake, which is the only question the first three seconds answer. This looks
    for the marks a stake leaves behind. It is advisory, never a blocker: a
    genuinely sharp hook can carry none of these, and refusing to build a reel on
    a word-list would be worse than a flat opening. The prompts do the enforcing;
    this decides whether to spend a free retry and what to warn about.
    """
    words = (hook or "").split()
    if len(words) < 4:
        return False
    if any(ch.isdigit() for ch in hook):
        return True
    # A capitalised word that is not the first is a name, a place or an
    # institution — the hook is about something in particular.
    if any(w[:1].isupper() for w in words[1:] if w[:1].isalpha()):
        return True
    return bool({w.strip(".,;:—-").lower() for w in words} & _STAKE_WORDS)


def _gen_script_nvidia(draft, run_id=None):
    """Generate the video-script via a free NVIDIA-hosted model instead of Claude
    (currently nemotron-3.5-lightning-30b-a3b — see _NVIDIA_SCRIPT_MODEL above).

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

    def _post(extra):
        r = requests.post(
            _NVIDIA_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": _NVIDIA_SCRIPT_MODEL,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": draft + extra}],
                  "temperature": 0.5, "max_tokens": _NVIDIA_SCRIPT_MAX_TOKENS},
            timeout=300,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    def _call(extra=""):
        """One script attempt, transient failures retried — see shared/nvidia.py for
        why 5xx/timeouts are retried and 4xx is not. A single 500 used to abort the
        whole build before the voice or ffmpeg had done anything."""
        from shared.nvidia import call_with_retry
        return call_with_retry(lambda: _post(extra),
                               what=f"video-script via NVIDIA (run #{run_id})")

    out = _call()
    if not _has_hook(out):
        log.warning("nvidia video-script missing HOOK: — retrying once (run #%s)", run_id)
        out = _call("\n\n---\nYour previous reply lacked the required HOOK: line. The reel "
                    "MUST open on a hook — the sharpest fact or the stakes, in one "
                    "sentence, no throat-clearing. Output ONLY the structured script now, "
                    "starting at TITLE:, no preamble.")
    elif not hook_is_sharp(_hook_line(out)):
        # This engine is free, so a setup line costs one more call and nothing
        # else. Only once: if it comes back flat again, a flat hook still beats
        # burning the build.
        log.warning("nvidia video-script hook has no stake in it — retrying once "
                    "(run #%s): %r", run_id, _hook_line(out)[:80])
        out = _call("\n\n---\nYour HOOK line only introduces the story. A hook must carry "
                    "the stake in its own words — a number, a name, a loss, or a "
                    "contradiction — so someone who sees ONLY that line knows what is at "
                    "issue. 'Karnataka promised farmers a highway' is a setup line; "
                    "'Karnataka took farmers' land for a highway the High Court says was "
                    "never theirs to take' is a hook. Use only what the article "
                    "establishes. Output ONLY the structured script now, starting at "
                    "TITLE:, no preamble.")
    # strip stray code fences some models wrap around the block
    out = out.replace("```", "").strip()
    # Fail rather than ship a hookless script. The old code returned `out` regardless of
    # the retry's result: a second miss produced a script whose first line was BEAT 1, and
    # the reel opened mid-story with no hook at all. run_structured_skill raises in the
    # same situation; this path has to hold the same contract.
    if not _has_hook(out):
        raise RuntimeError("video-script produced no HOOK: line after a retry — refusing "
                           "to build a reel that opens without a hook")
    return out


def _build_caption(fields, article_url, music_credit=None):
    """The IG description for the reel = the FULL narration (whole story, for muted
    viewers), then the sources link, then hashtags. Hashtags reuse the orchestrator's
    _build_hashtags so the brand/geo evergreen set + story tags are normalised and
    capped exactly as carousels do — no second implementation.

    `music_credit` satisfies the CC BY attribution requirement on the background
    track actually mixed into THIS reel (publishing/music.py) — a caption line,
    not an on-screen watermark, same reasoning as the font licenses."""
    from engine.agents.orchestrator import _build_hashtags, _FOLLOW_CTA
    story_tags = [t for t in (fields.get("hashtags") or "").replace(",", " ").split() if t]
    bits = [fields.get("narration") or ""]
    if article_url:
        bits.append(f"Full story & sources: {article_url}")
    bits.append(_FOLLOW_CTA)
    tags = _build_hashtags(story_tags)
    if tags:
        bits.append(tags)
    if music_credit:
        bits.append(f"Music: {music_credit}")
    return "\n\n".join(b for b in bits if b)[:2200]


def _plan_shots(voiced):
    """How many sub-shots each beat gets, from its REAL synthesised duration.

    A beat is roughly 6-12s of speech (the script's 110-180 words over 5-7 beats
    makes that arithmetic unavoidable), so one picture per beat means one picture
    per ~9s. This plans 2-3 pictures for the long ones. The narration is untouched
    — only the number of images changes — so nothing here can affect what the reel
    SAYS.

    This used to estimate the duration from the word count at 147wpm, before the voice
    existed. It overshot on one beat of the first Assam reel and cut a 5.8s line into
    two 2.9s shots — the fastest cuts in that reel were an estimation error, not a
    choice. Voicing first costs nothing extra (build_reel reuses the wavs).
    """
    from publishing.reel import shots_for_duration
    # A silent beat (the sign-off hold) carries only GAP_SECS of "speech", so it falls
    # out as one card without needing a special case.
    return [shots_for_duration(dur) for _wav, dur, _pauses in voiced]


# Appended to a sub-shot's scene so the second picture is a different COMPOSITION of the
# same idea, not the same image re-rolled. Seed-only variation left two of six pairs
# near-identical on the first Assam build, and a cut to a near-identical image is the
# worst kind — it spends the viewer's attention and returns nothing. The IDEA is
# unchanged, so this cannot introduce a claim the beat does not make.
_SHOT_ANGLES = [
    "",
    " Compose this as a wide establishing view, the subject small within a large space.",
    " Compose this as a close detail of one part of the same subject.",
]


# How many beats of one reel may fall back to the house ground (see
# `reel_illustrated.render_house_ground`) before the illustrated look is abandoned
# for the whole reel.
#
# The old rule was zero: any refusal dropped everything to text slides, and reel #27
# lost its look to one refusal out of eight. The reasoning behind that rule is sound
# and survives here — a reel that mixes the illustrated look with the text-slide look
# reads as a bug. What changed is that the fallback for ONE beat is no longer the
# other look: it is a frame drawn in this one, so the reel stays visually whole.
#
# One, and not a fraction of the beats, because the argument only holds while the
# card is the exception. Two or three inked fields in a six-beat reel stop reading as
# a beat that chose texture and start reading as a reel that could not draw itself —
# and at that point the honest, consistent product is the text-slide reel, which is
# exactly what the old rule delivers. So the bar is raised rather than removed: every
# beat but one.
MAX_HOUSE_CARDS = 1


def _illustrate(fields, out_dir, _p, shots=None, presentation_style=None):
    """Illustrations per beat, or None if too many beats went unillustrated.

    Returns a list parallel to `beats`, each entry a LIST of paths — the sub-shots for
    that beat. Two things stand between a refusal and the text-slide fallback:

      * a beat that got SOME of its sub-shots keeps them (the renderer holds the last
        good one), because the substitute is then the beat's own art;
      * up to `MAX_HOUSE_CARDS` beats with no art at all get the house ground, a frame
        drawn in the same look rather than in the other one.

    Past that the caller falls back to text slides for the whole reel, unchanged.

    `presentation_style` looks up the FLUX ground prompt via
    STYLE_BY_PRESENTATION (publishing/illustrate.py) — the dark house style
    unless the style-bandit chose the 'bright' ground-tone experiment.
    """
    from publishing.illustrate import (generate_beat_images, scene_from_beat,
                                       STYLE, STYLE_BY_PRESENTATION)
    ground = STYLE_BY_PRESENTATION.get(presentation_style, STYLE)
    from publishing.reel_illustrated import (malayalam_fonts_available,
                                             render_house_ground)

    if not malayalam_fonts_available():
        log.warning("Malayalam fonts missing — the sign-off card can't render; "
                    "using text-slide frames")
        return None

    beats = fields["beats"]
    prompts = fields.get("images") or []
    shots = shots or [1] * len(beats)
    # Flatten to one scene per SUB-SHOT, remembering which beat each came from. Extra
    # sub-shots reuse the beat's own scene: the beat is one idea, and the variation
    # comes from the per-scene seed in generate_beat_images, so the second picture is
    # another view of the same concept rather than a new claim.
    scenes, owner = [], []
    for i, (spoken, caption) in enumerate(beats):
        given = prompts[i].strip() if i < len(prompts) and prompts[i] else ""
        scene = given or scene_from_beat(caption, spoken)
        k = max(int(shots[i]), 1)
        for j in range(k):
            # Only vary the framing when the beat is actually cut — a single-shot beat
            # keeps the scene exactly as the script wrote it.
            angle = _SHOT_ANGLES[j % len(_SHOT_ANGLES)] if k > 1 else ""
            scenes.append(scene + angle)
            owner.append(i)

    def _step(k, total):
        _p(0.15 + 0.35 * (k / max(total, 1)), f"Illustrating shot {k + 1}/{total}…")

    flat = generate_beat_images(scenes, out_dir, progress=_step,
                                place=fields.get("place"), ground=ground)

    grouped = [[] for _ in beats]
    for k, p in enumerate(flat):
        if p is not None:
            grouped[owner[k]].append(p)

    # A beat with no picture at all is the only one that needs rescuing. A beat that
    # lost one sub-shot of two still has its own art, and `make_renderer` holds it
    # across the cut.
    bare = [i for i, g in enumerate(grouped) if not g]
    partial = [i for i, g in enumerate(grouped)
               if g and len(g) < max(int(shots[i]), 1)]
    if partial:
        log.info("beats %s lost a sub-shot — holding the beat's own picture", partial)
    if len(bare) > MAX_HOUSE_CARDS:
        log.warning("no illustration for beats %s (max %d) — text-slide fallback",
                    bare, MAX_HOUSE_CARDS)
        return None
    for i in bare:
        card = out_dir / f"house_{i}.png"
        render_house_ground(card, variant=i, bright=(presentation_style == "bright"))
        grouped[i] = [card]
        log.warning("beat %d could not be illustrated — house ground, look kept", i)
    return grouped


def make_narrated_reel(run_id, *, dark=None, article_url=None, progress=None,
                       mode=None, illustrated=True, script=None, notes=None,
                       voice=None):
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
    conceptual FLUX illustration per beat plus the silent sign-off card. A beat the
    image model refuses falls back to the house ground — a frame in the same look —
    and only a reel with more than `MAX_HOUSE_CARDS` such beats drops to text-slide
    frames throughout, so this never turns a working reel into a failed job.

    `voice` names a registered reel voice (publishing/voices.py). Omitted, the
    engine's configured default narrates — the kv key `reel_voice` when set,
    otherwise the voice server's own default. The voice reaches only the audio:
    a reel's words, pictures and cut are identical whoever reads it, which is
    what makes an A/B between voices worth anything.

    `notes` is free text from the command centre's remake suggestion box — what to
    change about the cut he just watched ("hook is flat, open on the pellet round",
    "cut the fourth beat"). It shapes the script step only, is stored on the reel it
    produced, and cannot override the skill's hard rules (see `_NOTES_HEADER`).
    Ignored when an explicit `script=` is supplied — a hand-corrected script is
    already the final word, so there is nothing left to direct.
    """
    from shared.db import get_belief, get_run, save_reel
    from shared import quota
    from shared.config import REEL_MODE
    from engine.agents.skill_runner import attended_mode

    # Presentation-style bandit (2026-08-19) — picked HERE, before illustration,
    # so a 'bright' choice actually changes the FLUX ground tone rendered below,
    # not just a label attached after the fact. See engine/agents/style_learning.py.
    try:
        from engine.agents.style_learning import choose_style
        presentation_style = choose_style()
    except Exception:
        presentation_style = "static"

    def _p(frac, msg):
        if progress:
            try:
                progress(frac, msg)
            except Exception:
                pass

    if voice is None:
        from shared.db import kv_get
        voice = (kv_get("reel_voice") or "").strip() or None
    mode = (mode or REEL_MODE or "attended").strip().lower()
    attended = mode == "attended"
    nvidia = mode == "nvidia"

    run = get_run(run_id)
    if run is None:
        return {"ok": False, "error": f"run #{run_id} not found"}
    draft = run.get("draft_text") or ""
    if not draft:
        return {"ok": False, "error": f"run #{run_id} has no draft text to script from"}

    # A belief piece is scripted from its stored spine, not from the article: the
    # spine IS the narration the verifier passed and the reviewer read, so there
    # is no script step to run. See publishing/belief_reel.py.
    desk = (run.get("desk") or "news").lower()
    if voice is None and desk in ("ek", "gk"):
        # A second voice for the belief desks — Fio's, at her own suggestion
        # (2026-08-17) — so "Everyone Knows"/"Turns Out" reads as a distinct
        # series through audio rather than a second visual theme forking the
        # locked brand system (see BRAND.md; only bg/illustration are allowed
        # to vary by piece, never the signature). Only applies when nobody
        # already forced a voice via kv `reel_voice` (checked above) — that
        # manual override still wins, e.g. for an A/B test across desks.
        from publishing.voices import available
        if "fio" in available():
            voice = "fio"
    belief = get_belief(run_id) if desk in ("ek", "gk") else None
    spine = (belief or {}).get("spine") or ""
    if desk in ("ek", "gk") and not spine:
        return {"ok": False, "error": (
            f"run #{run_id} is a {desk} piece with no stored spine — it was written "
            "before the spine was split out. Run "
            "`python -m engine.desks.ek.backfill_drafts` and try again.")}
    # The shape-B view label rides on every frame of a contested-frame reel — the
    # viewer most likely to take an argued frame as a finding is the one watching
    # muted who never taps through, and the label is the only thing that reaches
    # them. Fixed wording, not the writer's sentence: a label that changes per
    # piece is not a label.
    from engine.desks.ek.draft import REEL_VIEW_LABEL
    view_label = REEL_VIEW_LABEL if (belief or {}).get("label") else ""

    # 1) Route the model step (the video-script — a POST-GATE step; the article is
    #    already verified + human-approved, so which model writes the script never
    #    touches the trust gate).
    #  - nvidia mode: free hosted model (currently Lightning). Own key, no Anthropic/Gemini credit → the
    #    quota breaker doesn't apply; runs anywhere (dashboard included). No gate.
    #  - api mode (inactive by default): the script hits Claude → the quota breaker
    #    guards it; if open, don't hammer a dead API.
    #  - attended mode: no API at all; the script is a terminal handoff, which can
    #    only happen inside an attended process (the blocking wait is the compliance
    #    boundary). From the dashboard (non-attended) return the command, never the API.
    if spine:
        pass  # no script step at all — the words are already written and verified
    elif nvidia:
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
    from publishing.reel import parse_script, build_reel, synth_beats
    # One hook check for every path: the same predicate the nvidia generator enforces is
    # handed to run_structured_skill as its marker (it accepts a callable), so api and
    # attended modes cannot drift to a weaker rule than the default mode.
    _M_SCRIPT = _has_hook
    if script:
        # A human-corrected script. The generator compresses, and compression is
        # where it overstates — reel #12 said the students "won a bill" that had
        # only been tabled. When a line has been fixed by hand, do not regenerate
        # it and hope; build exactly what was approved.
        _p(0.10, "Using the supplied script…")
        if not _has_hook(script):
            return {"ok": False, "error": "supplied script has no HOOK: line — the reel "
                                          "has to open on a hook"}
        if notes:
            log.info("run #%s: script supplied by hand — revision notes not applied "
                     "to it (they are stored with the reel)", run_id)
    elif spine:
        # The belief desks. Words copied from the spine; only the captions,
        # illustration scenes and hashtags are chosen, and a caption has to be a
        # faithful span of the line it sits under or it is replaced by one.
        _p(0.10, "Laying out the verified spine…")
        from publishing import belief_reel
        from publishing.parser import extract_headline
        from engine.desks.ek.draft import spine_lines
        lines = spine_lines(spine)
        if not lines:
            return {"ok": False, "error": f"run #{run_id}'s spine has no spoken lines"}
        headline = extract_headline(draft)
        captions, scenes, tags = belief_reel.dress_spine(
            lines, headline=headline, series=belief_reel.SERIES_KICKER.get(desk, ""))
        script = belief_reel.script_from_spine(
            lines, headline=headline, desk=desk,
            captions=captions, scenes=scenes, hashtags=tags)
        if notes:
            log.info("run #%s: belief reel — revision notes do not reach the "
                     "narration (it is the verified spine); stored with the reel", run_id)
    else:
        _p(0.10, "Rewriting the reel script to your notes…" if notes
                 else "Writing the reel script (free NVIDIA model)…" if nvidia
                 else "Writing the reel script…" if not attended
                 else "Waiting for the script (attended handoff)…")
        # ONE prompt for both engines — the notes must not be able to reach Gemma but
        # not Claude (or vice versa) depending on which mode is active.
        script_input = draft + _notes_block(notes)
        try:
            if nvidia:
                script = _gen_script_nvidia(script_input, run_id=run_id)
            else:
                from engine.agents.skill_runner import run_structured_skill
                script = run_structured_skill("video-script", script_input,
                                              marker=_M_SCRIPT, run_id=run_id)
        except Exception as e:
            log.error("video-script failed for run #%s: %s", run_id, e)
            return {"ok": False, "error": f"script generation failed: {e}"}

    fields = parse_script(script)
    if not fields.get("beats"):
        return {"ok": False, "error": "video-script produced no usable beats"}
    # Belt and braces on the thing that decides whether anyone watches: the generators
    # validate their raw output, but only the parser knows what actually became beat one.
    # A HOOK line the parser couldn't read is the same product as no hook.
    if not fields.get("hook"):
        return {"ok": False, "error": "the script's HOOK line did not parse — a reel has "
                                      "to open on a hook, so nothing was rendered"}
    # The belief desks' one hard rule at this stage: what the voice says must still
    # be the spine the verifier passed. Checked AFTER parsing, so it covers a spine
    # mangled by the script format and a hand-corrected script whose words drifted.
    # Captions, pictures and hashtags are free; the words are not.
    if spine:
        from publishing import belief_reel
        from engine.desks.ek.draft import spine_lines
        if not belief_reel.spoken_matches_spine(script, spine_lines(spine)):
            return {"ok": False, "error": (
                "the script's spoken lines are not the verified spine — a belief reel "
                "may not say anything the trust gate did not pass. Edit the piece and "
                "re-run the desk if the narration needs to change.")}
    # One sharpness check for every path, after parsing, so what is judged is what
    # actually became beat one. Advisory by design — see hook_is_sharp. Where the
    # words can still be regenerated the generators have already spent their retry;
    # on the belief desks they cannot be (the spine is post-gate), so this is the
    # only signal there is, and it names the fix: the hook comes from the writer.
    if not hook_is_sharp(fields.get("hook") or ""):
        log.warning("run #%s: the hook carries no stake — %r%s", run_id,
                    (fields.get("hook") or "")[:90],
                    " (belief desk: sharpen the spine's first line and re-run the "
                    "desk; the reel may not rewrite it)" if spine else "")

    # Captured before the silent sign-off beat is appended below.
    narration = fields.get("narration") or ""

    # 4) Illustrations — one conceptual image per beat (FLUX.1-dev on the free
    #    NVIDIA key). A reel that mixes the illustrated and text-slide looks still
    #    reads as broken, so that mix is never shipped: a refused beat gets a frame
    #    drawn in the illustrated look instead (the house ground), and only when more
    #    than MAX_HOUSE_CARDS beats go unillustrated does the WHOLE reel drop back to
    #    text slides. See `_illustrate`.
    with tempfile.TemporaryDirectory(prefix="mkreel_") as tmp:
        tmpdir = Path(tmp)
        render_frame, kind, n_frames = None, "narrated", len(fields["beats"])
        shots_per_beat = None

        # 4) Voice FIRST. The shot plan needs each beat's real duration (a word-count
        #    estimate over-cut a 5.8s beat into two 2.9s shots) and its real pause
        #    positions (so a cut lands on a breath, not mid-clause). build_reel is
        #    handed these wavs, so the slowest step still runs exactly once.
        _p(0.12, f"Voicing {len(fields['beats'])} beats"
                 + (f" as {voice}…" if voice else "…"))
        try:
            voiced = synth_beats(fields["beats"], "chatterbox", tmpdir / "vo",
                                 voice=voice)
        except Exception as e:
            log.error("voicing failed for run #%s: %s", run_id, e)
            return {"ok": False, "error": f"voicing failed: {e}"}

        if illustrated:
            shots_per_beat = _plan_shots(voiced)
            n_shots = sum(shots_per_beat)
            log.info("run #%s: beats %s -> shots %s (%d images)", run_id,
                     [round(d, 1) for _w, d, _p2 in voiced], shots_per_beat, n_shots)
            _p(0.25, f"Illustrating {n_shots} shots across {len(shots_per_beat)} beats…")
            try:
                images = _illustrate(fields, tmpdir / "ill", _p, shots=shots_per_beat,
                                     presentation_style=presentation_style)
            except Exception as e:
                log.warning("illustration step failed for run #%s: %s", run_id, e)
                images = None
            if images:
                from publishing.reel_illustrated import make_renderer
                render_frame = make_renderer(images)
                kind = "illustrated"
                # Cut each beat to the pictures it actually HAS. Planning 2 shots for
                # a beat that came back with 1 makes the renderer hold the same frame
                # across a cut, which restarts the zoom on an identical picture — the
                # visible stutter the sub-shot work exists to avoid.
                shots_per_beat = [max(len(g), 1) for g in images]
                # One extra beat with no spoken text = the silent sign-off hold. It is
                # a single card, never cut, so it contributes one shot.
                fields = dict(fields, beats=list(fields["beats"]) + [("", "")])
                shots_per_beat = list(shots_per_beat) + [1]
                n_frames = len(fields["beats"])
            else:
                log.info("run #%s: falling back to text-slide frames", run_id)
                # The text-slide look has nothing to vary per sub-shot, so a split
                # would just restart the zoom on an identical frame — a visible
                # stutter. Fall back to one shot per beat along with the look.
                shots_per_beat = None

        # 5) Render — ffmpeg over the already-voiced beats. The backend is still passed
        #    because the appended sign-off beat has no pre-voiced wav: it is empty
        #    spoken text, which `_synth` turns into the deliberate silent hold.
        _p(0.55 if illustrated else 0.35, f"Rendering {n_frames} frames…")
        out_mp4 = tmpdir / f"reel_run{run_id}.mp4"
        # Pick the music bed ONCE here (not inside build_reel) so the caption's
        # attribution line below names the exact track that got mixed in.
        try:
            from publishing.music import pick_track
            music_choice = pick_track()
        except Exception:
            music_choice = None
        try:
            build_reel(fields, bool(dark), out_mp4, backend="chatterbox",
                       render_frame=render_frame, shots_per_beat=shots_per_beat,
                       voiced=voiced, label=view_label, voice=voice,
                       music_track=(music_choice["path"] if music_choice else None),
                       presentation_style=presentation_style)
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
    caption = _build_caption(dict(fields, narration=narration), article_url,
                             music_credit=(music_choice["credit"] if music_choice else None))
    # presentation_style was picked before illustration (top of this function) so
    # it could actually drive the FLUX ground tone — reused here, not re-picked,
    # so the tag on the reel always matches what it was actually rendered with.
    reel_id = save_reel(run_id, mp4_bytes, caption, kind=kind,
                        notes=(notes or "").strip() or None,
                        presentation_style=presentation_style)

    _p(1.0, "Reel ready ✓")
    return {"ok": True, "reel_id": reel_id, "caption": caption, "kind": kind,
            "beats": n_frames, "size_kb": len(mp4_bytes) // 1024,
            "notes": (notes or "").strip() or None}
