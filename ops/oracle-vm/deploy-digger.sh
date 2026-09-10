#!/usr/bin/env bash
# Run FROM THE LAPTOP (not the VM) — same reasoning as deploy-secrets.sh: this
# machine already has an authenticated `railway` CLI, so DATABASE_URL is pulled
# here and pushed over SSH rather than making the VM authenticate to Railway
# itself (one less credential on a box sitting on the open internet).
#
# The freellmapi key is NOT pulled from Railway — it lives only on the digger VM,
# inside the freellmapi container's own settings table, and is read out there.
#
# Layout is dictated by SELinux, which is Enforcing on this box (2026-09-10):
#   /opt/thelivu            code + venv   (usr_t — systemd may execute it)
#   /etc/thelivu/digger.env secrets       (root:root 600, readable by systemd)
# Putting either under /home/opc fails the unit with a bare "Permission denied",
# because systemd runs as init_t and cannot touch user_home_t.
#
# Usage: ops/oracle-vm/deploy-digger.sh [VM_PUBLIC_IP]
set -euo pipefail

VM_IP="${1:-129.225.67.115}"
KEY="$HOME/.ssh/thelivu_digger"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new opc@$VM_IP"
APP_DIR="/opt/thelivu"
ETC_DIR="/etc/thelivu"
PY311=/usr/bin/python3.11
export PATH="$HOME/.railway/bin:$PATH"

TMP_ENV="$(mktemp)"
REMOTE_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV" "$REMOTE_ENV"' EXIT
chmod 600 "$TMP_ENV"

echo "== pulling DATABASE_URL from Railway (value never printed) =="
python3 - "$TMP_ENV" <<'PYEOF'
import json, subprocess, sys
out_path = sys.argv[1]
pg = json.loads(subprocess.check_output(
    ["railway", "variables", "--service", "Postgres", "--json"]))
db_url = pg.get("DATABASE_PUBLIC_URL", "")
if not db_url:
    sys.exit("missing required Railway var: DATABASE_PUBLIC_URL")
with open(out_path, "w") as f:
    f.write(f"DATABASE_URL={db_url}\n")
print("wrote var: DATABASE_URL")
PYEOF

# Read the unified key via a SCRIPT FILE on the VM, never inline nested quoting.
# An inline `ssh '... "... '"'"'...'"'"' ..." '` mangled the value into 78
# characters instead of 59 and produced a silent HTTP 401 (2026-09-10). Quoting
# through ssh -> sh -> docker -> sqlite is four levels deep; a heredoc'd script
# is the only version that survives it.
echo "== reading freellmapi unified key off the VM =="
$SSH 'cat > /tmp/readkey.sh' <<'REMOTE'
#!/bin/bash
set -euo pipefail
docker run --rm -v freellmapi_freellmapi-data:/data alpine sh -c \
  'apk add --no-cache sqlite >/dev/null 2>&1; sqlite3 /data/freeapi.db "SELECT value FROM settings WHERE key = '"'"'unified_api_key'"'"';"'
REMOTE
$SSH 'chmod +x /tmp/readkey.sh'
FREE_KEY="$($SSH '/tmp/readkey.sh' | tr -d '\r\n')"
$SSH 'rm -f /tmp/readkey.sh'

# freellmapi mints these as "freellmapi-" + 48 hex = 59 chars. Validate the
# SHAPE rather than trusting the pipeline — a mangled key only shows up later as
# a 401 from a service that otherwise looks healthy.
if ! printf '%s' "$FREE_KEY" | grep -Eq '^freellmapi-[0-9a-f]{48}$'; then
  echo "ERROR: unified_api_key looks malformed (length ${#FREE_KEY}); expected" >&2
  echo "       'freellmapi-' + 48 hex chars. Is the freellmapi container up?" >&2
  exit 1
fi
printf 'FREELLMAPI_KEY=%s\n' "$FREE_KEY" >> "$TMP_ENV"

cat >> "$TMP_ENV" <<'EOF'
FREELLMAPI_BASE_URL=http://127.0.0.1:3001
DIGGER_CYCLE_SECONDS=3600
DIGGER_MAX_DOCS=1
EOF

echo "== syncing code to $APP_DIR =="
$SSH "sudo mkdir -p $APP_DIR && sudo chown opc:opc $APP_DIR"
rsync -az --delete \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude '.git' --exclude 'venv' --exclude '__pycache__' \
  --exclude '*.pyc' --exclude 'articles' --exclude 'thelivu.db' \
  --exclude 'branding' --exclude 'docs/plans/reel-prototype' \
  "$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)/" \
  opc@"$VM_IP":"$APP_DIR/"

echo "== ensuring venv =="
# python3.11 explicitly, NOT `python3`: Oracle Linux 8 ships 3.6.8, which has no
# psycopg2-binary wheel and falls back to a source build that fails outright
# (hit 2026-09-10). python3.11 comes from ol8_appstream.
$SSH "test -x $PY311" || {
  echo "ERROR: $PY311 missing on the VM. Install with:" >&2
  echo "  sudo dnf install -y --disablerepo='*' --enablerepo='ol8_baseos_latest,ol8_appstream' --setopt=install_weak_deps=False python3.11 python3.11-pip" >&2
  exit 1
}
$SSH "test -x $APP_DIR/venv/bin/python || $PY311 -m venv $APP_DIR/venv"
# Deliberately NOT requirements.txt: that pulls anthropic/openai/Pillow/lxml and
# a compiler toolchain onto a 945MB box for a service that needs neither. The
# digger is stdlib-only apart from the Postgres driver.
$SSH "$APP_DIR/venv/bin/pip install --quiet --upgrade pip 'psycopg2-binary>=2.9'"

# Diff before touching anything — same reasoning as deploy-secrets.sh: this is
# safe to re-run, and an unconditional restart interrupts an in-flight cycle for
# no reason on the common case where nothing changed.
$SSH "sudo cat $ETC_DIR/digger.env 2>/dev/null" > "$REMOTE_ENV" || true
if diff -q "$TMP_ENV" "$REMOTE_ENV" >/dev/null 2>&1; then
  echo "== env unchanged =="
  SECRETS_CHANGED=0
else
  echo "== installing env file to $ETC_DIR (root:root 600) =="
  scp -i "$KEY" -o StrictHostKeyChecking=accept-new "$TMP_ENV" \
    opc@"$VM_IP":/tmp/digger.env.new
  $SSH "sudo mkdir -p $ETC_DIR && sudo mv /tmp/digger.env.new $ETC_DIR/digger.env && \
        sudo chown root:root $ETC_DIR/digger.env && sudo chmod 600 $ETC_DIR/digger.env && \
        sudo restorecon -F $ETC_DIR/digger.env"
  SECRETS_CHANGED=1
fi

echo "== installing systemd unit =="
$SSH "sudo cp $APP_DIR/ops/oracle-vm/digger.service /etc/systemd/system/digger.service && \
      sudo restorecon -F /etc/systemd/system/digger.service && \
      sudo systemctl daemon-reload && sudo systemctl enable digger"

# Smoke test BEFORE restarting. `--once` returns non-zero only on a hard error,
# so also require that the run reported no cycle failure: a cycle that fails is
# caught and logged by design, and letting that pass for a deploy would ship a
# broken service that merely looks calm in the logs.
echo "== smoke test: one dry-run cycle, no DB writes =="
SMOKE="$($SSH "cd $APP_DIR && sudo -E env \$(sudo cat $ETC_DIR/digger.env | xargs) \
  $APP_DIR/venv/bin/python -m engine.digger.loop --once --dry-run" 2>&1)" || true
echo "$SMOKE"
if echo "$SMOKE" | grep -q "cycle failed"; then
  echo "SMOKE TEST FAILED — not restarting the service" >&2
  exit 1
fi

if [ "${SECRETS_CHANGED:-0}" = "1" ] || ! $SSH "sudo systemctl is-active --quiet digger"; then
  echo "== (re)starting digger =="
  $SSH "sudo systemctl restart digger && sleep 5 && \
        sudo systemctl status digger --no-pager -l | head -18"
else
  echo "== nothing changed and digger already running — not restarting =="
fi

echo "== memory caps actually applied? =="
$SSH "systemctl show digger -p MemoryHigh -p MemoryMax -p MemoryCurrent"

echo "== done. Tail logs with: =="
echo "  ssh -i $KEY opc@$VM_IP 'journalctl -u digger -f'"
