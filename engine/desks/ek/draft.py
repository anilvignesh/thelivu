"""Split a belief writer's output into the two things it actually contains.

The writers emit ONE block with five labelled parts: HEADLINE, DEK, LABEL, the
ARTICLE, the SOURCES, and the SPOKEN SPINE. Only the first four are for a
reader. The spine is production material — the narration the reel is cut from —
and putting it in `draft_text` verbatim, as runs #136-#140 did, means the /a/
page renders it under the sources and the reader sees the piece twice.

So the split happens once, here, at write time:

    draft_text          the reader-facing markdown, in the house format the
                        news desk already uses (H1 title, standfirst, sources
                        footer) so publish, the teaser, the article page, the
                        carousel and the command centre all work unchanged.
    belief_pieces.spine the verified narration, stored whole, for the reel.
    belief_pieces.label the shape-B view label, for the reel and the page.

The reason the spine is stored rather than re-derived is the whole of §9.5 of
docs/everyone-knows-desk.md: the spine was written by the writer under the
verifier's ruling and reviewed as part of the draft. Re-scripting it from the
article after the fact would re-introduce a generation step AFTER the trust
gate, which is exactly the seam this desk cannot afford.
"""
import re

# The view label is furniture, not prose: the same sentence on every shape-B
# piece, so a reader learns to recognise it. The writer may propose its own
# wording in LABEL:; this is the fallback and the reel's short form is derived
# from it, never from the writer's sentence (a label that changes per piece is
# not a label).
DEFAULT_VIEW_LABEL = "This piece argues a view from the documented record."
REEL_VIEW_LABEL = "A VIEW FROM THE RECORD"

STANDFIRST = (
    "*From Thelivu — explanatory journalism on the side of ordinary people. It "
    "argues a view and tells you when it's doing so. Facts are sourced and "
    "confirmed; the opinion is mine and is flagged. Drafted with AI assistance, "
    "reviewed by a human editor.*"
)

_CONF_BY_SHAPE = {"A": "Confirmed", "B": "Contested"}


def _line(text, label):
    """Read a `LABEL: value` line. Horizontal whitespace only — see the same
    rule in pipeline.py and publishing/reel.py for what `\\s` does here."""
    m = re.search(rf"^{label}:[ \t]*(.+)$", text or "", re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _section(text, name):
    """The body of a `## NAME` section, up to the next `## ` heading or the end."""
    m = re.search(rf"^##[ \t]+{name}[ \t]*$(.*?)(?=^##[ \t]+|\Z)",
                  text or "", re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def split(raw):
    """Parse a writer's raw output into its parts. Every value is a string; a
    part the writer omitted comes back empty rather than missing, so callers
    can decide what is fatal (only `article` and `spine` really are)."""
    raw = (raw or "").strip()
    return {
        "headline": _line(raw, "HEADLINE"),
        "dek": _line(raw, "DEK"),
        "label": _line(raw, "LABEL"),
        "confidence": _line(raw, "CONFIDENCE"),
        "article": _section(raw, "ARTICLE"),
        "sources": _section(raw, "SOURCES"),
        "spine": _section(raw, "SPOKEN SPINE"),
    }


def spine_lines(spine):
    """The spine as ordered spoken lines.

    Tolerant of the shapes a model reaches for when asked for "6-9 short lines":
    bare lines, `- ` bullets, and `1. ` numbering all mean the same thing. Blank
    lines and any stray markdown heading are dropped. Nothing is rewritten —
    this only decides where one spoken line ends and the next begins, because
    every word here has already been through the trust gate.
    """
    out = []
    for line in (spine or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", s).strip()
        if s:
            out.append(s)
    return out


def view_label(parts):
    """The shape-B label sentence, or "" for shape A. A writer that left LABEL
    empty on a shape-B piece still gets the label: the reader's ability to see
    that a frame is being argued does not depend on the writer remembering."""
    if (parts.get("shape") or "").upper() != "B":
        return ""
    return (parts.get("label") or "").strip() or DEFAULT_VIEW_LABEL


def to_markdown(parts, *, shape="", contact=None):
    """The reader-facing article, in the house markdown format.

    Layout matches a news piece deliberately — H1 headline, the standing
    standfirst, an H2 that carries the dek (parse_article reads the first H2 as
    the teaser hook), body, sources, confidence line. The one addition is the
    shape-B callout, which is emitted as a `> [!VIEW]` block so the page can
    style it as a label rather than as a pull-quote.
    """
    p = dict(parts, shape=shape or parts.get("shape") or "")
    bits = [f"# {p['headline']}".rstrip(), "", STANDFIRST]

    if p.get("dek"):
        bits += ["", f"## {p['dek']}"]

    label = view_label(p)
    if label:
        # Before the body, not after it: a reader who bounces at the second
        # paragraph must already have seen that this piece argues a frame.
        bits += ["", f"> [!VIEW] {label}"]

    bits += ["", p["article"]]

    if p.get("sources"):
        bits += ["", "## Sources", "", p["sources"]]

    conf = p.get("confidence") or _confidence_fallback(p)
    bits += ["", f"*Confidence: {conf}*"]

    md = "\n".join(bits).strip() + "\n"
    return md.replace("[contact]", contact) if contact else md


def _confidence_fallback(p):
    """A confidence line for a draft written before the writers emitted one.

    Shape decides the label because shape IS the claim being made: a shape A
    piece asserts a correction the record establishes, a shape B piece argues a
    frame over a documented case. Deliberately blunt — the writer's own
    sentence about its weakest load-bearing claim is better, and this exists so
    an old draft still carries the mandatory furniture rather than to replace
    it.
    """
    label = _CONF_BY_SHAPE.get((p.get("shape") or "").upper(), "Developing")
    if label == "Contested":
        return ("Contested — the documented case is established; the frame built "
                "on it is argued, and the counter-evidence is in the piece.")
    return ("Confirmed — every corrective claim rests on at least two independent "
            "sources named in the piece.")
