"""Distribution — what gets posted, when, and to which platform.

Created 2026-08-16 as the first step of a deliberate split: EDITORIAL (intake →
investigate → verify → write → review — still in engine/agents/orchestrator.py,
untouched by this split, on purpose) decides what a story SAYS and whether it's
true. DISTRIBUTION decides what happens to an already-approved-or-cleared piece
of writing — which platforms, what timing, and (new as of today) which runs are
even eligible to skip the human tap. Those are different kinds of judgment with
different failure modes, and today's incident (a duplicate reel posted 3x to
Instagram) was exactly a distribution bug, not an editorial one — it happened
downstream of good writing, in code that was tangled up with everything else.

This package is where all NEW distribution work lands going forward — YouTube
Shorts included. It does NOT yet contain the older carousel-composition code
still living in orchestrator.py (process_queued_carousels et al.) — that's a
real candidate for a future move, deliberately deferred rather than rewritten
in the same sitting as a live incident. See PROJECT-STATUS.md for the plan.
"""
