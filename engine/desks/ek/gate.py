"""The premise-check verdict, computed from the gate's own four judgments.

`premise-check` answers four questions and then emits a verdict. Twice now the
verdict has contradicted the answers — most recently on `gandhi-surname`, where
the REASON ended with the words "Route to GK lane." and the VERDICT line said
`DROP`. Both times the fix attempted was more prompt: a worked example, then a
rule, then a paragraph headed "`DROP` is not available to you here". The skill
kept doing it, and the cost of that particular slip is the one thing the
consequence floor must never do — bin a true, believed, checkable claim.

So the routing stopped being the model's to choose. It answers the judgments,
which need judgment; this computes the verdict from them, which needs none. The
model's own VERDICT line is still read, compared, and used as the answer only
when the structured fields are absent (an older prompt, a truncated reply) —
never to override them.
"""
import logging
import re

log = logging.getLogger("belief-desk")

VERDICTS = ("PURSUE-A", "PURSUE-B", "ROUTE-GK", "DROP")

_YES = {"yes", "y", "true"}
_NO = {"no", "n", "false"}


def _field(text, label):
    m = re.search(rf"^{label}:[ \t]*(.+)$", text or "", re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _bool(text, label, default=None):
    """A yes/no field. Anything else (including 'unsure') returns `default`,
    which is how DOES_WORK: unsure becomes "pursue" without a special case."""
    v = _field(text, label).strip().lower().rstrip(".")
    v = v.split()[0] if v else ""
    if v in _YES:
        return True
    if v in _NO:
        return False
    return default


def stated_verdict(text):
    m = re.search(r"^VERDICT:[ \t]*(PURSUE-A|PURSUE-B|ROUTE-GK|DROP)",
                  text or "", re.IGNORECASE | re.MULTILINE)
    return m.group(1).upper() if m else ""


def verdict(text, *, topic=""):
    """The verdict this output actually supports.

    Returns the computed verdict, or the model's stated one when the structured
    judgments are missing. Logs any disagreement — a silent override would hide
    exactly the regression this module exists to catch.
    """
    stated = stated_verdict(text)
    real = _bool(text, "REAL_BELIEF")
    shape = (_field(text, "SHAPE") or "").strip().upper()[:1]
    if real is None or shape not in ("A", "B"):
        # Pre-fields output. Trust the model's verdict — this is the old
        # behaviour, kept so an unrelated prompt edit can't strand the pipeline.
        return stated

    narrow = _bool(text, "NARROW", default=True)
    works = _bool(text, "DOES_WORK", default=True)   # 'unsure' → pursue
    unfalsifiable = _bool(text, "UNFALSIFIABLE", default=False)
    myth_swap = _bool(text, "MYTH_SWAP", default=False)
    live_news = _bool(text, "LIVE_NEWS", default=False)

    if not real or unfalsifiable or myth_swap or live_news:
        got = "DROP"
    elif not narrow:
        # The thesis that will not narrow — the hard kill, and asked of BOTH
        # shapes. A causal claim spanning seventy years of governments is a
        # thesis however the gate labelled its shape, and when breadth was a
        # shape-B-only test the gate escaped it by calling such a claim
        # "factual" (kerala-development, 2026-08-04).
        got = "DROP"
    elif not works:
        # A true, believed, checkable factual claim that does no work is the GK
        # lane's whole catalogue. A frame that does no work is not: GK carries
        # no arguments, so a weak shape B is dropped rather than routed.
        got = "ROUTE-GK" if shape == "A" else "DROP"
    else:
        got = f"PURSUE-{shape}"

    if stated and stated != got:
        log.warning("premise-check contradicted itself%s: said %s, its own "
                    "judgments give %s (REAL_BELIEF=%s SHAPE=%s NARROW=%s "
                    "DOES_WORK=%s) — using %s",
                    f" on {topic}" if topic else "", stated, got, real, shape,
                    narrow, works, got)
    return got
