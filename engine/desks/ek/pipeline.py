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

from engine.agents.skill_runner import run_skill, run_structured_skill, StructuredOutputError
from engine.desks.ek import linkcheck
from shared.db import save_run, update_run, _conn, _is_postgres

log = logging.getLogger("belief-desk")

# Which series a premise-check verdict routes to, and the desk it is stamped
# with. Anything not in this map is a DROP and never reaches the DB.
_ROUTE = {
    "PURSUE-A": ("ek", "ek:explainer-writer", "A"),
    "PURSUE-B": ("ek", "ek:explainer-writer", "B"),
    "ROUTE-GK": ("gk", "ek:turns-out-writer", "A"),
}
SERIES_NAME = {"ek": "Everyone Knows", "gk": "Turns Out"}

_M_GATE = r"GATE:\s*(READY-FOR-HUMAN|FRAMING-FIX|HOLD|KILL)"
_M_VERDICT = r"VERDICT:\s*(PURSUE-A|PURSUE-B|ROUTE-GK|DROP)"


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


def run_belief(belief, *, dry_run=False):
    """Take one candidate belief to the human gate. Returns a result dict.

    `dry_run` runs every skill but writes nothing to the database — for checking
    a prompt change without leaving rows behind.
    """
    out = {"belief": belief, "run_id": None}

    # ── 1. the gate ──────────────────────────────────────────────────────────
    gate_out = run_structured_skill(
        "ek:premise-check", f"CANDIDATE RECEIVED BELIEF:\n\n{belief}",
        marker=_M_VERDICT, max_tokens=1024, topic=belief[:60])
    verdict = _marker(gate_out, _M_VERDICT)
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
    record = run_skill(
        "ek:record-builder",
        f"BELIEF: {belief}\nSHAPE: {shape}\n\nPREMISE CHECK:\n{gate_out}",
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

    # ── 6. do the citations actually resolve? ────────────────────────────────
    # Deterministic, and deliberately after the reviewer: a model cannot check
    # this by reading, and run #136 shipped three 404s past a clean review.
    link_results, dead = linkcheck.check_text(draft)
    out["links"] = link_results
    out["dead_links"] = dead
    link_block = "\n\n## CITATION CHECK (automated)\n" + linkcheck.report(link_results)
    review = (review or "") + link_block
    # No URLs at all is held for the same reason a dead one is — it defeats the
    # check rather than passing it.
    no_links = not link_results
    if dead or no_links:
        log.warning("citation problem: %s",
                    f"{len(dead)} dead" if dead else "no URLs cited at all")

    out["review_verdict"] = rverdict
    out["draft"] = draft
    out["review"] = review

    # BLOCK means the draft rests on something the record file does not contain —
    # it must not reach the human as if it were ready. A dead citation is held for
    # the same reason: the reader cannot check it, which is the one thing this
    # desk promises they can.
    status = ("needs_attention" if (rverdict.startswith("BLOCK") or dead or no_links)
              else "pending_human")
    update_run(run_id, draft_text=draft, review_text=review, status=status)
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
