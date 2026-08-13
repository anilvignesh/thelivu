#!/usr/bin/env bash
# Run ON the Oracle VM (as ubuntu) after first SSH login. Sets up everything
# except secrets (that's deploy-secrets.sh, run from the laptop afterward) and
# the voice reference clip (copied by deploy-secrets.sh too — it's personal
# voice data, not in the repo).
#
# See docs/plans/06-reel-autonomy.md.
set -euo pipefail

REPO_URL="https://github.com/anilvignesh/thelivu"

echo "== apt packages =="
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git ffmpeg \
  fonts-noto-core fonts-noto-extra

# fonts-noto-extra carries Noto Sans/Serif Malayalam on Ubuntu 24.04 — confirm
# the exact family names the frame builder asserts on are present:
fc-list | grep -i malayalam || echo "WARNING: no Malayalam fonts found by fc-list — illustrated reels will fail until fixed"

echo "== clone repo =="
cd ~
if [ ! -d thelivu ]; then
  git clone "$REPO_URL" thelivu
fi
cd thelivu

echo "== thelivu venv =="
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

echo "== cbx venv (Chatterbox, CPU torch ONLY — do not let this pull CUDA) =="
cd ~
python3 -m venv cbx
# CPU-only torch index first, so pip resolves chatterbox-tts's torch dep against
# it rather than pulling the default CUDA wheel (HANDOFF.md's explicit warning —
# CUDA torch OOM'd this class of box before on a laptop; no GPU here either).
cbx/bin/pip install --upgrade pip
cbx/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
cbx/bin/pip install chatterbox-tts torchaudio

echo "== systemd units =="
sudo cp ~/thelivu/ops/oracle-vm/chatterbox.service /etc/systemd/system/
sudo cp ~/thelivu/ops/oracle-vm/reel-worker.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "== done =="
echo "Next: run deploy-secrets.sh FROM THE LAPTOP (not here) to copy the voice"
echo "reference clip + write the env file, then:"
echo "  sudo systemctl enable --now chatterbox reel-worker"
