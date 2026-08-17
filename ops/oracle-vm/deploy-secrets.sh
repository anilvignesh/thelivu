#!/usr/bin/env bash
# Run FROM THE LAPTOP (not the VM) — this machine already has an authenticated
# `railway` CLI (command_center/run.sh uses the same pattern), so secrets are
# pulled here and pushed over SSH rather than making the VM authenticate to
# Railway itself (one less credential on a box sitting on the open internet).
#
# Usage: ops/oracle-vm/deploy-secrets.sh <VM_PUBLIC_IP>
set -euo pipefail

VM_IP="${1:?usage: deploy-secrets.sh <VM_PUBLIC_IP>}"
KEY="$HOME/.ssh/thelivu_oracle"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new ubuntu@$VM_IP"
export PATH="$HOME/.railway/bin:$PATH"

TMP_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV"' EXIT
chmod 600 "$TMP_ENV"

echo "== pulling vars from Railway (values never printed) =="
python3 - "$TMP_ENV" <<'PYEOF'
import json, subprocess, sys

out_path = sys.argv[1]
pg = json.loads(subprocess.check_output(
    ["railway", "variables", "--service", "Postgres", "--json"]))
app = json.loads(subprocess.check_output(
    ["railway", "variables", "--service", "thelivu", "--json"]))

db_url = pg.get("DATABASE_PUBLIC_URL", "")
nvidia_key = app.get("NVIDIA_API_KEY", "")
base_url = app.get("SLIDE_SERVER_BASE_URL", "")
tg_token = app.get("TELEGRAM_BOT_TOKEN", "")
tg_chat = app.get("TELEGRAM_DRAFT_CHAT_ID", "")

missing = [n for n, v in [("DATABASE_PUBLIC_URL", db_url),
                          ("NVIDIA_API_KEY", nvidia_key)] if not v]
if missing:
    sys.exit(f"missing required Railway vars: {missing}")
# Telegram push is optional (reel_worker logs + skips if absent) — warn, don't fail.
if not (tg_token and tg_chat):
    print("NOTE: TELEGRAM_BOT_TOKEN/TELEGRAM_DRAFT_CHAT_ID not found — reels will "
          "build fine but won't be pushed to Telegram for review", file=sys.stderr)

with open(out_path, "w") as f:
    f.write(f"DATABASE_URL={db_url}\n")
    f.write(f"NVIDIA_API_KEY={nvidia_key}\n")
    f.write(f"SLIDE_SERVER_BASE_URL={base_url}\n")
    f.write(f"TELEGRAM_BOT_TOKEN={tg_token}\n")
    f.write(f"TELEGRAM_DRAFT_CHAT_ID={tg_chat}\n")
print("wrote 5 vars (DATABASE_URL, NVIDIA_API_KEY, SLIDE_SERVER_BASE_URL, "
      "TELEGRAM_BOT_TOKEN, TELEGRAM_DRAFT_CHAT_ID)")
PYEOF

echo "== copying env file to VM (chmod 600 there) =="
scp -i "$KEY" -o StrictHostKeyChecking=accept-new "$TMP_ENV" \
  ubuntu@"$VM_IP":/home/ubuntu/thelivu/ops/oracle-vm/reel-worker.env
$SSH "chmod 600 /home/ubuntu/thelivu/ops/oracle-vm/reel-worker.env"

echo "== copying voice reference clips =="
if [ -f "$HOME/thelivu_voice_ref2.wav" ]; then
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new \
    "$HOME/thelivu_voice_ref2.wav" ubuntu@"$VM_IP":/home/ubuntu/thelivu_voice_ref2.wav
else
  echo "WARNING: $HOME/thelivu_voice_ref2.wav not found locally — copy it manually before starting chatterbox.service"
fi
# Second voice for the belief desks (publishing/voices.py), added 2026-08-17.
# Optional — a fresh VM with just Anil's wav still works, it just narrates
# ek/gk reels in the news-desk voice until this exists (see make_reel.py).
if [ -f "$HOME/thelivu_voice_fio.wav" ]; then
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new \
    "$HOME/thelivu_voice_fio.wav" ubuntu@"$VM_IP":/home/ubuntu/thelivu_voice_fio.wav
  $SSH "mkdir -p ~/.jarvis && cat > ~/.jarvis/voices.json" <<'JSON'
{
  "default": "anil",
  "voices": {
    "anil": {"ref": "~/thelivu_voice_ref2.wav"},
    "fio":  {"ref": "~/thelivu_voice_fio.wav"}
  }
}
JSON
else
  echo "NOTE: $HOME/thelivu_voice_fio.wav not found locally — belief-desk reels will narrate as Anil until it's added and this script re-run."
fi

echo "== enabling + starting services =="
$SSH "sudo systemctl enable --now chatterbox reel-worker && sleep 3 && sudo systemctl status chatterbox reel-worker --no-pager -l | head -40"

echo "== done. Tail logs with: =="
echo "  ssh -i $KEY ubuntu@$VM_IP 'journalctl -u chatterbox -u reel-worker -f'"
