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

# A long-form script is 5-10x a reel's, and the model reasons before it writes.
#
# 12,000 was a guess and it was wrong in the worst way: the whole budget went to
# reasoning, the model never reached its answer, and the response came back with
# no text block at all. Measured 2026-09-13 — three consecutive calls, each
# output_tokens exactly 12000, each returning "". The failure then reported
# itself as "script parsed to zero chapters", which points at the parser.
#
# A 1,700-word script is ~2,500 tokens of output. The rest is headroom for the
# thinking that precedes it, which is what actually needed the room.
#
# But not unlimited headroom: above roughly 21k the Anthropic SDK refuses a
# non-streaming request outright — "Streaming is required for operations that
# may take longer than 10 minutes" — because a response that large could exceed
# the timeout. 32000 hit that wall immediately (2026-09-13). 16000 clears it and
# is still 6x what the script itself needs.
#
# If a script ever legitimately needs more than this, the fix is to stream in
# _run_claude, not to raise the number again.
MAX_TOKENS = 16000

# A script that will not parse will not parse the next time either — the input
# has not changed. This is the run #237 lesson (see publishing/reel_worker.py)
# applied to the path it was written for and then not applied to: three retries
# at two-minute intervals, ~$0.18 each, and it would have run all day.
MAX_SCRIPT_ATTEMPTS = 2

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
    out.extend(_clip_calls(parsed))
    out.extend(_long_holds(parsed))
    fits, why = longform.fits_window(parsed.get("word_count", 0))
    if not fits:
        out.append(why)
    return out


def _clip_calls(parsed):
    """Footage the reviewer has to decide about, not the renderer.

    A clip on a settled licence (GODL, CC-BY, licensed, our own) needs no
    comment — attribution is the condition and the caption carries it. A clip
    relying on fair dealing is a judgement about risk, and the person carrying
    that risk should be told, every time, before it ships. A clip with no
    recognised basis never reaches a frame at all; it is reported here so the
    reviewer knows a line was dropped rather than wondering where it went.
    """
    from publishing.longform_render import media_licence_status

    out = []
    for c in parsed.get("chapters", []):
        for kind, items in (("clip", c.get("clips") or []),
                            ("photo", c.get("photos") or [])):
            for item in items:
                ok, needs_call, why = media_licence_status(item)
                what = (item.get("shows") or item.get("src") or "")[:60]
                if not ok:
                    out.append(f"Chapter {c['n']} {kind} DROPPED — {what}: {why}")
                elif needs_call:
                    out.append(
                        f"Chapter {c['n']} {kind} needs your call — {what}: "
                        f"{why}. Credit alone is not permission; Content ID "
                        f"claims first and asks later.")
                elif kind == "photo":
                    # Every photo, every time. The licence is machine-checked;
                    # whether the picture shows what the line says it shows is
                    # not checkable by any API, and a correctly licensed photo
                    # of the wrong place is a false claim in our own voice.
                    # Demonstrated live 2026-09-11: a Commons search for
                    # "Indian highway construction" returns 1900s photographs
                    # of the Wind River Indian Reservation, Wyoming.
                    out.append(
                        f"Chapter {c['n']} photo — CONFIRM IT SHOWS THIS: "
                        f"\"{what}\" ({item.get('provenance') or 'no date given'}). "
                        f"Licence is fine; the subject is your call.")
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
        # Counted too. A run that has vanished, or has no draft, will still be
        # missing on the next tick — so this is a loop like any other, even
        # though it costs no model call. Silence for a day is its own failure.
        _note_attempt(queue_id)
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
        # Counted like any other failed attempt. The first version of the bound
        # only covered empty and unparseable OUTPUT, so a raising call — a bad
        # max_tokens, a dead key, a provider outage — retried unbounded, which
        # is the exact loop the bound exists to stop (2026-09-13: a ValueError
        # from the SDK, every two minutes, uncounted).
        _note_attempt(queue_id)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    if not (raw or "").strip():
        # Distinct from "would not parse". Nothing came back at all, which is
        # almost always the token ceiling — see MAX_TOKENS.
        _note_attempt(queue_id)
        return {"ok": False, "error": (
            "the model returned no text — most likely the whole token budget "
            f"went to reasoning (MAX_TOKENS={MAX_TOKENS}). Check the engine log "
            "for the stop_reason line.")}

    parsed = longform.parse_script(raw or "")
    if not parsed.get("chapters"):
        # Almost always a truncated or fenced response. Keep it on disk: a script
        # that cost a model call is worth looking at before it is thrown away.
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        bad = DRAFTS_DIR / f"longform-{queue_id}-UNPARSED.txt"
        bad.write_text(raw or "")
        _note_attempt(queue_id)
        return {"ok": False, "error": f"script parsed to zero chapters; raw kept at {bad}"}

    words = parsed.get("word_count", 0)
    if words < longform.LONGFORM_TARGET_MIN:
        # Not a judgement call about length — a script this short is almost
        # always the model running out of room and stopping, not deciding. The
        # first successful run produced 318 words against a 750 floor: five
        # chapters, ~2 minutes, which is a reel with chapter cards.
        #
        # Counted, so the existing 2-attempt bound applies. If it comes back
        # short twice the item parks and says so, which is the useful signal —
        # the skill needs work — rather than spending a human's attention at
        # gate 1 on something that was never long-form.
        _note_attempt(queue_id)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        short = DRAFTS_DIR / f"longform-{queue_id}-SHORT.txt"
        short.write_text(raw)
        return {"ok": False, "words": words, "error": (
            f"script came back {words} words against a {longform.LONGFORM_TARGET_MIN}"
            f"-word floor — that is a reel with chapter cards, not a long video. "
            f"Kept at {short}")}

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
    from shared.db import kv_set
    kv_set(f"longform_script_fails_{queue_id}", "")
    log.info("#%s scripted: %s words, %s chapters, %s blocker(s)",
             queue_id, parsed.get("word_count"), len(parsed["chapters"]),
             len(blockers))
    return {"ok": True, "path": str(path), "words": parsed.get("word_count", 0),
            "chapters": len(parsed["chapters"]), "blockers": blockers,
            "budget": budget_msg}


def _note_attempt(queue_id):
    """Count a failed scripting attempt, and park the item once it is clearly
    not going to work. Bounded because the input does not change between tries."""
    from shared.db import kv_get, kv_set, set_longform_status

    key = f"longform_script_fails_{queue_id}"
    n = int(kv_get(key) or 0) + 1
    kv_set(key, str(n))
    if n >= MAX_SCRIPT_ATTEMPTS:
        set_longform_status(queue_id, "dropped")
        kv_set(key, "")
        log.error("long-form #%s parked after %d failed scripting attempts — "
                  "re-queue it once the cause is fixed", queue_id, n)
        try:
            from engine.agents.orchestrator import _notify
            _notify(f"⏸️ Long-form #{queue_id} parked after {n} failed attempts "
                    f"to write its script. Each attempt is a paid call and the "
                    f"input does not change between them, so it stops here. "
                    f"Re-queue with /longform once the cause is fixed.")
        except Exception:
            pass


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
