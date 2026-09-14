#!/usr/bin/env bash
# Drain the digger's document spool into this laptop's permanent archive.
#
# Run FROM THE LAPTOP. The digger captures every document it reads at READ TIME
# — the only moment we are certain to hold the bytes, because by the time a URL
# rots a re-download fails too — but it is a 945MB box with 26GB of disk that
# also runs freellmapi and sshd. It holds the last few hours; this holds the
# collection.
#
# Safe to re-run. Content-addressed, so a document already held is skipped, and
# nothing is deleted from the spool until its bytes are verified here.
#
# Usage: ops/pull-archive.sh [VM_PUBLIC_IP]
set -euo pipefail

VM_IP="${1:-129.225.67.115}"
KEY="$HOME/.ssh/thelivu_digger"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new opc@$VM_IP"
SPOOL="/var/lib/thelivu/spool"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

export PATH="$HOME/.railway/bin:$PATH"
cd "$(dirname "$0")/.."

if ! $SSH "test -d $SPOOL"; then
  echo "no spool on the digger yet — nothing to collect"
  exit 0
fi

COUNT="$($SSH "ls -1 $SPOOL 2>/dev/null | grep -cv '\.part$'" || echo 0)"
if [ "$COUNT" -eq 0 ]; then
  echo "spool is empty — nothing to collect"
  exit 0
fi
echo "== $COUNT file(s) on the spool =="

# rsync, NOT scp: .part files are half-written documents the digger is still
# producing, and copying one would stage bytes whose name is a hash they do not
# match. The archive refuses those anyway, but not transferring them is cheaper.
rsync -az --exclude '*.part' \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  opc@"$VM_IP":"$SPOOL/" "$STAGE/"

DATABASE_URL="$(python3 -c "
import json, subprocess
print(json.loads(subprocess.check_output(
    ['railway', 'variables', '--service', 'Postgres', '--json']))['DATABASE_PUBLIC_URL'])")" \
  ./venv/bin/python -m ops.archive_pull "$STAGE" --vm "$VM_IP" --key "$KEY" --spool "$SPOOL"
