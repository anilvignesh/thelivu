"""Make a piece's voice takes with the Chatterbox server (run where the server is: the Oracle reel-worker VM, localhost:3901).

    python3 synth_voice.py <piece dir> [voice]

Reads <piece>/voice/script.json and writes <piece>/voice/<id>.wav for every line that has no take yet (delete a wav to re-take
it). The voice is a clone of Anil's own recording, so it is only ever made on his machines. Stdlib only. Generation is slow on
CPU (about 20-45 s per line), so the timeout is generous.
"""
import json
import sys
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:3901/synth"
piece = Path(sys.argv[1]); voice = sys.argv[2] if len(sys.argv) > 2 else "anil"
for line in json.loads((piece / "voice" / "script.json").read_text())["lines"]:
    out = piece / "voice" / f"{line['id']}.wav"
    if out.exists():
        print("have", out.name); continue
    req = urllib.request.Request(URL, json.dumps({"text": line["text"], "voice": voice}).encode(), {"Content-Type": "application/json"})
    out.write_bytes(urllib.request.urlopen(req, timeout=900).read())
    print("made", out.name, out.stat().st_size)
