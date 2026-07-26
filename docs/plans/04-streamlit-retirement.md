# Plan 04 — Retire the Streamlit dashboard

**Goal:** once the command center (`command_center/`, :8600) has proven itself
for ~a week of daily use, remove the parallel Streamlit dashboard (:8501) so
there's one operations surface. **Do NOT do this until Anil confirms the CC has
fully replaced his workflow** — parallel running is safe and cheap; premature
removal is not.

## Preconditions (verify before starting)

- Anil has been reviewing/approving/posting from the CC, not the dashboard,
  for several days.
- Every action the dashboard had exists in the CC. Cross-check the Streamlit
  tab list (Overview/Ingest/Drafts/Pipeline/Carousels/Digs/Follow-ups/Sources/
  Tasks/Costs) against the CC's 11 views. Known parity gaps to confirm closed:
  - **File drafts** (`articles/drafts/*.md`) — the Streamlit Drafts tab had a
    "file drafts" section (`_load_file_drafts`) that publishes/kills loose .md
    files. The CC does NOT have this. Before retiring: either add it to the CC
    (Gate view), or confirm with Anil that the file-draft workflow is dead
    (everything goes through the DB pipeline now). **This is the one real gap
    — handle it explicitly, don't drop it silently.**

## Do

1. Stop the autostart: remove/disable
   `~/.config/autostart/thelivu-dashboard.desktop` (and confirm
   `~/.jarvis/thelivu-dashboard.sh` won't be relaunched).
2. Kill the running process on :8501 (`fuser -k 8501/tcp`).
3. `git rm dashboard.py requirements-dashboard.txt` (verify nothing else
   imports them — grep the repo; `run.py` and the bot don't).
4. Remove dashboard mentions from `docs/HANDOFF.md` §2 and `PROJECT-STATUS.md`;
   make the CC the sole documented surface.
5. Keep `~/.jarvis/thelivu-dashboard.sh` on disk but inert, or delete it — the
   CC has its own launcher (`command_center/run.sh`).

## Test

- After removal: reboot (or re-login) and confirm only :8600 comes up,
  autostart-wise.
- The engine + bot are untouched (neither imports dashboard code) — a
  `py_compile` of run.py and a bot smoke check is enough.
- Publishing still flows: the CC and bot share `publishing.publish.*`; the
  dashboard was only ever a reader. Confirm one approve→publish from the CC
  still works end to end.

## Note

The CC's perf lessons (`command_center/db.py` docstring) supersede the
Streamlit-era caching notes in HANDOFF §5.15. That gotcha entry can be updated
to point at the CC as the resolution ("the real fix — a proper web app — now
exists").
