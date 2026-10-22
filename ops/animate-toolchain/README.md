# animate toolchain (backup copy)

The reel renderer lives on the Oracle reel VM at `~/animate` and is NOT otherwise under version control (found during the
2026-10-22 audit). This is a copy of the parts needed to rebuild it: `tools/` (build, still, export, voice, review, textcheck),
`kit/`, `grammar/`, `templates/`, `styles/` (style definitions, without demos and sample renders), and the notes.

What is NOT here: `pieces/` (3 GB of per-reel working folders and renders; each is reproducible from `publishing/animate/stories`
via `publishing.animate.worker`), and the VM's Python venv `~/fwenv` and Playwright browsers `/opt/pw`.

Restore: copy this folder to `~/animate` on a fresh VM, then provision per `ops/oracle-vm/README.md`.
The scene library the pieces use is `publishing/animate/lib/scenes.js` (that one IS in git); `build_piece.py` copies it into each piece.
If you change anything in `~/animate/tools` on the VM, copy it back here and commit.
