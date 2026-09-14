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


# How far above and below a matched line to take, in PDF points. A figure on its
# own proves nothing — "30,308.52" is a number until you can see the row label
# and the column head next to it. 90pt is roughly six lines of an audit report.
BAND_POINTS = 90
# Breathing room around the crop so the excerpt does not look guillotined.
CROP_PAD_POINTS = 14
# Below this the crop is a fragment, not a readable excerpt, and the whole page
# is the more honest thing to show.
MIN_CROP_POINTS = 40


def locate(pdf_path, needle, dpi=DEFAULT_DPI):
    """Where in a PDF a figure actually appears. [(page, (x0,y0,x1,y1))] in points.

    Anil, 2026-09-14: *"what we are looking for is not like a subtitle right.
    Materials related to the audio should be shown on the page... we can show
    the official table of the collections pending on the screen when 30308 is
    told."*

    That is the difference between a data card and evidence. A card restates the
    number in our own typography and asks to be believed; this finds the number
    IN THE DOCUMENT and puts that on screen, so the row label and the column
    head are visible next to it and a viewer can read the claim themselves.

    The box returned is a BAND, not the matched line. A figure alone proves
    nothing — what makes it evidence is the context printed around it — so the
    lines above and below come too.
    """
    from engine.digger.fetch import _new_parser

    needle = _norm(needle)
    if not needle:
        return []
    lp = _new_parser()
    try:
        result = lp.parse(str(pdf_path) if not hasattr(pdf_path, "read")
                          else pdf_path.read())
    except Exception as e:                                  # noqa: BLE001
        log.info("could not parse %s to locate %r: %s", pdf_path, needle, e)
        return []
    finally:
        try:
            lp.close()
        except Exception:
            pass

    out = []
    for page in getattr(result, "pages", None) or []:
        items = [t for t in (getattr(page, "text_items", None) or [])
                 if (getattr(t, "text", "") or "").strip()]
        hits = [t for t in items if needle in _norm(t.text)]
        if not hits:
            continue
        hit = hits[0]
        band = [t for t in items
                if hit.y - BAND_POINTS <= t.y <= hit.y + BAND_POINTS]
        if not band:
            band = [hit]
        box = (min(t.x for t in band),
               min(t.y for t in band),
               max(t.x + t.width for t in band),
               max(t.y + t.height for t in band))
        out.append((page.page_num, box))
    return out


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def excerpt(pdf_path, needle, out_dir, stem="excerpt", dpi=DEFAULT_DPI):
    """The region of the real document where `needle` appears, as a PNG.

    Returns {"path", "page", "cropped"} or None. `cropped` is False when the
    figure was found but the band was too small to be worth cutting to — the
    whole page goes up instead, which is less striking and never misleading.

    Cropping is allowed (see the module docstring) precisely because it does not
    change what the page SAYS. Anything that would — redrawing, retyping,
    rearranging — is not this function's business and never will be.
    """
    found = locate(pdf_path, needle, dpi=dpi)
    if not found:
        log.info("%r does not appear in %s — no excerpt", needle, pdf_path)
        return None
    page_no, (x0, y0, x1, y1) = found[0]

    shots = render_pages(pdf_path, [page_no], out_dir, stem=stem, dpi=dpi)
    if not shots:
        return None
    _p, page_png = shots[0]

    from PIL import Image
    im = Image.open(page_png)
    # liteparse reports geometry in POINTS and renders in PIXELS; the ratio is
    # dpi/72 but is taken from the image so a renderer that rounds differently
    # cannot silently shift every crop.
    from engine.digger.fetch import _new_parser
    lp = _new_parser()
    try:
        pw = lp.parse(str(pdf_path)).pages[page_no - 1].width
    except Exception:                                       # noqa: BLE001
        pw = im.width * 72.0 / dpi
    finally:
        try:
            lp.close()
        except Exception:
            pass

    if (y1 - y0) < MIN_CROP_POINTS:
        return {"path": page_png, "page": page_no, "cropped": False}

    sc = im.width / float(pw or 1)
    box = (max(0, int((x0 - CROP_PAD_POINTS) * sc)),
           max(0, int((y0 - CROP_PAD_POINTS) * sc)),
           min(im.width, int((x1 + CROP_PAD_POINTS) * sc)),
           min(im.height, int((y1 + CROP_PAD_POINTS) * sc)))
    if box[2] - box[0] < 80 or box[3] - box[1] < 40:
        return {"path": page_png, "page": page_no, "cropped": False}

    crop_path = os.path.join(out_dir, f"{stem}_p{page_no}_crop.png")
    im.crop(box).save(crop_path)
    log.info("excerpt %r -> %s page %s, %dx%d px", needle, crop_path, page_no,
             box[2] - box[0], box[3] - box[1])
    return {"path": crop_path, "page": page_no, "cropped": True}


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
