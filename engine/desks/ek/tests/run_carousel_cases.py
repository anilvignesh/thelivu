"""A belief piece becoming a carousel, end to end, without spending anything.

    python -m engine.desks.ek.tests.run_carousel_cases

No API key, no network, no Instagram, and nothing touches the live database: the
suite runs against a scratch SQLite file and hands `process_queued_carousels` a
canned composer reply, so what is exercised is the real pipeline — the real
`get_belief` branch, the real slide renderer, the real DB writes and the real
re-render the fileserver performs — with the one model call replaced. That seam
is deliberate. What a model writes on a slide is a judgement nobody can assert
about; what the engine does with it is mechanical, and mechanical is exactly what
must not drift.

Three things are checked, in the order they can fail:

1. **The brief.** A composer that never sees the spine cannot put the reel's
   narration on a slide, and one that never sees the gate's reasoning cannot put
   the desk's process there either. This is the reader-facing rule, enforced at
   the only place it can be — the input.
2. **The label.** A shape-B set carries A VIEW FROM THE RECORD on *every* slide,
   it survives the re-render the fileserver does from the DB (which is the image
   Instagram actually fetches), and a shape-A set carries none.
3. **The path.** A `desk='ek'` run goes from queued to pending_review with slides,
   a series stamp and a caption — and stops there, because posting is the human's.
"""
import os
import sys
import tempfile

# Before ANY shared.* import: shared.config reads DB_PATH at import time, and a
# suite that wrote into the real database would be the opposite of a test.
_TMP = tempfile.mkdtemp(prefix="ek_carousel_cases_")
os.environ["DB_PATH"] = os.path.join(_TMP, "scratch.db")
os.environ.setdefault("SLIDE_SERVER_BASE_URL", "https://example.invalid")

from engine.desks.ek import carousel as ek_carousel          # noqa: E402
from engine.desks.ek import draft as draft_mod               # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────
# A shape-B page in exactly the form draft.to_markdown emits, and the side-table
# row the pipeline writes beside it. The spine is a distinctive sentence that
# appears NOWHERE on the page, so "did the narration leak?" is a substring test.
SPINE_ONLY_LINE = "Everyone knows Guatemala's government collapsed on its own."

PARTS_B = {
    "headline": "The coup that was written down",
    "dek": "Guatemala 1954 is not a rumour. It is a filing cabinet.",
    "label": "This piece argues a view from the documented record.",
    "confidence": "Contested — the operation is documented; the reading of it is argued.",
    "article": ("The received account says the government fell to its own failures.\n\n"
                "The declassified PBSUCCESS file says the operation ran for a year.\n\n"
                "The strongest case against this reading is that the government was "
                "already losing the army, and the file does not settle that."),
    "sources": "1. CIA, *PBSUCCESS* files, released 1997.",
    "spine": SPINE_ONLY_LINE + "\nThe file says otherwise.",
}
PAGE_B = draft_mod.to_markdown(PARTS_B, shape="B")
BELIEF_B = {"belief": "Communist governments failed on their own.", "shape": "B",
            "label": PARTS_B["label"], "spine": PARTS_B["spine"],
            "currency": "Widely repeated in school textbooks.",
            "case_anchor": "Guatemala 1954 (PBSUCCESS).",
            "counter_case": "The army's own collapse is real and documented.",
            "so_what": "It changes who is held responsible."}

PARTS_A = dict(PARTS_B, label="", headline="A goldfish remembers for months",
               dek="The three-second memory is an invention.",
               confidence="Confirmed — two independent studies.")
PAGE_A = draft_mod.to_markdown(PARTS_A, shape="A")
BELIEF_A = {"belief": "A goldfish has a three-second memory.", "shape": "A",
            "label": "", "spine": PARTS_A["spine"]}

RUN_B = {"id": 900, "desk": "ek", "draft_text": PAGE_B, "slug": "900-the-coup",
         "throughline": BELIEF_B["belief"], "status": "published"}
RUN_A = {"id": 901, "desk": "gk", "draft_text": PAGE_A, "slug": "901-goldfish",
         "throughline": BELIEF_A["belief"], "status": "published"}

# What the composer returns. Hand-written in the skill's exact output format,
# including the trailing commentary a hosted model sometimes adds.
COMPOSED = """DARK: true
HASHTAGS: Guatemala1954 ColdWar DeclassifiedFiles PBSUCCESS History
SLIDE 1: Everyone knows Guatemala's government fell on its own.
SLIDE 2: The declassified file says the operation ran for a year.
SLIDE 3: The strongest case the other way: the army was already going.
SLIDE 4: What changes is who gets held responsible.

That should work well for the carousel.
"""

FAILS = []


def check(label, ok, detail=""):
    FAILS.append(label) if not ok else None
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail else ""))


# ── 1. the brief ─────────────────────────────────────────────────────────────

def case_brief():
    print("\nthe brief handed to the composer:")
    inp = ek_carousel.composer_input(RUN_B, BELIEF_B)
    check("the spine never reaches the composer", SPINE_ONLY_LINE not in inp,
          "the reel's narration lives on belief_pieces and must not become a slide")
    for field in ("currency", "case_anchor", "counter_case", "so_what"):
        check(f"the gate's {field.upper()} never reaches the composer",
              BELIEF_B[field] not in inp,
              "published surfaces carry zero editorial reasoning")
    check("the received belief is in the brief", BELIEF_B["belief"] in inp)
    check("the series is named", "Everyone Knows" in inp)
    check("the page is there to sequence", "PBSUCCESS file" in inp)
    check("the > [!VIEW] callout is stripped from the input", "[!VIEW]" not in inp,
          "it reaches the slides as rendered furniture, not as a sentence to quote")
    check("a shape-B brief asks for the counter-evidence",
          "ARGUES A FRAME" in inp)
    check("a shape-A brief does not",
          "ARGUES A FRAME" not in ek_carousel.composer_input(RUN_A, BELIEF_A))

    print("\nrouting and furniture:")
    check("ek routes to the belief composer",
          ek_carousel.composer_skill("ek") == "ek:carousel-composer")
    check("gk routes to the belief composer",
          ek_carousel.composer_skill("gk") == "ek:carousel-composer")
    check("news is untouched", ek_carousel.composer_skill("news") == "carousel-composer")
    check("news is untouched when desk is absent",
          ek_carousel.composer_skill(None) == "carousel-composer")
    check("ek stamps EVERYONE KNOWS", ek_carousel.slide_stamp("ek") == "EVERYONE KNOWS")
    check("gk stamps TURNS OUT", ek_carousel.slide_stamp("gk") == "TURNS OUT")
    check("a news stamp is the composer's own",
          ek_carousel.slide_stamp("news", "FACT vs ALLEGATION") == "FACT vs ALLEGATION")


# ── 2. the label ─────────────────────────────────────────────────────────────

def case_label():
    print("\nthe shape-B view marker:")
    check("shape B is labelled",
          ek_carousel.slide_label(BELIEF_B, PAGE_B) == draft_mod.REEL_VIEW_LABEL)
    check("shape A is not", ek_carousel.slide_label(BELIEF_A, PAGE_A) == "")
    check("a news piece is not", ek_carousel.slide_label(None, "# A story\n") == "")
    check("the page alone is enough to trigger it",
          ek_carousel.slide_label({}, PAGE_B) == draft_mod.REEL_VIEW_LABEL,
          "a belief row that lost its label must not cost the reader the marker")
    check("the row alone is enough to trigger it",
          ek_carousel.slide_label(BELIEF_B, "") == draft_mod.REEL_VIEW_LABEL)
    check("the caption carries the long sentence, not the pill",
          ek_carousel.caption_label(BELIEF_B, PAGE_B) == PARTS_B["label"])
    check("a shape-A caption carries no view sentence",
          ek_carousel.caption_label(BELIEF_A, PAGE_A) == "")

    cap = ek_carousel.caption(RUN_B, BELIEF_B, "https://example.invalid/a/900-the-coup",
                              "#Thelivu #ColdWar")
    check("the caption names the series", cap.startswith("EVERYONE KNOWS:"),
          "the throughline of a belief run IS the belief; unlabelled it reads as "
          "the account asserting it")
    check("the caption carries the view sentence", PARTS_B["label"] in cap)
    check("the caption links the sourced page", "/a/900-the-coup" in cap)
    check("the caption never carries the spine", SPINE_ONLY_LINE not in cap)


# ── 3. the render ────────────────────────────────────────────────────────────

def case_render():
    from publishing.slides import render_dossier_slide
    print("\nthe rendered slide:")
    plain = os.path.join(_TMP, "plain.jpg")
    marked = os.path.join(_TMP, "marked.jpg")
    render_dossier_slide("The declassified file says the operation ran for a year.",
                         stamp="2/4", dark=True, out=plain)
    render_dossier_slide("The declassified file says the operation ran for a year.",
                         stamp="2/4", dark=True, out=marked,
                         label=draft_mod.REEL_VIEW_LABEL)
    a, b = open(plain, "rb").read(), open(marked, "rb").read()
    check("a labelled slide renders", len(b) > 10_000)
    check("the marker actually changes the image", a != b,
          "the only way to tell the pill was drawn without reading pixels by eye")


# ── 4. the whole path ────────────────────────────────────────────────────────

def case_pipeline():
    print("\nqueued → composed → pending_review (scratch DB, canned composer):")
    from shared import db as sdb
    from engine.agents import orchestrator

    sdb.init_db()
    run_id = sdb.save_run(video_id=None, source="Everyone Knows (belief desk)",
                          throughline=BELIEF_B["belief"], trust_gate="READY-FOR-HUMAN",
                          status="published", desk="ek")
    sdb.update_run(run_id, draft_text=PAGE_B)
    sdb.save_belief_parts  # noqa: B018 — referenced so a rename here fails loudly
    conn = sdb._conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO belief_pieces (run_id, belief, shape, currency, "
                    "case_anchor, counter_case, so_what, spine, label) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, BELIEF_B["belief"], "B", BELIEF_B["currency"],
                     BELIEF_B["case_anchor"], BELIEF_B["counter_case"],
                     BELIEF_B["so_what"], BELIEF_B["spine"], BELIEF_B["label"]))
        conn.commit()
    finally:
        conn.close()
    cid = sdb.queue_carousel_run(run_id, article_url="https://example.invalid/a/x")

    # The two things this suite refuses to do for real: spend a model call, and
    # talk to Telegram. Everything between them is the shipping code.
    seen = {}

    def fake_skill(skill, text, **kw):
        seen["skill"], seen["input"] = skill, text
        return COMPOSED

    orig_skill = orchestrator.run_structured_skill
    orig_tg = orchestrator._tg_post_media_group
    orchestrator.run_structured_skill = fake_skill
    orchestrator._tg_post_media_group = lambda *a, **k: 1
    try:
        orchestrator.process_queued_carousels()
    finally:
        orchestrator.run_structured_skill = orig_skill
        orchestrator._tg_post_media_group = orig_tg

    check("the belief composer ran, not the news one",
          seen.get("skill") == "ek:carousel-composer", f"ran {seen.get('skill')!r}")
    check("the spine did not reach it", SPINE_ONLY_LINE not in (seen.get("input") or ""))

    cr = sdb.get_carousel_run(cid)
    slides = sdb.get_carousel_slides(cid)
    check("the carousel is at review, not posted", cr["status"] == "pending_review",
          f"status={cr['status']!r} — the post tap is the human's and this suite never takes it")
    check("four slides were rendered and stored", len(slides) == 4, f"{len(slides)} slides")
    check("slide 1 is the belief", slides[0]["headline"].startswith("Everyone knows"))
    check("the series stamp was applied", cr["stamp"] == "EVERYONE KNOWS",
          f"stamp={cr['stamp']!r}")
    check("the view label is persisted on the carousel",
          (cr["view_label"] or "") == draft_mod.REEL_VIEW_LABEL)
    check("the caption names the series", (cr["caption"] or "").startswith("EVERYONE KNOWS:"))
    check("the caption never carries the spine", SPINE_ONLY_LINE not in (cr["caption"] or ""))
    check("every slide file exists on disk",
          all(os.path.isfile(s["image_path"]) for s in slides))

    # The fileserver re-renders from the DB — that render, not the one above, is
    # what Instagram fetches when the cached file is gone or an edit forced it.
    print("\n  the re-render the fileserver does from the DB:")
    for pos in (1, len(slides)):
        d = sdb.get_slide_render_data(cid, pos)
        check(f"slide {pos} re-render carries the marker",
              (d or {}).get("view_label") == draft_mod.REEL_VIEW_LABEL,
              "without this the label lives only in the first render and vanishes "
              "the moment a slide is re-rendered")

    for s in slides:                       # scratch renders, not the repo's slides dir
        try:
            os.unlink(s["image_path"])
        except OSError:
            pass


def main():
    case_brief()
    case_label()
    case_render()
    case_pipeline()
    if FAILS:
        print(f"\n{len(FAILS)} case(s) FAILED:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("\nall carousel cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
