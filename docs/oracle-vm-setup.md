# Oracle Cloud VM — the 5-minute part only Anil can do

Part of `docs/plans/06-reel-autonomy.md`. This is only the account/identity step
(phone + card verification, OCI won't let anything else do this). Once the VM
exists and this doc's info is captured, Jarvis picks up the rest (deploy,
systemd, testing) unattended.

## 1. Sign up (if you don't already have an OCI account)

https://signup.oraclecloud.com — email, phone OTP, and a card for identity
verification only (Always Free resources are never billed to it). Pick the
**Mumbai (bom)** or **Hyderabad (hyd)** region if offered — lowest latency to
Railway/NVIDIA doesn't matter much here, but pick one and remember it, you can't
easily move a free-tier instance between regions later.

## 2. Create the instance

Compute → Instances → **Create instance**.
- **Image:** Ubuntu 24.04 (Canonical, default is fine)
- **Shape:** click "Change shape" → **Ampere (Arm-based) → VM.Standard.A1.Flex**
  — set **4 OCPU / 24GB RAM** (the Always Free allotment, and it's the whole
  free-tier point — don't accidentally leave it at a smaller default and don't
  pick an AMD/Intel shape, those aren't free).
- **Networking:** default VCN is fine.
- **SSH keys:** choose "Paste public keys" and paste this (already generated,
  dedicated to this box, not reused from anywhere else):

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIO4gWcQq/87mvGdri2T9Mpu9ATkgNPXGl+YNB8jBtnLK thelivu-reel-worker@oracle
```

- Leave boot volume at default (~50GB is plenty).
- **Create.**

**If it says "Out of host capacity"** for the A1.Flex shape — known Oracle free-
tier friction, capacity in a region comes and goes. Just retry (sometimes a
different region/AD helps). Not a sign anything's wrong with the setup.

## 3. After it's running

Note the **public IP** (Instance details page) and send it back — that's the
only thing needed to continue. No need to touch the Security List / firewall:
this box only needs outbound internet (to Railway Postgres + NVIDIA's API) and
inbound SSH (22, open by default on the default security list) — nothing else
gets exposed publicly, by design (see plan 06 — Chatterbox stays bound to
127.0.0.1, never a public port).

## 4. Hand back to Jarvis

Once you have the IP, either paste it here or just say "the VM's up, IP is
X.X.X.X" — deploy, systemd units, and the first test run happen from there
without needing you again until it's time to review the first auto-built reel
in the command center.
