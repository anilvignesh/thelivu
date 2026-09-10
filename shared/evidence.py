"""How deep to investigate, and when to stop — as a rule rather than a judgement
call made fresh each time.

Two distinct problems this solves.

**How deep.** Depth scales with what a claim costs if it is wrong, not with how
interesting it is. A figure in the cold open is the most screenshotted line in
the piece and travels furthest from its context; a company named alongside
wrongdoing can be harmed by an error in a way an aggregate cannot. Those need
more than a sentence of background colour does, and the bar is set here so it
is not re-argued per story.

**When to stop.** An investigation can end for reasons that look identical in a
transcript and mean opposite things:

  * SATURATED — new searching returns corroboration, not new load-bearing
    facts. We know what there is to know. Conclusive.
  * BLOCKED — robots.txt disallows us, the host 403s, the page is JS-rendered.
    We know nothing about whether the evidence exists. **Not** conclusive: a
    person with a browser can often get it in a minute.

Recording only "investigation ended" collapses those into one, which makes a
capability gap look like a finished piece of work. Every stop carries its
reason, and `is_conclusive()` is the difference.

Used by the long-form and reel skills now, and by the Tier-0 digger when it
starts promoting its own candidates — the same test either way.
"""

# --------------------------------------------------------------------------
# Claim tiers, ordered by what an error costs
# --------------------------------------------------------------------------

NAMED = "named"            # a person or company named alongside wrongdoing
HOOK = "hook"              # the cold open / reel hook — travels furthest
SPINE = "spine"            # the story collapses without it
SUPPORTING = "supporting"  # colour, context, a corroborating example
BACKGROUND = "background"  # scene-setting, uncontested

TIERS = (NAMED, HOOK, SPINE, SUPPORTING, BACKGROUND)

PRIMARY = "primary"        # the record itself: the reply, the order, the audit
SECONDARY = "secondary"    # someone else's reporting of that record
UNSOURCED = "unsourced"

# What each tier requires before publication.
_REQUIRED = {
    NAMED: PRIMARY,
    HOOK: PRIMARY,
    SPINE: PRIMARY,
    SUPPORTING: SECONDARY,
    BACKGROUND: SECONDARY,
}

_RANK = {PRIMARY: 2, SECONDARY: 1, UNSOURCED: 0}


class Claim:
    """One assertion in a script, and what stands behind it."""

    def __init__(self, text, tier=SUPPORTING, source_kind=UNSOURCED, source=None,
                 response_noted=False, dispute_noted=False):
        if tier not in TIERS:
            raise ValueError(f"unknown tier: {tier!r}")
        if source_kind not in _RANK:
            raise ValueError(f"unknown source kind: {source_kind!r}")
        self.text = text
        self.tier = tier
        self.source_kind = source_kind
        self.source = source
        # Only meaningful for NAMED: has the named party's answer been sought
        # or their dispute recorded?
        self.response_noted = response_noted
        self.dispute_noted = dispute_noted

    def shortfall(self):
        """Why this claim is not yet publishable, or None."""
        need = _REQUIRED[self.tier]
        if _RANK[self.source_kind] < _RANK[need]:
            return (f"{self.tier} claim needs a {need} source, has "
                    f"{self.source_kind}: {self.text[:70]}")
        if self.tier == NAMED and not (self.response_noted or self.dispute_noted):
            # Naming someone without their side is the failure that does real
            # harm and is hardest to undo after publication.
            return (f"named claim carries no response or noted dispute: "
                    f"{self.text[:70]}")
        return None


def assess(claims):
    """(ready, blockers) for a set of claims."""
    blockers = [b for b in (c.shortfall() for c in claims) if b]
    return (not blockers), blockers


# --------------------------------------------------------------------------
# Stopping
# --------------------------------------------------------------------------

SATURATED = "saturated"              # no new load-bearing facts
ALL_SPINE_PRIMARY = "all_spine_primary"
BLOCKED = "blocked"                  # robots / 403 / JS — we could not look
BUDGET = "budget"                    # attempts exhausted, evidence may exist

_CONCLUSIVE = {SATURATED, ALL_SPINE_PRIMARY}


def is_conclusive(stop_reason):
    """Did the investigation END, or merely STOP?

    BLOCKED and BUDGET mean the evidence may well exist and we did not reach
    it. Treating those as conclusive is how a capability gap gets written up as
    a finished investigation.
    """
    return stop_reason in _CONCLUSIVE


class Stop:
    def __init__(self, reason, detail="", handoff=None):
        if reason not in (_CONCLUSIVE | {BLOCKED, BUDGET}):
            raise ValueError(f"unknown stop reason: {reason!r}")
        self.reason = reason
        self.detail = detail
        # What a human (or Tier 1) could still try. Required when not
        # conclusive: "we stopped" without "and here is what would get it" is
        # not a handoff, it is an abandonment.
        self.handoff = handoff

    def __str__(self):
        if is_conclusive(self.reason):
            return f"ENDED ({self.reason}): {self.detail}"
        return (f"STOPPED ({self.reason}): {self.detail}"
                + (f" — still obtainable by: {self.handoff}" if self.handoff else ""))


# --------------------------------------------------------------------------
# Budget — so "how many times" is a number, not a mood
# --------------------------------------------------------------------------

MAX_FETCH_ATTEMPTS = 3          # per document, across hosts/paths
MAX_SEARCH_REFORMULATIONS = 2   # per question


# --------------------------------------------------------------------------
# Escalation — go deeper regardless of budget
# --------------------------------------------------------------------------

CONFLICTING_FIGURES = "conflicting_figures"
FIGURE_USED_TWO_WAYS = "figure_used_two_ways"
NAMING_SOMEONE = "naming_someone"

_ESCALATIONS = {
    CONFLICTING_FIGURES:
        "two sources disagree on a number — resolve it, or state plainly that "
        "it is unresolved. Never pick the more striking one.",
    FIGURE_USED_TWO_WAYS:
        "the same figure is being used to mean two different things (the "
        "BBMP Rs 46,300cr precedent: total spend vs amount misappropriated). "
        "Conflating them is the overstatement the charter forbids.",
    NAMING_SOMEONE:
        "a person or company is about to be named alongside wrongdoing — "
        "primary source and their side, both, before this ships.",
}


def escalations(triggers):
    """Reasons the budget does not apply. Budget caps effort on ordinary
    questions; it must never cap effort on these."""
    return [(t, _ESCALATIONS[t]) for t in triggers if t in _ESCALATIONS]


def report(claims, stop):
    """A single auditable line-set: what stands up, what does not, why we
    stopped, and whether that stop meant anything."""
    ready, blockers = assess(claims)
    lines = [str(stop)]
    if not is_conclusive(stop.reason):
        lines.append("NOTE: this stop is not evidence of absence.")
    lines.append(f"claims: {len(claims)}   publishable: {'yes' if ready else 'NO'}")
    lines.extend(f"  blocker: {b}" for b in blockers)
    return "\n".join(lines)
