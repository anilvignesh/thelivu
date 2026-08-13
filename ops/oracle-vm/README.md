# Oracle VM — reel autonomy runbook

See `docs/plans/06-reel-autonomy.md` for the why/design. This is the how, once
the VM exists (`docs/oracle-vm-setup.md` covers creating it — that part needs
Anil's phone/card, nothing here does).

## Order of operations

1. **Create the VM** — `docs/oracle-vm-setup.md`. Get the public IP.
2. **SSH in with the dedicated key** and run the provisioning script:
   ```
   ssh -i ~/.ssh/thelivu_oracle ubuntu@<VM_IP>
   git clone https://github.com/anilvignesh/thelivu ~/thelivu   # if provision.sh can't reach it itself
   bash ~/thelivu/ops/oracle-vm/provision.sh
   ```
   Installs ffmpeg, Malayalam fonts, clones the repo, builds both venvs
   (`~/thelivu/venv` for the worker, `~/cbx` for Chatterbox — CPU torch only),
   installs the systemd units. Does NOT start anything yet — no secrets, no
   voice reference clip.
3. **From the laptop** (this machine, where `railway` is already logged in):
   ```
   ops/oracle-vm/deploy-secrets.sh <VM_IP>
   ```
   Pulls `DATABASE_PUBLIC_URL` / `NVIDIA_API_KEY` / `SLIDE_SERVER_BASE_URL` from
   Railway (never printed), writes them to `ops/oracle-vm/reel-worker.env` on
   the VM (`chmod 600`, gitignored — never committed), copies
   `~/thelivu_voice_ref2.wav`, and starts both services.
4. **Verify:**
   ```
   ssh -i ~/.ssh/thelivu_oracle ubuntu@<VM_IP> \
     'curl -s localhost:3901/health; journalctl -u reel-worker -n 40 --no-pager'
   ```
   Chatterbox health should return 200. The worker logs either "nothing to
   build" or a run it's picked up.
5. **First real reel:** wait for the next `status='published'` run with no
   reel, or manually publish one, and watch it show up `ready` in the command
   center's Reels tab within one poll interval (10 min default). Review, then
   tap Post same as always — nothing about that step changed.

## Files here

- `provision.sh` — run on the VM, one-time setup (idempotent — safe to re-run).
- `deploy-secrets.sh <IP>` — run from the laptop, pushes secrets + the voice
  clip, (re)starts services. Re-run any time a Railway var rotates.
- `chatterbox.service` / `reel-worker.service` — systemd units, installed by
  `provision.sh`, `Restart=always`.
- `reel-worker.env` — **not in git**, written by `deploy-secrets.sh` directly on
  the VM.

## If something needs changing later

- Redeploy code: `ssh ... 'cd ~/thelivu && git pull && sudo systemctl restart reel-worker'`
  (Chatterbox's server code rarely changes; restart it too if it did.)
- Rotate a secret: re-run `deploy-secrets.sh <IP>` — it overwrites the env file
  and restarts both services.
- Slow it down/speed it up: `REEL_WORKER_POLL_SECONDS` in `reel-worker.env`
  (defaults to 600).
