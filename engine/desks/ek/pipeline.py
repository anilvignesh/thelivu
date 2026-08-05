"""The belief desks' spine: one received belief in, one gated draft out.

Two series share this pipeline because they share a trust floor — a wrong Turns
Out reel costs exactly as much credibility as a wrong Everyone Knows piece. What
differs is only which writer runs and which `desk` the run is stamped with, and
both of those are decided by premise-check's verdict, not by the caller.

    premise-check ──DROP──────────────► nothing
                  ──PURSUE-A/B────────► Everyone Knows  (desk='ek')
                  ──ROUTE-GK──────────► Turns Out       (desk='gk')
                        │
                        ▼
                  record-builder → record-verifier ──KILL/HOLD──► parked
                        │ READY / FRAMING-FIX
                        ▼
                     writer → explainer-reviewer ──BLOCK──► parked
                        │ APPROVE / REVISE(once)
                        ▼
                   status='pending_human'  ★ THE HUMAN GATE ★

Nothing here publishes or posts. The last thing this module does is set a run to
pending_human; the tap is the owner's, in the command centre.

    python -m engine.desks.ek.pipeline "A goldfish has a three-second memory."
"""
import argparse
import logging
import re
import sys

from engine.agents.skill_runner import (run_skill, run_structured_skill,
                                        StructuredOutputError, MARK)
# Imported under a distinct name on purpose: `gate` is already the local for the
# TRUST gate's verdict inside run_belief, and the collision made Python treat the
# module reference as a local read-before-assignment — the whole desk raised
# UnboundLocalError on its first real call.
from engine.desks.ek import draft as draft_mod, gate as premise_gate, linkcheck
from shared.db import save_run, update_run, save_belief_parts, _conn, _is_postgres

log = logging.getLogger("belief-desk")

# Which series a premise-check verdict routes to, and the desk it is stamped
# with. Anything not in this map is a DROP and never reaches the DB.
_ROUTE = {
    "PURSUE-A": ("ek", "ek:explainer-writer", "A"),
    "PURSUE-B": ("ek", "ek:explainer-writer", "B"),
    "ROUTE-GK": ("gk", "ek:turns-out-writer", "A"),
}
SERIES_NAME = {"ek": "Everyone Knows", "gk": "Turns Out"}

_M_GATE = MARK("GATE", "READY-FOR-HUMAN|FRAMING-FIX|HOLD|KILL")
_M_VERDICT = MARK("VERDICT", "PURSUE-A|PURSUE-B|ROUTE-GK|DROP")


def _field(text, label):
    """Read a `LABEL: value` line. Horizontal whitespace only — `\\s` would match
    a newline and let an empty label swallow the next line's text, which is the
    bug that made a bare HOOK: steal BEAT 1 in the reel parser."""
    m = re.search(rf"^{label}:[ \t]*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _marker(text, pattern):
    m = re.search(pattern, text or "", re.IGNORECASE)
    return m.group(1).upper() if m else ""


def _save_belief(run_id, belief, shape, gate_out):
    """Side-table row: the belief-specific fields that have no home in
    pipeline_runs, kept out of it so the news schema doesn't grow columns that
    are null for most rows."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""INSERT INTO belief_pieces
                (run_id, belief, shape, currency, case_anchor, counter_case, so_what)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (run_id, belief, shape,
             _field(gate_out, "CURRENCY"), _field(gate_out, "CASE_ANCHOR"),
             _field(gate_out, "COUNTER"), _field(gate_out, "SO_WHAT")),
        )
        conn.commit()
    finally:
        conn.close()


def run_belief(belief, *, note="", dry_run=False):
    """Take one candidate belief to the human gate. Returns a result dict.

    `note` is the owner's steer from the command centre's submit box — where he
    heard the belief, a document worth looking for, a trap to avoid. It reaches
    the RESEARCH step only, as direction and never as fact: the record file is
    built from retrieved sources, and a note saying "it was X" does not make it
    so. It was being stored on the queue row and read by nothing, which is why
    the note on run #146 ("the Feroze-Khan claim is the replacement story, do not
    let it carry the piece") had no effect on the piece at all.

    `dry_run` runs every skill but writes nothing to the database — for checking
    a prompt change without leaving rows behind.
    """
    out = {"belief": belief, "run_id": None}

    # ── 1. the gate ──────────────────────────────────────────────────────────
    gate_out = run_structured_skill(
        "ek:premise-check", f"CANDIDATE RECEIVED BELIEF:\n\n{belief}",
        marker=_M_VERDICT, max_tokens=1024, topic=belief[:60])
    # The verdict is computed from the gate's four judgments, not read off its
    # VERDICT line — the two have disagreed, and the disagreement binned a
    # candidate the gate itself had reasoned into the GK lane. See gate.py.
    verdict = premise_gate.verdict(gate_out, topic=belief[:60])
    out["verdict"] = verdict
    out["premise_check"] = gate_out
    log.info("premise-check: %s", verdict)

    if verdict not in _ROUTE:
        out["stopped_at"] = "premise-check"
        out["reason"] = _field(gate_out, "REASON")
        return out

    desk, writer_skill, shape = _ROUTE[verdict]
    # premise-check may have restated an overstated belief; the rest of the
    # pipeline must work on ITS version, not the caller's caricature.
    belief = _field(gate_out, "BELIEF") or belief
    out.update(desk=desk, series=SERIES_NAME[desk], belief=belief, shape=shape)

    # ── 2. the record ────────────────────────────────────────────────────────
    note_block = ""
    if (note or "").strip():
        note_block = (
            "\n\nOWNER'S NOTE — direction for your search, NOT evidence and NOT a "
            "finding. It may name a document worth hunting, a trap to avoid, or where "
            "the belief was heard. Verify anything in it like anything else; if the "
            "record contradicts it, the record wins and you say so.\n"
            f"{note.strip()}\n")
    record = run_skill(
        "ek:record-builder",
        f"BELIEF: {belief}\nSHAPE: {shape}\n\nPREMISE CHECK:\n{gate_out}{note_block}",
        max_tokens=8192, topic=belief[:60])
    out["record"] = record

    # ── 3. the trust gate ────────────────────────────────────────────────────
    verification = run_structured_skill(
        "ek:record-verifier",
        f"BELIEF: {belief}\nSHAPE: {shape}\n\nRECORD FILE:\n\n{record}",
        marker=_M_GATE, max_tokens=4096, topic=belief[:60])
    gate = _marker(verification, _M_GATE)
    out["gate"] = gate
    out["verification"] = verification
    log.info("record-verifier: %s", gate)

    if dry_run:
        out["stopped_at"] = "dry-run"
        return out

    # A run row exists from here on, so a KILL/HOLD is visible in the command
    # centre rather than vanishing — same as the news desk parks its holds.
    run_id = save_run(
        video_id=None, source=f"{SERIES_NAME[desk]} (belief desk)",
        throughline=belief[:400], trust_gate=gate,
        verification_report=verification,
        status="pending_human" if gate in ("READY-FOR-HUMAN", "FRAMING-FIX") else gate.lower(),
        desk=desk)
    out["run_id"] = run_id
    _save_belief(run_id, belief, shape, gate_out)

    if gate in ("KILL", "HOLD"):
        out["stopped_at"] = "record-verifier"
        out["reason"] = _field(verification, "REASON")
        return out

    # ── 4. write ─────────────────────────────────────────────────────────────
    framing = ""
    if gate == "FRAMING-FIX":
        framing = ("FRAMING FIX REQUIRED — the facts hold, the framing does not. "
                   "Apply the verifier's REQUIRED OF THE WRITER section exactly and "
                   "do not assert beyond the record.\n\n")
    write_input = (f"{framing}BELIEF: {belief}\nSHAPE: {shape}\n\n"
                   f"RECORD FILE:\n\n{record}\n\nVERIFICATION REPORT:\n\n{verification}")
    draft = run_skill(writer_skill, write_input, max_tokens=4096, topic=belief[:60])

    # ── 5. review, with one revision pass ────────────────────────────────────
    review = run_skill(
        "ek:explainer-reviewer",
        f"{write_input}\n\nDRAFT:\n\n{draft}", max_tokens=4096, topic=belief[:60])
    rverdict = _field(review, "VERDICT").upper()

    if rverdict.startswith("REVISE"):
        log.info("reviewer asked for a revision — one pass")
        draft = run_skill(
            writer_skill,
            f"{write_input}\n\nYOUR PREVIOUS DRAFT:\n\n{draft}\n\n"
            f"REQUIRED CHANGES (apply every one):\n\n{review}",
            max_tokens=4096, topic=belief[:60])
        review = run_skill(
            "ek:explainer-reviewer",
            f"{write_input}\n\nDRAFT:\n\n{draft}", max_tokens=4096, topic=belief[:60])
        rverdict = _field(review, "VERDICT").upper()

    # ── 6. split the draft: what a reader sees vs what the reel says ─────────
    # The writer emits one block containing both. The spine must NOT reach the
    # page (runs #136-#140 rendered the narration under the sources), and the
    # reel must get the spine EXACTLY as verified rather than a re-scripting of
    # the article. See engine/desks/ek/draft.py.
    parts = draft_mod.split(draft)
    spine = parts["spine"]
    if not parts["article"] or not spine:
        # Neither half is optional: no article is nothing to publish, no spine
        # is a piece that can never become a reel without a post-gate rewrite.
        missing = "ARTICLE" if not parts["article"] else "SPOKEN SPINE"
        log.warning("writer output has no %s section — parking run #%s", missing, run_id)
        update_run(run_id, draft_text=draft, review_text=review,
                   status="needs_attention")
        out.update(status="needs_attention", draft=draft, review=review,
                   stopped_at="draft-split", reason=f"writer emitted no {missing} section")
        return out
    page_md = draft_mod.to_markdown(parts, shape=shape)

    # ── 7. do the citations actually resolve? ────────────────────────────────
    # Deterministic, and deliberately after the reviewer: a model cannot check
    # this by reading, and run #136 shipped three 404s past a clean review.
    # Checked against the READER'S page, not the raw output — a URL that only
    # ever appears in the spine is not a citation anyone can follow.
    link_results, dead = linkcheck.check_text(page_md)
    out["links"] = link_results
    out["dead_links"] = dead
    link_block = "\n\n## CITATION CHECK (automated)\n" + linkcheck.report(link_results)
    # The check underneath the link check: does every source NAME a work a reader
    # could find? An address that resolves and a book with a publisher and a year
    # are both checkable; "biographical records of X — minimum three independent
    # sources" is not, and carries no URL to test. Holding on missing URLs alone
    # treated those two as the same thing and parked a piece sourced to Guha,
    # Nanda and Gopal. (Owner's ruling, 2026-08-04.)
    unnamed = linkcheck.unnamed_sources(page_md)
    if unnamed:
        link_block += ("\n\n**%d source(s) name no findable work:**\n" % len(unnamed)
                       + "\n".join(f"- {u[:160]}" for u in unnamed))
    review = (review or "") + link_block
    if dead or unnamed:
        log.warning("citation problem: %s",
                    f"{len(dead)} dead" if dead else f"{len(unnamed)} unnamed source(s)")
    out["unnamed_sources"] = unnamed

    out["review_verdict"] = rverdict
    out["draft"] = page_md
    out["spine"] = spine
    out["review"] = review

    # BLOCK means the draft rests on something the record file does not contain —
    # it must not reach the human as if it were ready. A dead citation is held for
    # the same reason: the reader cannot check it, which is the one thing this
    # desk promises they can.
    status = ("needs_attention" if (rverdict.startswith("BLOCK") or dead or unnamed)
              else "pending_human")
    save_belief_parts(run_id, spine=spine, label=draft_mod.view_label(
        dict(parts, shape=shape)))
    update_run(run_id, draft_text=page_md, review_text=review, status=status)
    out["status"] = status
    out["stopped_at"] = "human gate"
    return out


def main(argv):
    ap = argparse.ArgumentParser(description="Take one received belief to the human gate.")
    ap.add_argument("belief", help="the belief, as people state it")
    ap.add_argument("--dry-run", action="store_true", help="run the skills, write nothing")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        r = run_belief(a.belief, dry_run=a.dry_run)
    except StructuredOutputError as e:
        print(f"HALTED: {e.skill_name} produced no valid structured output")
        print(e.raw[:1500])
        return 2

    print("\n" + "=" * 72)
    print(f"belief   : {r['belief']}")
    print(f"verdict  : {r.get('verdict')}   series: {r.get('series', '—')}")
    print(f"gate     : {r.get('gate', '—')}   review: {r.get('review_verdict', '—')}")
    print(f"run      : #{r.get('run_id')}   status: {r.get('status', '—')}")
    print(f"stopped  : {r.get('stopped_at')}")
    if r.get("reason"):
        print(f"reason   : {r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
