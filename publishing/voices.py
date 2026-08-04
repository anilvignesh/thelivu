"""The reel voices: who can narrate, and with what settings.

Chatterbox clones from a reference wav handed to it on every call, so a voice is
just a file plus three dials — there is no per-voice model to load and no reason
a switch should cost a restart. This is the registry both the voice server and
the reel builder read.

Adding a voice is a wav and one entry in `~/.jarvis/voices.json`:

    {
      "default": "anil",
      "voices": {
        "anil": {"ref": "~/thelivu_voice_ref2.wav"},
        "fio":  {"ref": "~/thelivu_voice_fio.wav", "exaggeration": 0.4}
      }
    }

Anything the file omits falls back to the built-in defaults below, so a minimal
entry is `{"ref": "..."}`. The file is optional: with no file at all the built-in
registry is exactly the setup that existed before this module.

Why a file on the laptop rather than a repo constant: the wavs are a person's
recorded voice. They live on the machine that renders, they are not in git, and
which of them is in use is an operational choice, not a code change.
"""
import json
import os
from pathlib import Path

CONFIG = Path(os.path.expanduser(os.environ.get(
    "THELIVU_VOICES", "~/.jarvis/voices.json")))

# The settings Anil tuned by ear on the original clone; a voice that names none
# of them inherits these.
DEFAULT_SETTINGS = {"exaggeration": 0.45, "cfg_weight": 0.4, "temperature": 0.7}

# The built-in registry — what the engine knows without any config file.
BUILTIN = {
    "default": "anil",
    "voices": {"anil": {"ref": "~/thelivu_voice_ref2.wav"}},
}


def _load():
    if not CONFIG.exists():
        return dict(BUILTIN)
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        # A broken config must not take the voice server down: fall back to the
        # built-in and let /health report what is actually usable.
        return dict(BUILTIN)
    voices = dict(BUILTIN["voices"])
    voices.update(data.get("voices") or {})
    return {"default": data.get("default") or BUILTIN["default"], "voices": voices}


def registry():
    """{name: {ref, exaggeration, cfg_weight, temperature, available}}."""
    out = {}
    for name, spec in _load()["voices"].items():
        ref = os.path.expanduser(str(spec.get("ref", "")))
        out[name] = dict(DEFAULT_SETTINGS, **{k: v for k, v in spec.items() if k != "ref"},
                         ref=ref, available=bool(ref) and os.path.exists(ref))
    return out


def default_name():
    """The configured default. CBX_REF, if set, still wins for backward
    compatibility — that is how the server was driven before this existed."""
    return _load()["default"]


def resolve(name=None):
    """(name, settings) for a voice. Falls back to the default when `name` is
    empty or unknown, and raises only when nothing usable exists at all —
    a missing wav is an operational problem worth a clear message, not a
    silent switch to somebody else's voice."""
    reg = registry()
    want = (name or "").strip().lower() or default_name()
    if want not in reg:
        known = ", ".join(sorted(reg)) or "none"
        raise ValueError(f"unknown voice {want!r} — configured: {known}")
    spec = reg[want]
    if not spec["available"]:
        raise ValueError(f"voice {want!r} has no reference audio at {spec['ref']!r}")
    return want, spec


def available():
    return sorted(n for n, s in registry().items() if s["available"])
