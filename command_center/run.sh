#!/usr/bin/env bash
# Thelivu Command Center — launcher (autostart + manual).
# Pulls env from Railway each boot so it stays in sync, then serves on
# 0.0.0.0:8600 — laptop, home LAN, and the phone over Tailscale
# (100.70.158.55:8600). Logs: ~/.jarvis/thelivu-command-center.log

set -u
export PATH="$HOME/.railway/bin:$PATH"
LOG="$HOME/.jarvis/thelivu-command-center.log"
REPO="/home/jarvis/thelivu"
cd "$REPO" || { echo "$(date) repo not found" >> "$LOG"; exit 1; }

echo "=== $(date) starting thelivu command center ===" >> "$LOG"

# Wait for network + Railway to be reachable at boot (up to ~60s).
DBURL=""
for i in $(seq 1 12); do
  DBURL=$(railway variables --service Postgres --json 2>/dev/null \
          | python3 -c "import sys,json; print(json.load(sys.stdin).get('DATABASE_PUBLIC_URL',''))" 2>/dev/null)
  [ -n "$DBURL" ] && break
  sleep 5
done
if [ -z "$DBURL" ]; then
  echo "$(date) could not fetch DATABASE_PUBLIC_URL — is railway logged in / network up?" >> "$LOG"
  exit 1
fi

BOTV=$(railway variables --service thelivu --json 2>/dev/null)
getv() { echo "$BOTV" | python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

export DATABASE_URL="$DBURL"
export TELEGRAM_BOT_TOKEN="$(getv TELEGRAM_BOT_TOKEN)"
export TELEGRAM_CHANNEL_ID="$(getv TELEGRAM_CHANNEL_ID)"
export TELEGRAM_DRAFT_CHAT_ID="$(getv TELEGRAM_DRAFT_CHAT_ID)"
export SLIDE_SERVER_BASE_URL="$(getv SLIDE_SERVER_BASE_URL)"
export CONTACT_HANDLE="$(getv CONTACT_HANDLE)"
export IG_USER_ID="$(getv IG_USER_ID)"
export IG_ACCESS_TOKEN="$(getv IG_ACCESS_TOKEN)"
export NVIDIA_API_KEY="$(getv NVIDIA_API_KEY)"
export DASHBOARD_PASSWORD="thelivu"

# Don't double-launch if one is already serving 8600.
if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',8600))==0 else 1)"; then
  echo "$(date) port 8600 already in use — not launching a second instance" >> "$LOG"
  exit 0
fi

exec "$REPO/venv/bin/python" -m command_center.app >> "$LOG" 2>&1
