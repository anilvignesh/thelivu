"""The scout — verifying sources, and finding the ones that hide their API.

    python -m shared.tests.run_scout_cases

No API key, no network, no browser: `fetch` and `robots` are stubbed, so the DB
writes are real and nothing leaves the machine.

What this is FOR, in order of how much it would cost to lose:

1. **The scout never activates, and never deactivates.** A source, once
   trusted, quietly shapes every story that flows through it — that rule is
   already in `discover.py`. The reverse matters just as much and is easier to
   get wrong: on 2026-09-19 thirty-three targets reported barren and every one
   was pointed at exactly the right source, their documents simply too long for
   the digger's window. A scout that "cleaned up" dead sources would have
   deleted the best thirty-three we have, and nothing downstream would ever
   have reported the absence.

2. **A refusal is not a breakage.** robots.txt saying no gets its own verdict,
   because filing it beside a broken fetch invites someone to "fix" it.

3. **A source that stops working must produce a ROW, not a silence.** The whole
   reason this module exists is that four of nine targets had produced zero
   candidates in their entire history and the only thing that noticed was a
   person asking by hand.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from engine.digger import apiscan, fetch, robots, scout   # noqa: E402
from shared.db import (                                   # noqa: E402
    init_db, digger_targets, source_checks, source_health,
)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ── stubs ───────────────────────────────────────────────────────────────────
# Keyed by URL so one fake world serves every case.

WORLD = {
    "https://good.example/index":   [{"url": f"https://good.example/{i}.pdf"}
                                     for i in range(9)],
    "https://empty.example/index":  [],                    # JS shell / wrong URL
    "https://gone.example/index":   fetch.FetchError("HTTP 404"),
    "https://refused.example/index": None,                 # robots says no
}


def fake_fetch_index(url, pattern=None, timeout=None):
    item = WORLD.get(url)
    if isinstance(item, Exception):
        raise item
    return item or []


def fake_allowed(url, user_agent=None):
    return not url.startswith("https://refused.example")


def target(key, url, **kw):
    d = {"key": key, "name": key, "index_url": url,
         "link_pattern": r"\.pdf$", "brief": "records"}
    d.update(kw)
    return d


def main():
    print("scout")
    init_db()
    fetch.fetch_index = fake_fetch_index
    robots.allowed = fake_allowed

    tl = [
        target("healthy", "https://good.example/index"),
        target("js-shell", "https://empty.example/index"),
        target("vanished", "https://gone.example/index"),
        target("polite-no", "https://refused.example/index"),
        {"key": "a-dataset", "kind": "dataset", "name": "rows", "brief": "rows"},
    ]

    # ── 1. the four verdicts are four different situations ──────────────────
    res = scout.verify_all(tl)
    by = {c["key"]: c for c in res["checks"]}
    check("a working source reads ok", by["healthy"]["verdict"] == "ok",
          by["healthy"]["detail"])
    check("an index with no documents is barren",
          by["js-shell"]["verdict"] == "barren", by["js-shell"]["detail"])
    check("it says WHICH kind of barren",
          "JS-rendered" in by["js-shell"]["detail"], by["js-shell"]["detail"])
    check("an unfetchable index is unreachable",
          by["vanished"]["verdict"] == "unreachable", by["vanished"]["detail"])
    check("robots.txt gets its own verdict",
          by["polite-no"]["verdict"] == "refused", by["polite-no"]["detail"])
    check("a refusal is not listed as needing review",
          "polite-no" not in [c["key"] for c in res["needs_review"]])
    check("a dataset target is not judged by index links",
          by["a-dataset"]["verdict"] == "ok", by["a-dataset"]["detail"])

    # ── 2. the check is WRITTEN DOWN, which is the point ────────────────────
    rows = source_checks()
    check("every source produced a row", len(rows) == len(tl), str(len(rows)))
    check("a dead source is a row with a date on it",
          all(r["checked_at"] for r in rows))
    health = source_health()
    check("health is ordered by consequence",
          [h["verdict"] for h in health][:2] == ["unreachable", "barren"],
          str([h["verdict"] for h in health]))
    check("a refusal sorts below the faults, not among them",
          [h["verdict"] for h in health].index("refused") >
          [h["verdict"] for h in health].index("barren"))

    # ── 3. barren history: reads fine, finds nothing, EVER ──────────────────
    res2 = scout.verify_all([target("busy-but-useless", "https://good.example/index")],
                            record=False)
    check("a readable source with no history is not condemned",
          res2["checks"][0]["verdict"] == "ok")
    res3 = [scout.verify_source(target("busy-but-useless", "https://good.example/index"),
                                barren_keys={"busy-but-useless"}, record=False)]
    check("a readable source that never finds anything is barren",
          res3[0]["verdict"] == "barren", res3[0]["detail"])
    res4 = [scout.verify_source(target("long-docs", "https://good.example/index"),
                                barren_keys={"long-docs"},
                                referred_keys={"long-docs"}, record=False)]
    check("a source whose documents went to the corpus is NOT barren",
          res4[0]["verdict"] == "ok", res4[0]["detail"])

    # ── 4. the hard boundary ────────────────────────────────────────────────
    before = {t["key"] for t in digger_targets(status="active")}
    scout.run_scout_cycle(notify=False)
    after = {t["key"] for t in digger_targets(status="active")}
    check("a scout cycle activates nothing", before == after, str(after - before))
    check("a scout cycle deactivates nothing", before == after, str(before - after))

    # ── 5. finding an API nobody advertised ─────────────────────────────────
    html = """<html><body><div id=app></div>
      <script>const r = await fetch("/api_ls/question/qetFilteredQuestionsAns");</script>
      <script src="https://sansad.in/static/bundle.js"></script>
      <script src="https://cdn.jsdelivr.net/npm/react/react.js"></script>
      <a data-api="/services/records.json">records</a>
      <img src="/assets/logo.png"><link href="/x.css">
      </body></html>"""
    mined = apiscan.mine(html, "https://sansad.in/ls/questions")
    check("the endpoint written in the page is found",
          "https://sansad.in/api_ls/question/qetFilteredQuestionsAns" in mined,
          str(mined))
    check("a data-api attribute counts too",
          "https://sansad.in/services/records.json" in mined, str(mined))
    check("images and stylesheets are not probed",
          not any(u.endswith((".png", ".css")) for u in mined), str(mined))
    bundles = apiscan.bundles(html, "https://sansad.in/ls/questions")
    check("the site's own bundle is worth mining",
          bundles == ["https://sansad.in/static/bundle.js"], str(bundles))
    check("a CDN's copy of react is not", "jsdelivr" not in " ".join(bundles))

    # ── 5b. a portal root is not the index ──────────────────────────────────
    # cag.gov.in is a homepage; the audit reports are four paths down. A sweep
    # that examined only the seed URL would report "no documents here" about
    # every worthwhile source in the jurisdiction file.
    portal = """<html><body>
      <a href="/en/about-us">About the CAG of India</a>
      <a href="/ag1/kerala/en/audit-report">Audit Reports</a>
      <a href="/en/press-release">Press Releases</a>
      <a href="/careers">Careers at CAG</a>
      <a href="https://elsewhere.example/reports">Someone else's reports</a>
      </body></html>"""
    apiscan._get_raw = lambda url, timeout=30: (portal, "text/html",
                                                "https://cag.gov.in/")
    cands = [c["url"] for c in scout.index_candidates("https://cag.gov.in")]
    check("the listing below the homepage is found",
          "https://cag.gov.in/ag1/kerala/en/audit-report" in cands, str(cands))
    check("an About page is not mistaken for a listing",
          not any("about" in c for c in cands), str(cands))
    check("careers pages are skipped", not any("career" in c for c in cands))
    check("another host's links are not followed",
          not any("elsewhere.example" in c for c in cands), str(cands))

    # ── 6. typed rows, not a page that says 200 ─────────────────────────────
    check("a JSON array is rows", apiscan._json_rows('[1,2,3,4]') == 4)
    check("rows one level down are found",
          apiscan._json_rows('{"records":[1,2,3]}') == 3)
    check("an HTML error page is not JSON", apiscan._sniff("<html>oops") is None)

    # ── 7. could-not-look is never reported as found-nothing ────────────────
    try:
        apiscan.browser_watch("https://sansad.in/ls/questions")
        check("browser tier either works or says it cannot", True,
              "playwright is installed here")
    except apiscan.ApiscanUnavailable as e:
        check("browser tier says plainly that it cannot look",
              "playwright" in str(e).lower(), str(e))
    except Exception as e:                                      # noqa: BLE001
        check("browser tier says plainly that it cannot look", False,
              f"{type(e).__name__}: {e}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all scout cases passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            os.unlink(_TMPDB.name)
        except OSError:
            pass
