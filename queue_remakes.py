import os, json
if os.path.exists(".db_url"):
    os.environ["DATABASE_URL"] = open(".db_url").read().strip()

from shared.db import _conn, kv_set, kv_get

# (reel_id, run_id, note) — chronological by run_id. First one promoted now;
# the rest queued for the new daily sweep in run.py to promote one per day.
TARGETS = [
    (72, 186, "Remake requested 2026-09-07 (Anil): held 2026-08-29 as a precaution "
              "before that session's caption-leak fixes, never individually confirmed "
              "broken, never followed up. Original leak was model format-instructions "
              "text ('3-6 word text. Maybe:') on card 1 -- different shape than the "
              "_sane_caption() fix targeted. Rebuilding with all current leak-detection "
              "(including the 2026-09-02 spoken-line hard-block) should clear it."),
    (69, 188, "Remake requested 2026-09-07 (Anil): posted 2026-08-21, deleted by Anil "
              "2026-08-24 -- felt stuck/static (confirmed via ffprobe: not a corrupt "
              "render, a pacing/motion-magnitude complaint). Caveat: ZOOM_MAX in "
              "publishing/reel.py is still 1.08 (8%), unchanged since this was diagnosed -- "
              "the underlying magnitude was never bumped, only a separate Ken-Burns "
              "timing bug (commit aeacfd1, which predates this reel) was fixed. This "
              "remake may reproduce the same stuck/static feel; flagged to Anil as an "
              "open question rather than changed unilaterally (it matches reel_kinetic.py's "
              "ZOOM_TARGET=1.07, so it may be a deliberate house choice, not an oversight)."),
    (70, 191, "Remake requested 2026-09-07 (Anil): posted 2026-08-24, deleted by Anil "
              "same day -- same stuck/static complaint and same ZOOM_MAX caveat as reel #69/"
              "run 188 above."),
    (74, 195, "Remake requested 2026-09-07 (Anil): held 2026-08-29 as a precaution before "
              "that session's fixes, never individually confirmed broken, never followed up."),
    (75, 198, "Remake requested 2026-09-07 (Anil): held 2026-08-29 as a precaution before "
              "that session's fixes, never individually confirmed broken, never followed up."),
    (76, 199, "Remake requested 2026-09-07 (Anil): held 2026-08-29 as a precaution before "
              "that session's fixes, never individually confirmed broken, never followed up."),
    (79, 201, "Remake requested 2026-09-07 (Anil): held 2026-08-29 as a precaution before "
              "that session's fixes, never individually confirmed broken, never followed up."),
    (71, 203, "Remake requested 2026-09-07 (Anil): posted 2026-08-26, deleted by Anil -- "
              "on-screen caption leaked the model's raw word-count self-correction reasoning. "
              "Root-caused and fixed same day (_sane_caption() guard, commit 0aa6dd8) -- this "
              "remake runs through that fix plus every leak-detection improvement since."),
    (77, 206, "Remake requested 2026-09-07 (Anil): held 2026-08-29 as a precaution before "
              "that session's fixes, never individually confirmed broken, never followed up."),
    (85, 212, "Remake requested 2026-09-07 (Anil): this is the run that triggered the "
              "2026-09-02 pause (hook's spoken line was the literal unfilled placeholder "
              "'<the spoken opening line>'). DB shows this reel was never actually posted "
              "(no ig_media_id, no posted_at, status sat at 'ready') despite the incident "
              "writeup's 'shipped...live on Instagram' language -- flagged as a discrepancy, "
              "not corrected retroactively. The hard-block fix for exactly this (commit "
              "a8a4116) is live; this remake is the first real test of it against the "
              "original bad input."),
]

conn = _conn()
cur = conn.cursor()

# Sanity check: confirm every target reel id maps to the run id we expect,
# before mutating anything.
ph = "%s"
for rid, run, _ in TARGETS:
    cur.execute(f"SELECT run_id, status FROM reels WHERE id = {ph}", (rid,))
    row = cur.fetchone()
    assert row, f"reel #{rid} not found"
    assert row[0] == run, f"reel #{rid} has run_id {row[0]}, expected {run}"
    print(f"verified reel #{rid} -> run #{run}, current status={row[1]!r}")

# Promote the first one now.
first_id, first_run, first_note = TARGETS[0]
cur.execute(f"UPDATE reels SET status = 'remake_requested', notes = {ph} WHERE id = {ph}",
            (first_note, first_id))
conn.commit()
print(f"\nPromoted reel #{first_id} (run {first_run}) to remake_requested now.")

# Queue the rest for the daily sweep.
backlog = [{"reel_id": rid, "run_id": run, "note": note} for rid, run, note in TARGETS[1:]]
kv_set("reel_remake_backlog", json.dumps(backlog))
print(f"Queued {len(backlog)} more for the daily sweep: {[b['reel_id'] for b in backlog]}")

cur.close()
conn.close()
