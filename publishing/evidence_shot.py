"""Putting the actual record on screen.

Anil, 2026-09-11: "can we get some real images or facts... show screenshots from
reports on the mix?" Yes, and it is the strongest visual this desk has.

**This is a different asset class from an illustration, and the difference is
the whole point.** BRAND.md forbids images that could be mistaken for evidence,
and forbids lettering in generated images. A rendered page of a parliamentary
answer inverts both rules rather than breaking them: it is not an image that
might be mistaken for evidence, it *is* the evidence, and its text is the reason
to show it. An illustration says "imagine a ledger"; this says "here is the
ledger, read line twelve."

So the two never mix in one frame. An IMAGE line is generated and symbolic. A
RECORD line is a page of a real document, unretouched, captioned with what it is
and where it came from. Cropping to the relevant table is allowed; anything that
changes what the page says is not.

Rendering is liteparse's `screenshot()`, which is already installed for text
extraction, so this costs no new dependency. **Pages are 1-indexed** — passing 0
raises "page 0 out of range", which reads like an empty document and is not.

What this does NOT do: fetch photographs from the open web. A picture of a
collapsed flyover from a search result carries no provenance, no licence and no
guarantee it is the right flyover, and Thelivu's whole product is not being
wrong about what a record shows. Real photographs need a real source with rights
attached, which is a separate decision.
"""

import logging
import os
import re

log = logging.getLogger("evidence_shot")

DEFAULT_DPI = 150            # legible on a phone without producing huge PNGs
MAX_PAGES_PER_DOC = 4        # a video holds a handful of pages, not a report


class EvidenceShotError(RuntimeError):
    pass


def _parser(dpi=DEFAULT_DPI):
    """A fresh parser per call, closed by the caller — same reason as
    fetch.pdf_to_text: letting liteparse reach __del__ at interpreter shutdown
    core-dumps the process."""
    import liteparse
    return liteparse.LiteParse(ocr_enabled=False, num_workers=1, pool_size=1,
                               quiet=True, dpi=dpi, parse_timeout=90)


def render_pages(pdf_path, pages, out_dir, stem="record", dpi=DEFAULT_DPI):
    """Render 1-indexed `pages` of a PDF to PNGs. Returns [(page, path)].

    Pages are 1-INDEXED. liteparse raises "page 0 out of range (document has N
    pages)" for 0, which reads like an empty or broken document and is neither.
    """
    pages = [int(p) for p in pages if int(p) >= 1][:MAX_PAGES_PER_DOC]
    if not pages:
        raise EvidenceShotError("no valid page numbers — pages are 1-indexed")
    os.makedirs(out_dir, exist_ok=True)

    try:
        lp = _parser(dpi)
    except ImportError as e:
        raise EvidenceShotError("liteparse is not installed on this host") from e

    out = []
    try:
        for shot in lp.screenshot(str(pdf_path), page_numbers=pages):
            path = os.path.join(out_dir, f"{stem}_p{shot.page_num}.png")
            with open(path, "wb") as f:
                f.write(shot.image_bytes)
            out.append((shot.page_num, path))
            log.info("rendered %s page %s -> %s (%dx%d)",
                     stem, shot.page_num, path, shot.width, shot.height)
    except Exception as e:
        raise EvidenceShotError(f"render failed: {type(e).__name__}: {e}") from e
    finally:
        try:
            lp.close()
        except Exception:
            pass
    if not out:
        raise EvidenceShotError("no pages rendered")
    return out


def find_pages(pdf_text_by_page, needle):
    """Which 1-indexed pages contain `needle`?

    Used to put the RIGHT page on screen rather than the first: a viewer shown
    page one of a five-page answer while the narration quotes the annexure has
    been given a prop, not evidence.
    """
    if not needle:
        return []
    norm = lambda s: re.sub(r"\s+", " ", s or "").lower()
    n = norm(needle)
    return [i for i, text in enumerate(pdf_text_by_page, 1) if n in norm(text)]


def caption_for(source_url, description, page=None):
    """The on-screen line that makes a rendered page checkable.

    A screenshot with no citation is decoration. The caption has to say what the
    document is and where it came from, so a viewer can go and read it — which
    is the entire reason to show a record rather than draw one.
    """
    bits = [description.strip().rstrip(".")]
    if page:
        bits.append(f"p.{page}")
    host = re.sub(r"^https?://(www\.)?", "", source_url or "").split("/")[0]
    if host:
        bits.append(host)
    return " — ".join(b for b in bits if b)


def from_source(pdf_path, out_dir, source_url, description, quote=None,
                pdf_text_by_page=None, stem="record", dpi=DEFAULT_DPI):
    """Render the page(s) that actually carry `quote`, captioned.

    Returns [{page, path, caption}]. Falls back to page 1 when the quote cannot
    be located, and says so, because silently showing the wrong page is worse
    than showing the first and admitting it.
    """
    pages, located = [], True
    if quote and pdf_text_by_page:
        pages = find_pages(pdf_text_by_page, quote)
    if not pages:
        pages, located = [1], bool(quote and pdf_text_by_page)
        if quote and pdf_text_by_page:
            log.warning("quote not found in %s; falling back to page 1", stem)
            located = False

    shots = render_pages(pdf_path, pages, out_dir, stem=stem, dpi=dpi)
    return [{
        "page": pg,
        "path": path,
        "caption": caption_for(source_url, description, pg),
        "shows_quote": located,
    } for pg, path in shots]
