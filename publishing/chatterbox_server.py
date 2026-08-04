"""Chatterbox voice server — Anil's cloned voice for Thelivu reels.

Loads the Chatterbox Turbo (350M) model ONCE and serves POST /synth so
reel.py can voice a whole script without paying the model-load cost per line.
Runs LOCALLY in the ~/cbx venv (chatterbox-tts is installed there, not in the
thelivu venv) — Anil's laptop only; Railway can't run this. Local, free, CPU.

Voice = the cloned reference at CBX_REF, with the settings Anil picked
("B": exaggeration 0.45, cfg_weight 0.4, temperature 0.7 — 2026-07-24).

Run:  ~/cbx/bin/python -m publishing.chatterbox_server      (from ~/thelivu)
  or: cd ~/thelivu && ~/cbx/bin/python publishing/chatterbox_server.py
Health: GET /health -> {status, default, voices}
Synth:  POST /synth {"text": "...", "voice": "anil"} -> audio/wav
        `voice` is optional and names an entry in publishing/voices.py; omitted,
        the configured default narrates. Switching costs nothing — the model
        takes the reference wav on every call, so there is no reload.
"""
import io
import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch  # noqa: F401  (imported so a bad install fails loudly at startup)
import torchaudio as ta
from chatterbox.tts_turbo import ChatterboxTurboTTS

# The launcher (~/.jarvis/reel-voice.sh) starts this by FILE PATH, which puts
# publishing/ on sys.path rather than the repo root — so a plain
# `from publishing import ...` fails however sensible it looks. Fix it here
# rather than in the launcher: this file must work whichever way it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from publishing import voices  # noqa: E402

# CBX_REF still wins when set — that is how this server was driven before the
# registry existed, and a running setup should not change under anyone's feet.
# Otherwise the voice comes from the registry, per request.
REF = os.environ.get("CBX_REF", "")
EXAGGERATION = float(os.environ.get("CBX_EXAGGERATION", "0.45"))
CFG_WEIGHT = float(os.environ.get("CBX_CFG", "0.4"))
TEMPERATURE = float(os.environ.get("CBX_TEMPERATURE", "0.7"))
PORT = int(os.environ.get("CBX_PORT", "3901"))


def _voice(name):
    """(label, ref path, settings dict) for this request. The model takes the
    reference on every generate() call, so switching voices costs nothing and
    needs no restart."""
    if REF:
        return "CBX_REF", REF, {"exaggeration": EXAGGERATION,
                                "cfg_weight": CFG_WEIGHT,
                                "temperature": TEMPERATURE}
    label, spec = voices.resolve(name)
    return label, spec["ref"], {k: spec[k] for k in
                                ("exaggeration", "cfg_weight", "temperature")}

print(f"[chatterbox] loading Turbo (CPU)…  "
      f"{'ref=' + REF if REF else 'voices=' + ','.join(voices.available())}",
      flush=True)
_MODEL = ChatterboxTurboTTS.from_pretrained(device="cpu")
print(f"[chatterbox] ready on :{PORT}  (exag={EXAGGERATION} cfg={CFG_WEIGHT} temp={TEMPERATURE})", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # Report the voice actually loaded, not a hardcoded name — it said
            # "anil" regardless of CBX_REF, which would have been a lie the
            # moment a second voice existed.
            body = json.dumps({
                "status": "ok",
                "default": "CBX_REF" if REF else voices.default_name(),
                "voices": ["CBX_REF"] if REF else voices.available(),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/synth":
            self.send_response(404); self.end_headers(); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            text = (payload.get("text") or "").strip()
            if not text:
                raise ValueError("empty text")
            label, ref, settings = _voice(payload.get("voice"))
            wav = _MODEL.generate(text, audio_prompt_path=ref, **settings)
            buf = io.BytesIO()
            ta.save(buf, wav, _MODEL.sr, format="wav")
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001 — report the failure to the caller
            msg = str(e).encode()
            self.send_response(500)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
