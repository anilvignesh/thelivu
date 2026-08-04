"""Platform-neutral parse of a Thelivu article.

`parse_article()` turns a prepared (scaffolding-stripped) Markdown draft into an
Article: title, hook, confidence, and an ordered list of neutral Blocks. Every
publishing renderer (telegram, future medium/instagram) consumes this, so the
markdown is parsed exactly once and platform code only serialises.
"""
import re

_CONF_EMOJI = {"confirmed": "🟢", "developing": "🟡", "contested": "🔴"}
_DEFAULT_CONF = ("Developing", _CONF_EMOJI["developing"])


class Block:
    """A neutral content block. `text` keeps raw inline markdown; renderers
    convert inline (**bold**, *italic*, [t](u)) themselves."""
    __slots__ = ("type", "level", "text", "items", "kind")

    def __init__(self, type, level=0, text="", items=None, kind=""):
        self.type = type           # heading | paragraph | blockquote | callout | list | rule
        self.level = level
        self.text = text
        self.items = items or []   # list blocks only: [raw inline md, ...]
        self.kind = kind           # callout blocks only: VIEW, NOTE, …

    def __repr__(self):
        return f"Block({self.type!r}, level={self.level}, text={self.text[:30]!r})"


class Article:
    __slots__ = ("title", "hook", "confidence_label", "confidence_emoji", "blocks")

    def __init__(self, title, hook, confidence_label, confidence_emoji, blocks):
        self.title = title
        self.hook = hook
        self.confidence_label = confidence_label
        self.confidence_emoji = confidence_emoji
        self.blocks = blocks


def strip_inline(s):
    """Drop inline markdown markers for plain-text contexts (title, hook)."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", s)
    return s.strip()


def _first_sentence(s):
    m = re.search(r"^(.+?[.!?])(\s|$)", s)
    return m.group(1).strip() if m else s[:200].strip()


def parse_blocks(md):
    """Split markdown into neutral blocks on blank-line boundaries."""
    blocks = []
    for chunk in re.split(r"\n\s*\n", md.strip()):
        lines = [l for l in chunk.splitlines() if l.strip() != ""]
        if not lines:
            continue
        stripped = chunk.strip()

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            blocks.append(Block("rule"))
            continue
        if all(re.match(r"^\s*[-*]\s+", l) for l in lines):
            items = [re.sub(r"^\s*[-*]\s+", "", l).strip() for l in lines]
            blocks.append(Block("list", items=items))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m and "\n" not in stripped:
            blocks.append(Block("heading", level=len(m.group(1)), text=m.group(2).strip()))
            continue
        if stripped.startswith(">"):
            text = " ".join(re.sub(r"^\s*>\s?", "", l) for l in lines).strip()
            # `> [!VIEW] …` is a callout, not a quote. The belief desk's shape B
            # pieces argue a frame over a documented case, and the reader has to
            # be able to SEE that seam — a pull-quote's italics say "nice line",
            # which is the opposite of what this block means. Renderers that
            # don't know the type fall through to a paragraph, so the sentence is
            # never lost, only unstyled.
            m = re.match(r"^\[!(\w+)\]\s*(.*)$", text, re.DOTALL)
            if m:
                blocks.append(Block("callout", text=m.group(2).strip(),
                                    kind=m.group(1).upper()))
                continue
            blocks.append(Block("blockquote", text=text))
            continue
        blocks.append(Block("paragraph", text=" ".join(l.strip() for l in lines).strip()))
    return blocks


def parse_article(md):
    """Parse prepared article markdown into a neutral Article.

    The H1 title is pulled out (it becomes the page title, not body content). The
    first H2 is the hook; it stays in the body too. Confidence is read from the
    '*Confidence: X — …*' line, defaulting to Developing.

    If the draft has no H1 at all (the writer sometimes headlines with '##' —
    run #53 shipped to Telegraph titled just 'Thelivu' that way), the first
    heading of any level is promoted to the title and removed from the body.
    """
    title = ""
    hook = ""
    conf_label, conf_emoji = _DEFAULT_CONF
    out_blocks = []

    for b in parse_blocks(md):
        if b.type == "heading" and b.level == 1 and not title:
            title = strip_inline(b.text)
            continue  # title handled separately; not part of the body
        if b.type == "heading" and b.level == 2 and not hook:
            hook = strip_inline(b.text)
        if b.type == "paragraph":
            cm = re.match(r"^\*?\s*Confidence:\s*([A-Za-z]+)\b", b.text)
            if cm:
                conf_label = cm.group(1).capitalize()
                conf_emoji = _CONF_EMOJI.get(conf_label.lower(), _DEFAULT_CONF[1])
        out_blocks.append(b)

    if not title:
        for b in out_blocks:
            if b.type == "heading":
                title = strip_inline(b.text)
                out_blocks.remove(b)  # promoted to title; not body content
                if hook == title:
                    hook = ""  # was the same heading; recompute below
                break

    if not hook:
        for b in out_blocks:
            if b.type == "paragraph" and not b.text.lstrip().startswith("*"):
                hook = _first_sentence(strip_inline(b.text))
                break

    return Article(title, hook, conf_label, conf_emoji, out_blocks)


def strip_scaffolding(md):
    """Drop the writer's review-only header ('# DRAFT — for human review',
    sometimes inside a code fence, plus leading blanks) so it never becomes a
    title or reaches a reader. The single shared implementation — the bot's
    publish path and the orchestrator's preview path both go through this."""
    lines = (md or "").strip().splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s == "" or s.startswith("```") or ("DRAFT" in s.upper() and "HUMAN REVIEW" in s.upper()):
            i += 1
            continue
        break
    return "\n".join(lines[i:]).strip()


def extract_headline(raw_md):
    """The article's real headline from a raw (unstripped) draft — never the
    scaffolding header or the italic 'From Thelivu' preamble. '' if the draft
    has no heading at all."""
    return parse_article(strip_scaffolding(raw_md)).title


FOOTER = (
    "\n\n—\n"
    "Sources above. Drafted with AI assistance, reviewed by a human editor "
    "before publishing. Spotted an error? We correct openly — [contact]."
)


def prepare_for_publish(md, contact):
    """Turn an approved draft into exactly what a reader sees: strip the review
    scaffolding, ensure the standing footer is present exactly once, fill the
    [contact] placeholder. Substance is never touched. Shared by the bot's
    channel publish and the self-hosted /a/ article pages, so both always show
    the identical text."""
    text = strip_scaffolding(md)
    # The writer's sources block already carries the standing footer text; only
    # append the standalone footer when it is genuinely absent (avoid doubling).
    if "Drafted with AI assistance" not in text:
        text += FOOTER
    return text.replace("[contact]", contact)
