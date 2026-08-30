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
# Added 2026-08-30 for the Cloudflare Workers AI illustration fallback
# (publishing/illustrate.py) -- both optional, same as Telegram below: the
# fallback just stays inactive without them, nothing else breaks.
cf_token = app.get("CLOUDFLARE_API_TOKEN", "")
cf_account = app.get("CLOUDFLARE_ACCOUNT_ID", "")

missing = [n for n, v in [("DATABASE_PUBLIC_URL", db_url),
                          ("NVIDIA_API_KEY", nvidia_key)] if not v]
if missing:
    sys.exit(f"missing required Railway vars: {missing}")
# Telegram push is optional (reel_worker logs + skips if absent) — warn, don't fail.
if not (tg_token and tg_chat):
    print("NOTE: TELEGRAM_BOT_TOKEN/TELEGRAM_DRAFT_CHAT_ID not found — reels will "
          "build fine but won't be pushed to Telegram for review", file=sys.stderr)
if not (cf_token and cf_account):
    print("NOTE: CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID not found — the "
          "Cloudflare illustration fallback stays inactive, FLUX-only", file=sys.stderr)

with open(out_path, "w") as f:
    f.write(f"DATABASE_URL={db_url}\n")
    f.write(f"NVIDIA_API_KEY={nvidia_key}\n")
    f.write(f"SLIDE_SERVER_BASE_URL={base_url}\n")
    f.write(f"TELEGRAM_BOT_TOKEN={tg_token}\n")
    f.write(f"TELEGRAM_DRAFT_CHAT_ID={tg_chat}\n")
    if cf_token:
        f.write(f"CLOUDFLARE_API_TOKEN={cf_token}\n")
    if cf_account:
        f.write(f"CLOUDFLARE_ACCOUNT_ID={cf_account}\n")
print("wrote vars: DATABASE_URL, NVIDIA_API_KEY, SLIDE_SERVER_BASE_URL, "
      "TELEGRAM_BOT_TOKEN, TELEGRAM_DRAFT_CHAT_ID" +
      (", CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID" if cf_token else ""))
PYEOF

# Diff against what's already there before touching anything — this script
# now also runs on a schedule (2026-08-30), not just once at provisioning
# time, and an unconditional restart every run would reload the TTS model
# and interrupt an in-flight render for zero reason on the common case
# (nothing in Railway actually changed since the last run).
REMOTE_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV" "$REMOTE_ENV"' EXIT
$SSH "cat /home/ubuntu/thelivu/ops/oracle-vm/reel-worker.env 2>/dev/null" > "$REMOTE_ENV" || true

if diff -q "$TMP_ENV" "$REMOTE_ENV" >/dev/null 2>&1; then
  echo "== no change from what's already on the VM — skipping copy + restart =="
  SECRETS_CHANGED=0
else
  echo "== copying env file to VM (chmod 600 there) =="
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new "$TMP_ENV" \
    ubuntu@"$VM_IP":/home/ubuntu/thelivu/ops/oracle-vm/reel-worker.env
  $SSH "chmod 600 /home/ubuntu/thelivu/ops/oracle-vm/reel-worker.env"
  SECRETS_CHANGED=1
fi

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

echo "== enabling services (first run) =="
$SSH "sudo systemctl enable chatterbox reel-worker"

# Only restart when the secrets actually changed, or the services aren't
# running yet (first provisioning) -- `enable --now`/`restart` reload the TTS
# model and can interrupt an in-flight render, real costs to pay on every one
# of this script's now-scheduled runs for no reason on the common no-op case.
NEEDS_RESTART=0
if [ "${SECRETS_CHANGED:-0}" = "1" ]; then
  echo "== secrets changed -- restart required =="
  NEEDS_RESTART=1
elif ! $SSH "sudo systemctl is-active --quiet chatterbox reel-worker"; then
  echo "== services not both running yet -- starting =="
  NEEDS_RESTART=1
fi

if [ "$NEEDS_RESTART" = "1" ]; then
  $SSH "sudo systemctl restart chatterbox reel-worker && sleep 3 && sudo systemctl status chatterbox reel-worker --no-pager -l | head -40"
else
  echo "== nothing changed and both services already running -- not restarting =="
fi

echo "== done. Tail logs with: =="
echo "  ssh -i $KEY ubuntu@$VM_IP 'journalctl -u chatterbox -u reel-worker -f'"
