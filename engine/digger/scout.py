"""The scout: finds sources, and keeps the ones we have honest.

Two jobs, and the second is the one that was missing.

**VERIFY.** Re-check every active source on a schedule, because a source that
stops working does not raise an error — it produces plausible nothing. The index
fetches, the extractor reads, the cycle logs "0 candidate(s)" and sleeps, which
is also exactly what a healthy source looks like on a quiet day. On 2026-09-14
four of nine targets turned out to have produced ZERO candidates in every run
they had ever made: `cag-reports` was pointed at a listing whose PDFs are the
whistleblower policy and a training compendium, and `cag-press-releases` had no
link pattern at all and had been reading "About the CAG of India" once an hour
for weeks. Nothing was broken in a way anything could see.

`barren_targets()` could already answer the question. What was missing is that
nobody was asking it on a schedule, and nothing was written down — so "this has
been dead for six days" was an inference from a week of journal instead of a
query. This module asks, on a schedule, and writes the answer to `source_checks`.

**FIND.** Given a jurisdiction's seed domains, locate document indexes —
including the JS-shell shape, where the documents are not in the markup at all
(see `apiscan.py`).

---

**The hard boundary: the scout PROPOSES. It never activates.**

`discover.py` already states the reasoning — *a bad story gets caught at the
verification gate, but a bad source, once trusted, quietly shapes every story
that flows through it.*

The same holds in the other direction, which is less obvious and is why this
module refuses to deactivate anything: a source that looks dead may be a source
whose documents outgrew the digger's window (`referred_targets()` — on
2026-09-19 thirty-three targets reported barren and every one was pointed at
exactly the right place). Dropping a good source silently narrows what we can
ever see, and nothing downstream would ever report the absence. So the scout
raises `needs_review` and a person decides. Both directions of that gate are a
person's call.
"""

import logging
import re
from datetime import datetime, timezone

from engine.digger import apiscan, discover, fetch, robots, targets

log = logging.getLogger("digger.scout")

# A source is barren after this many runs with documents read and nothing found.
# Matches barren_targets()'s own default so the two agree about the word.
BARREN_MIN_RUNS = 5

VERDICTS = ("ok", "barren", "unreachable", "refused")


def verify_source(target, barren_keys=None, referred_keys=None, record=True):
    """Check one active source and record the verdict. Never raises.

    The four verdicts are not severity levels, they are different situations:

      ok           fetches, yields documents
      refused      robots.txt or a bot wall says no. NOT a fault. An answer.
      unreachable  we cannot get the index at all — a URL to fix
      barren       we can read it, and it has never yielded anything — the
                   silent failure, and the reason this job exists

    `refused` is deliberately not an alarm. Treating a robots.txt refusal as a
    breakage is how a crawler ends up being 'fixed' into ignoring one.
    """
    key = target.get("key") or "?"
    out = {"key": key, "verdict": "ok", "robots_ok": None, "fetch_ok": None,
           "doc_links": None, "detail": "", "checked_at":
           datetime.now(timezone.utc).isoformat()}

    # A dataset target has no index to fetch — it is typed rows through an API,
    # watched by arithmetic. Verifying it means asking whether the rows still
    # arrive, which dataset_watch already does per cycle.
    if target.get("kind") == "dataset":
        out["verdict"] = "ok"
        out["detail"] = "dataset target — verified per cycle by dataset_watch"
        if record:
            _record(out)
        return out

    index_url = target.get("index_url")
    if not index_url:
        out["verdict"] = "unreachable"
        out["detail"] = "no index_url"
        if record:
            _record(out)
        return out

    try:
        out["robots_ok"] = robots.allowed(index_url)
    except Exception as e:                                      # noqa: BLE001
        log.debug("robots check failed for %s: %s", index_url, e)
    if out["robots_ok"] is False:
        out["verdict"] = "refused"
        out["detail"] = "robots.txt disallows this crawler"
        if record:
            _record(out)
        return out

    try:
        items = fetch.fetch_index(index_url, target.get("link_pattern"))
        out["fetch_ok"] = True
        out["doc_links"] = len(items)
    except fetch.FetchError as e:
        out["fetch_ok"] = False
        out["verdict"] = "unreachable"
        out["detail"] = str(e)[:400]
        if record:
            _record(out)
        return out
    except Exception as e:                                      # noqa: BLE001
        out["fetch_ok"] = False
        out["verdict"] = "unreachable"
        out["detail"] = f"{type(e).__name__}: {e}"[:400]
        if record:
            _record(out)
        return out

    if out["doc_links"] < discover.MIN_DOC_LINKS:
        # Reaching the page and finding no documents on it is the RBI shape:
        # navigation chrome with the records loaded by JS. Worth saying which
        # it is, because the fix is apiscan, not a new URL.
        out["verdict"] = "barren"
        out["detail"] = (f"index yielded {out['doc_links']} document link(s) — "
                         "a JS-rendered listing or the wrong URL")
        if record:
            _record(out)
        return out

    if barren_keys and key in (barren_keys or ()):
        if key in (referred_keys or ()):
            out["verdict"] = "ok"
            out["detail"] = ("finds nothing here, but its documents were "
                             "referred to the corpus — working as intended")
        else:
            out["verdict"] = "barren"
            out["detail"] = (f"index yields {out['doc_links']} documents but the "
                             f"last {BARREN_MIN_RUNS}+ runs found nothing — "
                             "reading the wrong documents")
        if record:
            _record(out)
        return out

    out["detail"] = f"{out['doc_links']} document link(s)"
    if record:
        _record(out)
    return out


def verify_all(target_list=None, record=True):
    """Check every active source. Returns {'checks': [...], 'needs_review': [...]}.

    The two signals are combined here rather than separately because they
    answer different halves of one question: `fetch_index` says whether we can
    still READ the source, `barren_targets()` says whether reading it has ever
    been worth anything. A source can pass either alone and still be useless.
    """
    from shared import db

    try:
        barren_keys = {k for k, _runs, _docs in db.barren_targets(
            min_runs=BARREN_MIN_RUNS)}
    except Exception as e:                                      # noqa: BLE001
        log.warning("barren_targets unavailable: %s", e)
        barren_keys = set()
    try:
        referred_keys = set(db.referred_targets() or {})
    except Exception:                                           # noqa: BLE001
        referred_keys = set()

    tl = target_list if target_list is not None else targets.active_targets()
    checks = [verify_source(t, barren_keys, referred_keys, record=record)
              for t in tl]
    needs_review = [c for c in checks if c["verdict"] in ("barren", "unreachable")]
    return {"checks": checks, "needs_review": needs_review,
            "ok": sum(1 for c in checks if c["verdict"] == "ok"),
            "refused": sum(1 for c in checks if c["verdict"] == "refused")}


# ── Finding new sources ─────────────────────────────────────────────────────

def examine(index_url, name=None, brief=None, link_pattern=None, propose=False):
    """Look at one candidate index every way we know how, and report.

    Tries the plain shape first (`discover.validate` — an HTML index of document
    links) and falls back to the JS-shell shape (`apiscan.discover`). That order
    is not arbitrary: a source that serves plain links needs no endpoint hunt,
    and probing a dozen URLs on a government server to learn something its HTML
    already said is rude as well as slow.
    """
    out = {"index_url": index_url, "name": name or index_url,
           "shape": None, "evidence": None, "api": None, "proposed": False}

    ev = discover.validate(index_url, link_pattern, brief)
    out["evidence"] = ev
    if ev.get("ok"):
        out["shape"] = "index"
    else:
        api = apiscan.discover(index_url)
        out["api"] = api
        if api.get("endpoints"):
            out["shape"] = "api"
        else:
            out["shape"] = "none"

    if propose and out["shape"] in ("index", "api"):
        if not brief:
            raise ValueError("a proposal needs a brief — what to extract from "
                             "its documents")
        url = (out["api"]["endpoints"][0]["url"] if out["shape"] == "api"
               else index_url)
        discover.propose(url, out["name"], brief, link_pattern=link_pattern,
                         proposed_by="scout")
        out["proposed"] = True
    return out


# Words that mark a link as a LISTING of records rather than a page about the
# organisation. Kept here rather than in the jurisdiction file because none of
# them is about India — every government publishing platform uses this
# vocabulary, and a second country inherits it for free.
INDEX_HINTS = (
    "audit-report", "audit_report", "auditreport", "annual-report",
    "publication", "document", "press-release", "pressrelease", "press_release",
    "notification", "circular", "order", "dataset", "catalog", "catalogue",
    "rti", "question", "report", "download", "archive", "statistic",
)
# Pages that look like listings and are not: the organisation talking about
# itself. `cag-press-releases` spent weeks reading "About the CAG of India".
INDEX_ANTI_HINTS = ("about", "contact", "career", "tender", "recruit",
                    "sitemap", "privacy", "disclaimer", "feedback", "login")
# A DOCUMENT is not an index, and the hint words match both.
#
# Found live on 2026-09-20: the first run of this scorer against cag.gov.in
# returned six press-release PDFs and not one listing page, because
# "PR-Press-release-report-no-21-GPFR-2023-24.pdf" scores higher on the same
# vocabulary than the page that links to it. Every one of those would then have
# been probed as an index, failed validation, and the host would have been
# reported as having no sources — a confident wrong answer about our single
# most important domain.
_DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                      ".zip", ".csv", ".jpg", ".png")
_DOCUMENT_PATHS = ("/uploads/", "/upload/", "/files/", "/attachment")
# How many candidate paths are worth probing per host. Each one is a request to
# a government server, and a root page can carry two hundred links.
MAX_CANDIDATES_PER_HOST = 6


def index_candidates(host_url, limit=MAX_CANDIDATES_PER_HOST):
    """Paths on one host that look like listings of records, best first.

    A portal's ROOT is almost never the index — `cag.gov.in` is a homepage, and
    the audit reports are four paths down at `/ag1/kerala/en/audit-report`. A
    sweep that only examined the seed URL would correctly report "no documents
    here" about every worthwhile source in the jurisdiction file.

    Scored on the URL and the link text together, because a government portal
    labels the same page differently in its navigation than in its path.
    """
    from engine.digger import apiscan

    try:
        html, _ctype, final = apiscan._get_raw(host_url)
    except apiscan._RawFetchError as e:
        raise RuntimeError(str(e)) from e

    scored = []
    for link in fetch.extract_links(html, final):
        url = link["url"]
        blob = f"{url} {link.get('title', '')}".lower()
        if any(bad in blob for bad in INDEX_ANTI_HINTS):
            continue
        if _host(url) != _host(final):
            continue
        path = url.split("?")[0].lower()
        if path.endswith(_DOCUMENT_SUFFIXES) or any(p in path for p in _DOCUMENT_PATHS):
            continue
        hits = sum(1 for hint in INDEX_HINTS if hint in blob)
        if not hits:
            continue
        # SHALLOWER wins, and a path ending in a record id loses.
        #
        # The first version preferred depth, on the reasoning that a listing
        # sits below a section front page. Live against cag.gov.in that ranked
        # `/en/audit-report/details/31829` — ONE report from 2017 — above
        # `/en/audit-report`, the page listing all of them. A detail page
        # validates as a document and yields a single record, so the sweep
        # would have proposed the narrowest possible view of the best source we
        # have.
        depth = url.rstrip("/").count("/")
        looks_like_a_record = 1 if re.search(r"/(?:details?|view|show)?/?\d{3,}/?$",
                                             url) else 0
        scored.append((-hits, looks_like_a_record, depth, url,
                       link.get("title", "")))
    scored.sort()

    out, seen = [], set()
    for _hits, _rec, _depth, url, title in scored:
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": title})
        if len(out) >= limit:
            break
    return out


def sweep(jurisdiction_key=None, limit=None, propose=False,
          per_host=MAX_CANDIDATES_PER_HOST):
    """Walk a jurisdiction's seed portals, find the listings, report what they are.

    Deliberately NOT a crawler: one page deep from a host a person already wrote
    down, and only links that look like listings of records. The plan's rule
    holds throughout — a domain in `portals` is a place to look, not a trusted
    source, and `propose` records proposals that a person still has to activate.
    """
    from shared import jurisdiction as juris

    j = juris.load(jurisdiction_key)
    known = {t.get("index_url") for t in targets.active_targets()}
    results = []
    for portal in (j.portals[:limit] if limit else j.portals):
        host = portal.get("host")
        if not host:
            continue
        root = f"https://{host}"
        try:
            cands = index_candidates(root, limit=per_host)
        except Exception as e:                                  # noqa: BLE001
            results.append({"index_url": root, "host": host, "shape": "error",
                            "error": str(e)[:300]})
            continue
        # The root itself is worth one look when nothing below it looked like a
        # listing — some portals ARE a single listing page.
        for cand in (cands or [{"url": root, "title": host}]):
            if cand["url"] in known:
                continue
            try:
                res = examine(cand["url"],
                              name=f"{j.name} — {cand.get('title') or host}",
                              brief=portal.get("what"), propose=propose)
            except Exception as e:                              # noqa: BLE001
                res = {"index_url": cand["url"], "shape": "error",
                       "error": str(e)[:300]}
            res["host"] = host
            results.append(res)
    found = [r for r in results if r.get("shape") in ("index", "api")]
    return {"jurisdiction": j.key, "examined": len(results),
            "found": len(found), "results": results}


def _host(url):
    from urllib.parse import urlparse
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


# ── The scheduled job ───────────────────────────────────────────────────────

def run_scout_cycle(notify=True, do_sweep=False):
    """Verify every active source, record the checks, report what needs a person.

    Returns a summary dict. Reports through the same digest everything else
    uses rather than inventing a channel — a signal nobody is subscribed to is
    the failure this job was built to end.
    """
    from shared import db

    started = datetime.now(timezone.utc)
    result = verify_all()
    summary = {
        "checked": len(result["checks"]),
        "ok": result["ok"],
        "refused": result["refused"],
        "needs_review": [c["key"] for c in result["needs_review"]],
        "started_at": started.isoformat(),
    }

    if do_sweep:
        try:
            summary["sweep"] = sweep()
        except Exception as e:                                  # noqa: BLE001
            summary["sweep_error"] = str(e)[:300]

    try:
        db.kv_set("last_digger_scout_at", started.isoformat())
    except Exception as e:                                      # noqa: BLE001
        log.warning("could not stamp last_digger_scout_at: %s", e)

    if result["needs_review"]:
        lines = [f"{c['key']}: {c['verdict']} — {c['detail']}"
                 for c in result["needs_review"]]
        body = "\n".join(lines)
        log.warning("scout: %d source(s) need review\n%s",
                    len(lines), body)
        try:
            db.record_event("scout", f"{len(lines)} source(s) need review",
                            body=body, level="warn")
        except Exception as e:                                  # noqa: BLE001
            log.warning("could not record scout event: %s", e)
        if notify:
            try:
                from shared import notify as notifier
                notifier.send(
                    f"🔎 Scout: {len(lines)} source(s) need review\n\n{body}\n\n"
                    "Nothing was deactivated — that is your call.")
            except Exception as e:                              # noqa: BLE001
                log.warning("could not notify: %s", e)
    else:
        log.info("scout: %d sources checked, all reading",
                 summary["checked"])
    return summary


def _record(check):
    from shared import db
    try:
        db.record_source_check(
            check["key"], check["verdict"], robots_ok=check.get("robots_ok"),
            fetch_ok=check.get("fetch_ok"), doc_links=check.get("doc_links"),
            detail=check.get("detail"))
    except Exception as e:                                      # noqa: BLE001
        log.warning("could not record check for %s: %s", check["key"], e)


def describe(check):
    """One line, for a log or the command center."""
    mark = {"ok": "OK  ", "barren": "DEAD", "unreachable": "GONE",
            "refused": "NO  "}.get(check["verdict"], "?   ")
    return f"{mark} {check['key']:26s} {check.get('detail','')[:90]}"
