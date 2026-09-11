"""Writing the long-form script — the step that turns a queued story into a gate.

`engine/skills/long-form-script/SKILL.md` has existed since the format was
designed, and `longform.parse_script()` has always known how to read what it
emits. Nothing called it. So `longform_build.attach_script()` was a door with
nobody on the other side of it: a story could graduate out of the reel format,
sit in `longform_queue` as `queued`, and wait there forever for a human to hand
it a script. The NH penalty script was written by hand for exactly that reason.

This is the missing caller. It is deliberately the only automated step between
"the reel format reported that this outgrew it" and "a person has to read
something" — which is the line Anil drew (2026-09-11): *"all research, digging,
validation should run automated, once a script or report is reviewed and
validated, we create the long videos."*

## What the writer is given, and what it is not

The material is the run's own record, nothing more:

    throughline           the one-line claim the run was built around
    draft_text            the published article — already verified and approved
    verification_report   what was checked, and against what
    reason                why the reel format said this did not fit

Not the open web. A long-form script that reaches for new facts at writing time
is a script whose new facts never passed the trust gate, and the gate is
upstream of here for a reason: everything in `draft_text` has been through it.
The skill's job is to give that material eight minutes of room, not to extend it.

## The blockers on the gate-1 card are mechanical, not an evidence assessment

`shared/evidence.py` assesses `Claim` objects, and a script is prose — there is
no honest way to derive tiers and source kinds from it without a second model
call whose opinion nobody checked. So what goes on the card is what can be
checked by looking: **which chapters carry a RECORD line and which do not**, and
which chapters state figures without one.

That is a weaker claim than "this cleared the evidence bar", and it is labelled
as one. It is also the single most useful thing to put in front of a reviewer,
because it is precisely what reading 1,500 words of confident prose will not
make you notice.
"""

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("longform_script")

DRAFTS_DIR = Path(os.environ.get(
    "LONGFORM_DRAFTS_DIR",
    Path(__file__).resolve().parent.parent / "articles" / "drafts"))

# A long-form script is 5-10x a reel's. 4096 truncates one mid-chapter, which
# parses cleanly into a script that simply stops.
MAX_TOKENS = 12000

# A figure in a chapter with no record behind it is the thing a reviewer should
# be pointed at. Deliberately loose — it is a prompt to look, not a verdict.
#
# Number WORDS, not digits, because that is the house style: the script is read
# aloud, so "forty of fifty-nine" is what a chapter actually contains and a
# digit-only pattern would have found nothing in any script we have written.
# The unit is what makes it a claim rather than an ordinal, so both halves are
# required.
_NUMBER_WORD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
                r"twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
                r"hundred|thousand|lakh|crore|million|billion)")
_UNIT = (r"(?:crore|lakh|percent|per cent|%|kilomet|km|rupees|cases|projects|"
         r"of (?:fifty|forty|thirty|twenty|nineteen|eighteen|seventeen|sixteen|"
         r"fifteen|fourteen|thirteen|twelve|eleven|ten|nine|eight|seven|six|"
         r"five|four|three|two)\b)")
_FIGURE = re.compile(
    rf"\b(?:\d[\d,.]*|{_NUMBER_WORD}(?:[- ]{_NUMBER_WORD})*)\s*{_UNIT}",
    re.I)


def material_for(queue_id):
    """The run's own record, assembled for the writer. Returns (text, meta)."""
    from shared.db import get_run, longform_item

    row = longform_item(queue_id)
    if not row:
        raise ValueError(f"no long-form queue item #{queue_id}")
    run_id = row.get("run_id")
    run = get_run(run_id) if run_id else None
    if not run:
        raise ValueError(f"#{queue_id} points at run #{run_id}, which is missing")

    draft = (run.get("draft_text") or "").strip()
    if not draft:
        raise ValueError(f"run #{run_id} has no draft text to work from")

    parts = [
        f"THROUGHLINE: {run.get('throughline') or '(none recorded)'}",
        "",
        "WHY THIS OUTGREW THE REEL FORMAT:",
        row.get("reason") or "(not recorded)",
        "",
        "THE PUBLISHED ARTICLE — this is the verified material. Everything in the",
        "script must come from here. Do not add facts that are not in it.",
        "",
        draft,
    ]
    report = (run.get("verification_report") or "").strip()
    if report:
        parts += [
            "",
            "VERIFICATION REPORT — what was checked and against what. Use it to",
            "decide which claims can carry a RECORD line and which cannot.",
            "",
            report,
        ]
    meta = {"run_id": run_id, "slug": run.get("slug") or f"run{run_id}",
            "title": row.get("title") or run.get("throughline") or f"run #{run_id}",
            "status": row.get("status")}
    return "\n".join(parts), meta


def mechanical_blockers(parsed):
    """What a reviewer should look at, found by looking rather than by judging.

    NOT an evidence assessment — see the module docstring. These are the three
    things that are checkable without a model: a chapter with no record behind
    it, a chapter stating figures with no record behind it, and a script whose
    narration will not fit an idle window.
    """
    from publishing import longform

    out = []
    for c in parsed.get("chapters", []):
        states_figures = bool(_FIGURE.search(c.get("text") or ""))
        # A chapter that says a number and never puts it on screen is the
        # specific failure the first sample had: the argument turned on 2,732
        # against 780 and the viewer saw a symbolic ledger. Separate from the
        # record check, because they fail for different reasons and a reviewer
        # fixes them differently — one needs a FIGURE line, the other a source.
        if states_figures and not c.get("figures"):
            out.append(f"Chapter {c['n']} ({c['title']}) states figures but puts "
                       f"none on screen — no FIGURE line")
        if c.get("records"):
            continue
        if states_figures:
            out.append(f"Chapter {c['n']} ({c['title']}) states figures and cites "
                       f"no record")
        else:
            out.append(f"Chapter {c['n']} ({c['title']}) cites no record")
    if not parsed.get("why_long_form"):
        out.append("No WHY_LONG_FORM line — the script does not say why this is "
                   "not a reel")
    out.extend(_long_holds(parsed))
    fits, why = longform.fits_window(parsed.get("word_count", 0))
    if not fits:
        out.append(why)
    return out


# Past this, one frame is a slide with a voice over it. Anil, 2026-09-11: the
# video "shouldnt end up like an audio book". The renderer cuts as often as the
# narration allows, but it can only cut to something that exists — a chapter
# that declares two assets and runs two minutes holds each for a minute, and no
# renderer setting fixes that. Only another FIGURE, TABLE, RECORD or IMAGE line
# does, which makes it a note for the reviewer rather than a knob.
MAX_HOLD_SECONDS = 20.0


def _long_holds(parsed):
    """Units whose frames sit on screen too long because too little was declared."""
    from publishing import longform, longform_render

    out = []
    def _bookend(key):
        return {"figures": parsed.get(f"{key}_figures") or [],
                "images": parsed.get(f"{key}_images") or []}

    units = [("Cold open", _bookend("cold_open"), parsed.get("cold_open", ""),
              parsed.get("cold_open_image"))]
    for c in parsed.get("chapters", []):
        units.append((f"Chapter {c['n']} ({c['title']})", c, c["text"], None))
    units.append(("Close", _bookend("close"), parsed.get("close", ""),
                  parsed.get("close_image")))

    for name, chap, text, fallback in units:
        words = len((text or "").split())
        if not words:
            continue
        secs = words / (longform.SPOKEN_WORDS_PER_MINUTE / 60.0)
        assets = longform_render.plan_assets(chap or {}, fallback_image=fallback)
        shots = longform_render._shot_count(secs, len(assets)) if assets else 1
        hold = secs / max(1, shots)
        if hold > MAX_HOLD_SECONDS:
            out.append(f"{name} holds one frame for {hold:.0f}s — declares "
                       f"{len(assets)} asset(s) for {secs:.0f}s of narration; "
                       f"needs more FIGURE/TABLE/RECORD/IMAGE lines")
    return out


def write_script(queue_id, model=None, dry_run=False):
    """Write, check and attach the long-form script for one queued story.

    Returns {ok, path, words, chapters, blockers} — or {ok:False, error}. Never
    raises for an expected failure: this runs inside the engine tick, and one
    unwritable script must not take the tick down.

    On success the item is at SCRIPTED and the gate-1 card has gone out. This
    function never advances past that: SCRIPTED is a human gate, and rendering
    an unread script spends an hour of the only voice server.
    """
    from publishing import longform
    from publishing.longform_build import attach_script

    try:
        material, meta = material_for(queue_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if meta["status"] != longform.QUEUED:
        return {"ok": False, "error": (
            f"#{queue_id} is {meta['status']}, not {longform.QUEUED} — a script "
            "already exists, or a person has already acted on it")}

    from engine.agents.skill_runner import run_skill
    log.info("#%s writing a long-form script from run #%s", queue_id, meta["run_id"])
    try:
        raw = run_skill("long-form-script", material, max_tokens=MAX_TOKENS,
                        run_id=meta["run_id"])
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    parsed = longform.parse_script(raw or "")
    if not parsed.get("chapters"):
        # Almost always a truncated or fenced response. Keep it on disk: a script
        # that cost a model call is worth looking at before it is thrown away.
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        bad = DRAFTS_DIR / f"longform-{queue_id}-UNPARSED.txt"
        bad.write_text(raw or "")
        return {"ok": False, "error": f"script parsed to zero chapters; raw kept at {bad}"}

    blockers = mechanical_blockers(parsed)
    ok_budget, budget_msg = longform.budget_check(parsed)
    if not ok_budget:
        # The one hard failure. Length is advisory; machine time is not.
        return {"ok": False, "error": budget_msg, "blockers": blockers}

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / f"longform-{queue_id}-{meta['slug']}.txt"
    if dry_run:
        path = path.with_suffix(".dryrun.txt")
        path.write_text(raw)
        return {"ok": True, "path": str(path), "dry_run": True,
                "words": parsed.get("word_count", 0),
                "chapters": len(parsed["chapters"]), "blockers": blockers,
                "budget": budget_msg}
    path.write_text(raw)

    res = attach_script(queue_id, str(path), blockers=blockers)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error"), "path": str(path)}
    log.info("#%s scripted: %s words, %s chapters, %s blocker(s)",
             queue_id, parsed.get("word_count"), len(parsed["chapters"]),
             len(blockers))
    return {"ok": True, "path": str(path), "words": parsed.get("word_count", 0),
            "chapters": len(parsed["chapters"]), "blockers": blockers,
            "budget": budget_msg}


def write_pending(limit=1, model=None):
    """Script the queued stories. One per pass by default.

    One, because a long-form script is a large model call and long-form is
    occasional — a queue with three in it means something unusual happened, and
    spending three large calls in one tick to clear it is how a day's budget
    goes on a format that publishes monthly.
    """
    from publishing import longform
    from shared.db import longform_queue

    out = []
    for row in longform_queue(status=longform.QUEUED)[:limit]:
        res = write_script(row["id"], model=model)
        res["id"] = row["id"]
        if not res.get("ok"):
            log.warning("long-form #%s not scripted: %s", row["id"], res.get("error"))
        out.append(res)
    return out


def main():
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [longform-script] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("queue_id", nargs="?", type=int,
                    help="script this queue item; omitted, scripts the next queued one")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the script to disk but do not attach it or open gate 1")
    ap.add_argument("--material", action="store_true",
                    help="print what the writer would be given, and stop")
    args = ap.parse_args()

    from shared.db import init_db
    init_db()

    if args.material:
        if not args.queue_id:
            sys.exit("--material needs a queue id")
        text, meta = material_for(args.queue_id)
        print(f"# run #{meta['run_id']} · {meta['status']} · {len(text.split())} words\n")
        print(text)
        return 0

    results = ([write_script(args.queue_id, dry_run=args.dry_run)]
               if args.queue_id else write_pending())
    for r in results:
        print(r.get("error") if not r.get("ok") else
              f"#{r.get('id', args.queue_id)}: {r['words']} words, "
              f"{r['chapters']} chapters, {len(r['blockers'])} blocker(s) -> {r['path']}")
        for b in r.get("blockers") or []:
            print(f"    ⚠ {b}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
