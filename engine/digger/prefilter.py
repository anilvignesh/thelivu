"""The cheap pass that decides what a reviewer never has to look at.

Build-order step 6. Written against real output rather than a guess about it:
the first fourteen cycles produced five candidates, and inspecting them is what
this module is shaped by.

What actually came back, and what it taught:

  * **Two were navigation chrome.** "Screen Reader Access Document" and
    "Accessibility Statement page content" from the Lok Sabha site — the model
    read them correctly and reported, accurately, that they contained nothing
    relevant. Grounding worked; the finding was still worthless. Correctly
    extracted nothing is the single most common form of noise, and it is not a
    grounding failure, so nothing upstream catches it.

  * **Three were real** SEBI enforcement records, but thin: a recovery
    certificate exists, naming a person. True, checkable, and not yet a story —
    what makes it one is a pattern across many, which is a later step's job.

  * **All five were flagged `differ`**, which was a bug in the agreement
    comparison rather than genuine disagreement (fixed in extract.py). A
    pre-filter built on that signal a day earlier would have been calibrated to
    noise.

So this drops what a human would never promote, and leaves judgement about what
IS promotable to the review step. When unsure, it keeps: a false drop is
invisible and permanent, a false keep costs one line in a batch.
"""

import re

# Pages that exist for accessibility or navigation. They are not documents,
# and every site on the beat has them.
_CHROME_TITLE = re.compile(
    r"(screen[- ]reader|accessibility|sitemap|privacy policy|terms of use|"
    r"disclaimer|copyright policy|hyperlink(ing)? policy|help\b|faq\b|"
    r"website polic|contact us|feedback form|how to use|font size|"
    r"skip to main)", re.I)

# A finding whose own text reports the absence of a finding. The model did its
# job; there was nothing there.
_NULL_FINDING = re.compile(
    r"(contains no |does not contain|no information about|no relevant|"
    r"nothing (matching|relevant|of note)|not (contain|include) any|"
    r"no details (about|regarding)|no such (information|record)|"
    r"there (is|are) no )", re.I)

# A lead needs something checkable in it. Not proof — an anchor a reviewer can
# pull on: a figure, a date, a statute, an identifier.
_CHECKABLE = re.compile(
    r"(\b(rs\.?|₹|inr)\s?[\d,.]+|\b\d[\d,.]*\s?(crore|lakh|cr\b|per cent|%)|"
    r"\b(19|20)\d{2}\b|\bsection\s+\d+|\bclause\s+\d+|\bregulation\s+\d+|"
    r"\b[A-Z]{2,}\s?\d{3,}\b|\b\d{2,}\s?(km|kms|projects|cases|days)\b)", re.I)

MIN_FINDING_WORDS = 8

KEEP = "keep"
DROP = "drop"


def classify(candidate):
    """(verdict, reason) for one candidate.

    `candidate` is a dict as recorded by the digger: title, finding, excerpt,
    source_url, agreement.
    """
    title = (candidate.get("title") or "").strip()
    finding = (candidate.get("finding") or "").strip()

    if not title or not finding:
        return DROP, "empty title or finding"

    if _CHROME_TITLE.search(title):
        return DROP, f"site furniture, not a record: {title[:60]}"

    if _NULL_FINDING.search(finding):
        # The model read the document correctly and found nothing. That is a
        # working extractor, not a lead.
        return DROP, "reports the absence of a finding — correctly extracted nothing"

    if len(finding.split()) < MIN_FINDING_WORDS:
        return DROP, f"too thin to review ({len(finding.split())} words)"

    if not _CHECKABLE.search(finding + " " + title):
        # No figure, date, statute or identifier. A reviewer has nothing to
        # pull on, and the charter's attribution rules could not be met from it.
        return DROP, "nothing checkable in it — no figure, date, statute or identifier"

    return KEEP, "has a checkable anchor"


def dedup(candidates):
    """Collapse candidates describing the same finding.

    Cross-source duplication is expected and was predicted before it appeared:
    CAG press releases and CAG audit reports describe the same findings, so
    per-URL dedup in the loop does not catch it. Reuses the extractor's own
    overlap comparison so 'the same finding' means one thing in this codebase,
    not two.
    """
    from engine.digger.extract import _same_finding

    kept = []
    for c in candidates:
        if any(_same_finding(c, k) for k in kept):
            continue
        kept.append(c)
    return kept


def run(candidates):
    """(kept, dropped) — dropped carries reasons.

    Reasons are returned rather than discarded because this is where a
    pre-filter goes wrong silently: if it starts dropping real leads, the only
    evidence is in what it said about them.
    """
    surviving, dropped = [], []
    for c in candidates:
        verdict, reason = classify(c)
        if verdict == KEEP:
            surviving.append(c)
        else:
            dropped.append((c, reason))
    return dedup(surviving), dropped


def summarise(kept, dropped):
    lines = [f"pre-filter: {len(kept)} kept, {len(dropped)} dropped"]
    counts = {}
    for _, reason in dropped:
        key = reason.split(":")[0].split("(")[0].strip()
        counts[key] = counts.get(key, 0) + 1
    lines.extend(f"  {n:3d}  {reason}" for reason, n in
                 sorted(counts.items(), key=lambda x: -x[1]))
    return "\n".join(lines)
