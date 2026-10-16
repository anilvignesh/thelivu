# Railway config-as-code migration (deadline 2026-12-01)

`railway.toml` stops working on 2026-12-01. `railway.ts.proposed` is its replacement, imported from the live project with
`railway config pull` (secrets stay as `preserve()`, never written to the file) plus the three settings the toml carries:
builder NIXPACKS, start `python run.py`, restart ALWAYS, for both `thelivu` and `thelivu-agent`.

`railway config plan` against the live project: 0 to add, 4 to change, 0 to destroy (all four set those same values).

To finish, before 2026-12-01:
1. `npm install --no-save railway` in the repo root, then `cp ops/railway/railway.ts.proposed .railway/railway.ts`
2. `railway config plan` (expect exactly the 4 changes above; STOP if it says anything is destroyed)
3. `railway config apply`, then delete `railway.toml`
Do not run `railway config init`: it writes a generic template that would add a service called `web`.
