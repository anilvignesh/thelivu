"""What a carousel from a belief piece needs that a news carousel does not.

A belief piece is a row in `pipeline_runs` with `desk` in ('ek', 'gk') and a
`draft_text` that is deliberately the same house markdown a news piece uses —
that is why `queue_carousel_run`, the slide renderer, the fileserver's on-demand
re-render, the post path and the whole command centre already work on one. What
was missing was not plumbing. It was three editorial decisions:

1. **The composer is news-shaped.** `carousel-composer` opens slide 1 on the
   story's own headline and stamps it `VERIFIED`. A belief piece's first slide
   has to open on the belief — the reader has to recognise the thing they
   already think before the record contradicts it — and `VERIFIED` is the wrong
   word for a piece whose whole subject is a claim that is widely believed.
   So the belief desks get their own composer, `ek:carousel-composer`, exactly
   as they got their own writers.
2. **Shape B has to wear its label.** See `slide_label` below.
3. **The spine must not reach a slide.** The narration lives on
   `belief_pieces.spine`, never in `draft_text`, and nothing in this module ever
   reads it. The composer is handed the reader's page and nothing else, so the
   only words it can put on a slide are words a reader could already read.

Everything here is deterministic and model-free: it decides what to hand the
composer and how to dress what comes back. The composing itself is the same
`run_structured_skill` call the news desk makes, from the same place
(`process_queued_carousels`).
"""
import re

from engine.desks.ek.draft import DEFAULT_VIEW_LABEL, REEL_VIEW_LABEL

BELIEF_DESKS = ("ek", "gk")

# Slide 1's stamp. Fixed per series, not the composer's choice, for the same
# reason the reel's kicker and the view label are fixed: it is furniture that
# tells a reader which series they are looking at, and furniture that changes per
# piece teaches a reader nothing. It also keeps `VERIFIED` — a word about a news
# story's standing — off a desk where the headline claim is the thing being
# corrected.
SERIES_STAMP = {"ek": "EVERYONE KNOWS", "gk": "TURNS OUT"}
SERIES_NAME = {"ek": "Everyone Knows", "gk": "Turns Out"}

COMPOSER_SKILL = "ek:carousel-composer"

# The `> [!VIEW] …` callout the reader's page carries (engine/desks/ek/draft.py).
_VIEW_CALLOUT = re.compile(r"^>\s*\[!VIEW\][^\n]*\n?", re.MULTILINE)


def is_belief(desk):
    return (desk or "news").lower() in BELIEF_DESKS


def composer_skill(desk):
    """Which slide composer runs for this desk."""
    return COMPOSER_SKILL if is_belief(desk) else "carousel-composer"


def slide_stamp(desk, default="VERIFIED"):
    return SERIES_STAMP.get((desk or "").lower(), default)


def slide_label(belief, page=""):
    """The on-slide view marker for a belief piece, or "" when it needs none.

    **Where it belongs, and why: every slide.** The reel puts the pill on every
    story frame because the viewer who takes an argued frame for a finding is the
    one watching muted who never taps through. A carousel's version of that
    viewer is not a hypothesis — Instagram re-serves a carousel to people
    *starting on a later slide* (the news composer's own brief says so), and any
    single slide can be screenshotted and travel alone. A label on slide 1 only
    would therefore be seen by exactly the readers who were never at risk, and
    missed by the ones who were. There is no equivalent of the reel's sign-off
    card here — every slide of a carousel carries a claim from the piece — so
    there is nothing to exempt.

    Shape is not consulted directly: `belief_pieces.label` is set by
    `draft.view_label`, which is already "" for shape A and the writer's (or the
    default) sentence for shape B. Reading the same field the reel reads is what
    keeps the surfaces from disagreeing about whether a piece argues a frame.

    `page` is the reader's markdown, checked as a second witness. The page
    carries its own `> [!VIEW]` callout, written from the same value at the same
    moment, so the two can only disagree if a row was migrated or hand-edited —
    and when they do, the labelled answer wins. An unnecessary marker costs a
    line of furniture; a missing one costs the reader the fact that they are
    reading an argument.
    """
    if (belief or {}).get("label") or _VIEW_CALLOUT.search(page or ""):
        return REEL_VIEW_LABEL
    return ""


def caption_label(belief, page=""):
    """The long-form view sentence for the Instagram caption, or "".

    The pill is four words because it has to survive being read at a glance; the
    caption has room for the sentence the page carries, and the caption is a
    reader surface too.
    """
    if not slide_label(belief, page):
        return ""
    return ((belief or {}).get("label") or "").strip() or DEFAULT_VIEW_LABEL


def strip_view_callout(markdown):
    """Remove the `> [!VIEW]` line from the page before the composer reads it.

    The label reaches the carousel as rendered furniture on every slide. Left in
    the input it would arrive at the composer looking like a sentence of the
    piece, and a slide whose whole headline is "This piece argues a view from the
    documented record." is furniture wearing a beat's clothes — it spends a swipe
    and says nothing about the story.
    """
    return _VIEW_CALLOUT.sub("", markdown or "")


def composer_input(run, belief):
    """What `ek:carousel-composer` is given: a two-line brief and the page.

    The brief carries only the series and the belief as the reader's page states
    it. Nothing from the gate — not CURRENCY, not SO_WHAT, not COUNTER, not
    CASE_ANCHOR — and never the spine. Those are the desk's reasoning about the
    piece, and the reader-facing rule is that no published surface carries any of
    it; a composer that never sees a sentence cannot put it on a slide.
    """
    desk = (run.get("desk") or "news").lower()
    page = run.get("draft_text") or ""
    series = SERIES_NAME.get(desk, "")
    stated = ((belief or {}).get("belief") or "").strip()
    head = [f"SERIES: {series}"]
    if stated:
        head.append(f"THE RECEIVED BELIEF: {stated}")
    if slide_label(belief, page):
        head.append("THIS PIECE ARGUES A FRAME: yes — the record contests an "
                    "interpretation, so the carousel must show the counter-evidence "
                    "the piece names.")
    head.append("")
    head.append("THE PIECE:")
    head.append("")
    return "\n".join(head) + strip_view_callout(page)


def caption(run, belief, article_url, hashtags=""):
    """The Instagram caption for a belief carousel.

    The news caption opens on `throughline`, which for a belief run is the belief
    itself, stated flat and out of context ("A goldfish has a three-second
    memory."), reading as if the account is asserting it. Naming the series first
    makes the same sentence do the job it does on the reel: this is the thing
    everyone knows, and the slides are what the record says about it.
    """
    desk = (run.get("desk") or "news").lower()
    series = SERIES_NAME.get(desk, "")
    stated = ((belief or {}).get("belief") or "").strip() or (run.get("throughline") or "")
    bits = [f"{series.upper()}: {stated}" if series and stated else stated]
    label = caption_label(belief, run.get("draft_text") or "")
    if label:
        bits.append(label)
    if article_url:
        bits.append(f"Full story & sources: {article_url}")
    if hashtags:
        bits.append(hashtags)
    return "\n\n".join(b for b in bits if b)[:2200]
