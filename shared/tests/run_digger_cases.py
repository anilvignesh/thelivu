"""Tier-0 digger — grounding, parsing and cross-check behaviour.

    python -m shared.tests.run_digger_cases

No API key, no network, no production database: a throwaway SQLite file and
fixture documents, so the DB writes are real but nothing else is.

What it is FOR is the one property that makes this tier safe to run unattended:
**a finding that is not literally present in the fetched document must not
survive.** Free models are frozen at training time and will confidently produce
plausible figures that were never in the page (run #223's fabricated ₹1800cr;
the 2026-09-08 video-script Gemma failure). `_grounded()` is the check that
stops that, and it is the first thing that would rot silently if someone
"simplified" the extractor later.
"""
import json
import os
import sys
import tempfile

# BEFORE any shared.* import — shared.config reads DATABASE_URL at import time,
# and a developer with the production URL exported is the normal state.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from engine.digger import extract, fetch          # noqa: E402
from engine.digger import robots                  # noqa: E402
from engine.digger import discover, targets       # noqa: E402
from engine.digger import routing                 # noqa: E402
from engine.digger import freellm                 # noqa: E402
from shared.db import (                           # noqa: E402
    init_db, record_digger_candidate, digger_seen_urls,
    start_digger_run, finish_digger_run, digger_candidates,
    propose_digger_target, digger_targets, set_digger_target_status,
)

_fails = []

DOC = {
    "final_url": "https://example.gov.in/audit/2026",
    "fetched_at": "2026-09-10T00:00:00Z",
    "truncated": False,
    "text": (
        "Report of the Comptroller and Auditor General for the year 2024-25.\n"
        "The audit observed irregularities amounting to Rs 1,950 crore across "
        "all departments of the corporation.\n"
        "Audit objections totalling Rs 14,653 crore remain unresolved since "
        "1964-65.\n"
    ),
}


def _rp(text):
    """Build a parsed RobotFileParser from literal robots.txt content."""
    import urllib.robotparser
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


# --------------------------------------------------------------------------
# parse_findings — free models fence, chatter, and sometimes emit bare arrays
# --------------------------------------------------------------------------

def t_parses_plain_json():
    raw = json.dumps({"findings": [
        {"title": "Rs 1,950 crore in irregularities", "finding": "Audit found it.",
         "excerpt": "irregularities amounting to Rs 1,950 crore"}]})
    check("plain json parses", len(extract.parse_findings(raw)), 1)


def t_parses_fenced_json():
    raw = ("```json\n" + json.dumps({"findings": [
        {"title": "T", "finding": "F", "excerpt": "E"}]}) + "\n```")
    check("fenced json parses", len(extract.parse_findings(raw)), 1)


def t_parses_json_wrapped_in_prose():
    raw = ('Sure! Here is what I found:\n'
           '{"findings": [{"title": "T", "finding": "F", "excerpt": "E"}]}\n'
           'Hope that helps.')
    check("prose-wrapped json salvaged", len(extract.parse_findings(raw)), 1)


def t_none_means_none():
    check("NONE yields no findings", extract.parse_findings("NONE"), [])
    check("empty yields no findings", extract.parse_findings(""), [])
    check("garbage yields no findings", extract.parse_findings("I cannot help"), [])


def t_drops_incomplete_findings():
    raw = json.dumps({"findings": [
        {"title": "", "finding": "F", "excerpt": "E"},
        {"title": "T", "finding": "", "excerpt": "E"},
        {"title": "ok", "finding": "real", "excerpt": "E"}]})
    check("incomplete findings dropped", len(extract.parse_findings(raw)), 1)


def t_caps_findings():
    raw = json.dumps({"findings": [
        {"title": f"t{i}", "finding": "f", "excerpt": "e"} for i in range(20)]})
    check("findings capped", len(extract.parse_findings(raw)), extract.MAX_FINDINGS)


# --------------------------------------------------------------------------
# _grounded — the check that stops training-data recall reaching the DB
# --------------------------------------------------------------------------

def t_grounded_accepts_verbatim_excerpt():
    f = {"title": "t", "finding": "f",
         "excerpt": "irregularities amounting to Rs 1,950 crore"}
    check("verbatim excerpt is grounded", extract._grounded(f, DOC["text"]), True)


def t_grounded_accepts_reflowed_whitespace():
    f = {"title": "t", "finding": "f",
         "excerpt": "irregularities   amounting\n to Rs 1,950 crore"}
    check("whitespace-reflowed excerpt is grounded",
          extract._grounded(f, DOC["text"]), True)


def t_grounded_rejects_invented_figure():
    # The exact failure mode this tier exists to prevent: a plausible figure
    # that never appeared in the document.
    f = {"title": "t", "finding": "f",
         "excerpt": "irregularities amounting to Rs 1,800 crore"}
    check("invented figure is rejected", extract._grounded(f, DOC["text"]), False)


def t_grounded_blanks_unverifiable_short_excerpt():
    f = {"title": "t", "finding": "f", "excerpt": "Rs 1"}
    kept = extract._grounded(f, DOC["text"])
    check("short excerpt kept", kept, True)
    check("short excerpt blanked rather than claimed verified", f["excerpt"], "")


# --------------------------------------------------------------------------
# cross_check — two models, and graceful degradation when the second fails
# --------------------------------------------------------------------------

def _fake_complete(mapping):
    """Return a freellm.complete stand-in keyed by model name."""
    def _c(prompt, model=None, **kw):
        val = mapping.get(model, mapping.get("*"))
        if isinstance(val, Exception):
            raise val
        return val
    return _c


def _with_fake(mapping, fn):
    orig = freellm.complete
    freellm.complete = _fake_complete(mapping)
    try:
        return fn()
    finally:
        freellm.complete = orig


def t_cross_check_agree():
    payload = json.dumps({"findings": [{
        "title": "Rs 1,950 crore in irregularities",
        "finding": "Audit found Rs 1,950 crore of irregularities.",
        "excerpt": "irregularities amounting to Rs 1,950 crore"}]})
    out, calls = _with_fake({"*": payload},
                            lambda: extract.cross_check(DOC, "brief", "m1", "m2"))
    check("agree: one candidate", len(out), 1)
    check("agree: flagged agree", out[0]["agreement"], "agree")
    check("agree: two model calls", calls, 2)


def t_cross_check_differ():
    a = json.dumps({"findings": [{
        "title": "Rs 1,950 crore in irregularities",
        "finding": "A.",
        "excerpt": "irregularities amounting to Rs 1,950 crore"}]})
    b = json.dumps({"findings": [{
        "title": "Objections unresolved since 1964-65",
        "finding": "B.",
        "excerpt": "unresolved since 1964-65"}]})
    out, _ = _with_fake({"m1": a, "m2": b},
                        lambda: extract.cross_check(DOC, "brief", "m1", "m2"))
    check("differ: flagged differ", out[0]["agreement"], "differ")
    check("differ: second answer retained", bool(out[0]["answer_b"]), True)


def t_second_model_rate_limited_falls_back():
    """A 429 on the named model must not cost the cross-check — free providers
    rate-limit constantly, so extract() retries via freellmapi's own routing."""
    a = json.dumps({"findings": [{
        "title": "Rs 1,950 crore in irregularities",
        "finding": "A.",
        "excerpt": "irregularities amounting to Rs 1,950 crore"}]})
    out, calls = _with_fake(
        {"m1": a, "m2": freellm.FreeLLMError("429 rate limited"), "auto": a},
        lambda: extract.cross_check(DOC, "brief", "m1", "m2"))
    check("fallback: still yields the lead", len(out), 1)
    check("fallback: cross-check still happened", out[0]["agreement"], "agree")
    check("fallback: records the model that ACTUALLY read it",
          out[0]["model_b"], freellm.FALLBACK_MODEL)


def t_cross_check_survives_total_second_model_failure():
    """Named model AND fallback both down: keep model A's grounded findings,
    flagged 'single'. Losing every lead to one provider outage is worse."""
    a = json.dumps({"findings": [{
        "title": "Rs 1,950 crore in irregularities",
        "finding": "A.",
        "excerpt": "irregularities amounting to Rs 1,950 crore"}]})
    out, calls = _with_fake(
        {"m1": a,
         "m2": freellm.FreeLLMError("429"),
         "auto": freellm.FreeLLMError("503")},
        lambda: extract.cross_check(DOC, "brief", "m1", "m2"))
    check("degraded: still yields the lead", len(out), 1)
    check("degraded: flagged single", out[0]["agreement"], "single")
    check("degraded: model_b recorded as None", out[0]["model_b"], None)
    check("degraded: only one call counted", calls, 1)


def t_cross_check_drops_ungrounded_even_if_both_agree():
    # Both models inventing the SAME figure must still not get through: the
    # cross-check is a second opinion, not a substitute for grounding.
    payload = json.dumps({"findings": [{
        "title": "Rs 1,800 crore diverted",
        "finding": "Both models say so.",
        "excerpt": "diversion amounting to Rs 1,800 crore"}]})
    out, _ = _with_fake({"*": payload},
                        lambda: extract.cross_check(DOC, "brief", "m1", "m2"))
    check("mutual hallucination still rejected", len(out), 0)


# --------------------------------------------------------------------------
# fetch — HTML to text, without network
# --------------------------------------------------------------------------

def t_html_to_text_strips_scripts_and_style():
    html = ("<html><head><title>x</title></head><body>"
            "<script>var a = 'SCRIPTTEXT';</script>"
            "<style>.c{color:red}</style>"
            "<p>Real content here</p></body></html>")
    text = fetch.html_to_text(html)
    check("script text removed", "SCRIPTTEXT" in text, False)
    check("style text removed", "color:red" in text, False)
    check("real content kept", "Real content here" in text, True)


def t_html_to_text_survives_malformed():
    text = fetch.html_to_text("<p>unclosed <b>tags <div>everywhere")
    check("malformed html still yields text", "unclosed" in text, True)


# --------------------------------------------------------------------------
# format dispatch — official sources serve whatever shape they like
# --------------------------------------------------------------------------

def t_json_is_readable_and_quotable():
    body = '{"scheme":"PMAY","allocated_cr":1950,"spent_cr":812}'
    out = fetch.body_to_text(body, "application/json", "https://x/api")
    check("json rendered", '"scheme": "PMAY"' in out, True)
    check("figure preserved verbatim", "1950" in out, True)


def t_json_sniffed_when_mislabelled():
    """OGD endpoints routinely serve JSON as text/html."""
    body = '[{"a":1}]'
    out = fetch.body_to_text(body, "text/html", "https://x/resource")
    check("mislabelled json still parsed", out.strip().startswith("["), True)
    check("json pretty-printed", "\n" in out, True)


def t_csv_becomes_aligned_rows():
    body = "district,allocated,spent\nWayanad,120,45\nIdukki,90,88"
    out = fetch.body_to_text(body, "text/csv", "https://x/d.csv")
    check("header row present", "district | allocated | spent" in out, True)
    check("data row present", "Wayanad | 120 | 45" in out, True)


def t_csv_truncates_on_whole_rows():
    """Half a row invites a model to misread a number — cap on records, not
    characters."""
    rows = "\n".join(f"r{i},{i*10},{i*3}" for i in range(fetch.MAX_CSV_ROWS + 50))
    out = fetch.body_to_text("a,b,c\n" + rows, "text/csv", "https://x/d.csv")
    check("truncation is announced", "[truncated at" in out, True)
    lines = [l for l in out.splitlines() if l and not l.startswith("...")]
    check("row cap honoured", len(lines), fetch.MAX_CSV_ROWS)
    check("last kept line is a whole row", lines[-1].count(" | "), 2)


def t_tsv_detected_from_plain_text():
    body = "state\tgsdp\tgrowth\nKerala\t1000\t6.1\nTN\t2000\t7.2"
    out = fetch.body_to_text(body, "text/plain", "https://x/d.txt")
    check("tab-delimited read as a table", "Kerala | 1000 | 6.1" in out, True)


def t_xml_strips_tags():
    body = '<?xml version="1.0"?><root><finding>Rs 1,950 crore</finding></root>'
    out = fetch.body_to_text(body, "application/xml", "https://x/d.xml")
    check("xml tags stripped", "<finding>" in out, False)
    check("xml content kept", "Rs 1,950 crore" in out, True)


def t_plain_text_passes_through():
    body = "Audit objections of Rs 14,653 crore remain unresolved."
    out = fetch.body_to_text(body, "text/plain", "https://x/note.txt")
    check("plain text unchanged", out, body)


def t_html_still_wins_for_html():
    body = "<html><body><script>BAD</script><p>Real finding</p></body></html>"
    out = fetch.body_to_text(body, "text/html", "https://x/p.html")
    check("html path used", "Real finding" in out, True)
    check("script still stripped", "BAD" in out, False)


# --------------------------------------------------------------------------
# robots.txt — an unattended crawler that ignores it is misbehaving
# --------------------------------------------------------------------------

def t_robots_disallow_is_respected():
    robots.reset_cache()
    robots._CACHE["https://x.gov.in/robots.txt"] = (
        __import__("time").time(), _rp("User-agent: *\nDisallow: /private/"), False)
    check("disallowed path refused",
          robots.allowed("https://x.gov.in/private/doc.pdf"), False)
    check("other path allowed",
          robots.allowed("https://x.gov.in/public/doc.pdf"), True)


def t_robots_rule_targeting_us_specifically():
    robots.reset_cache()
    robots._CACHE["https://y.gov.in/robots.txt"] = (
        __import__("time").time(),
        _rp("User-agent: ThelivuDigger\nDisallow: /\n\nUser-agent: *\nAllow: /"), False)
    check("named exclusion of this crawler honoured",
          robots.allowed("https://y.gov.in/anything"), False)


def t_missing_robots_means_allowed():
    """RFC 9309: no robots.txt is no restrictions. Refusing here would silently
    drop most sources for no reason."""
    robots.reset_cache()
    robots._CACHE["https://z.gov.in/robots.txt"] = (__import__("time").time(), None, False)
    check("absent robots.txt allows", robots.allowed("https://z.gov.in/doc"), True)


def t_robots_4xx_means_allowed_per_rfc9309():
    """A 4xx on robots.txt is "unavailable" -> no rules published -> allowed.
    Treating 403 as a refusal excluded data.gov.in, whose WAF 403s non-browser
    clients while the platform exists to distribute public data."""
    import urllib.error
    robots.reset_cache()
    orig = robots.urllib.request.urlopen
    def _403(*a, **k):
        raise urllib.error.HTTPError("u", 403, "Forbidden", None, None)
    robots.urllib.request.urlopen = _403
    try:
        check("403 on robots.txt allows", robots.allowed("https://w.gov.in/doc"), True)
    finally:
        robots.urllib.request.urlopen = orig


def t_robots_5xx_means_back_off():
    """A struggling server is exactly what robots.txt exists to protect."""
    import urllib.error
    robots.reset_cache()
    orig = robots.urllib.request.urlopen
    def _503(*a, **k):
        raise urllib.error.HTTPError("u", 503, "Service Unavailable", None, None)
    robots.urllib.request.urlopen = _503
    try:
        check("503 on robots.txt backs off", robots.allowed("https://s.gov.in/doc"), False)
    finally:
        robots.urllib.request.urlopen = orig


def t_robots_check_raises_with_a_clear_reason():
    robots.reset_cache()
    robots._CACHE["https://v.gov.in/robots.txt"] = (
        __import__("time").time(), _rp("User-agent: *\nDisallow: /"), False)
    try:
        robots.check("https://v.gov.in/doc")
        check("robots.check raises", False, True)
    except robots.RobotsDenied as e:
        check("robots.check raises RobotsDenied", True, True)
        check("reason states it is a decision to respect",
              "respect" in str(e), True)


# --------------------------------------------------------------------------
# routing — reaching a record without defeating anyone
# --------------------------------------------------------------------------

def t_disallowed_host_routes_to_a_permitted_one():
    """rajyasabha.nic.in disallows us; sansad.in serves the same questions and
    permits us. Asking the party that said yes is not circumventing the one
    that said no."""
    alts = routing.alternates(
        "https://cms.rajyasabha.nic.in/UploadedFiles/Questions/x.pdf")
    check("an alternate exists", len(alts), 1)
    check("routes to sansad.in", "sansad.in" in alts[0], True)
    check("path preserved", alts[0].endswith("/UploadedFiles/Questions/x.pdf"), True)


def t_routing_is_host_only_never_path_guessing():
    """Guessing paths is crawling blind. We only ever ask a different publisher
    for the same document."""
    src = "https://eparlib.sansad.in/bitstream/1/2/3.pdf?a=b"
    alt = routing.alternates(src)[0]
    from urllib.parse import urlparse
    check("path unchanged", urlparse(alt).path, "/bitstream/1/2/3.pdf")
    check("query preserved", urlparse(alt).query, "a=b")


def t_unknown_host_has_no_alternates():
    check("no invented alternates",
          routing.alternates("https://example.gov.in/x"), [])


def t_api_key_is_used_when_held_and_absent_otherwise():
    """data.gov.in answers 400, not 403 — it wants a registered key. That is
    the intended door, and using it is the opposite of a bypass."""
    import os
    u = "https://api.data.gov.in/resource/abc"
    orig = os.environ.pop("DATA_GOV_IN_API_KEY", None)
    try:
        out, have = routing.with_api_key(u)
        check("no key -> url untouched", out, u)
        check("no key -> reported", have, False)
        check("missing key surfaced", "data.gov.in" in routing.missing_api_keys(), True)

        os.environ["DATA_GOV_IN_API_KEY"] = "TESTKEY"
        out, have = routing.with_api_key(u)
        check("key -> appended", "api-key=TESTKEY" in out, True)
        check("key -> json requested", "format=json" in out, True)
        check("key -> reported", have, True)
        check("key no longer missing",
              "data.gov.in" in routing.missing_api_keys(), False)
    finally:
        os.environ.pop("DATA_GOV_IN_API_KEY", None)
        if orig is not None:
            os.environ["DATA_GOV_IN_API_KEY"] = orig


def t_every_block_gets_a_door_or_an_honest_handoff():
    """A non-conclusive stop must carry what would still obtain the record."""
    cases = {
        "robots.txt disallows ThelivuDigger at x": "robots",
        "blocked by bot detection at y":           "captcha",
        "HTTP 403 for index z":                    "waf",
        "no document links found at index w":      "js",
    }
    for err, want in cases.items():
        check(f"classified: {want}", routing.classify(err), want)
        check(f"{want} has a handoff", bool(routing.handoff_for(want)), True)
    check("captcha is handed to Tier 1, never bypassed",
          "grounded search" in routing.handoff_for("captcha"), True)
    check("unpublished records go to RTI",
          "RTI" in routing.handoff_for("unpublished"), True)


# --------------------------------------------------------------------------
# crawl delay — the half of robots.txt that costs us something
# --------------------------------------------------------------------------

def t_crawl_delay_is_actually_enforced():
    """Disallow was honoured and Crawl-delay was not: robots.crawl_delay()
    existed and nothing called it. Reading a publisher's rules and following
    only the half that is free is not compliance."""
    import time as _t
    robots.reset_cache()
    fetch._LAST_REQUEST.clear()
    robots._CACHE["https://slow.gov.in/robots.txt"] = (
        _t.time(), _rp("User-agent: *\nCrawl-delay: 2"), False)

    slept = []
    orig_sleep, orig_mono = fetch.time.sleep, fetch.time.monotonic
    clock = [1000.0]
    fetch.time.sleep = lambda s: slept.append(s)
    fetch.time.monotonic = lambda: clock[0]
    try:
        fetch._throttle("https://slow.gov.in/a")      # first hit: no wait
        check("first request does not wait", slept, [])
        fetch._throttle("https://slow.gov.in/b")      # immediate second hit
        check("second request waits", len(slept), 1)
        check("waits the publisher's 2s", round(slept[0]), 2)
    finally:
        fetch.time.sleep, fetch.time.monotonic = orig_sleep, orig_mono


def t_default_delay_applies_without_robots_rule():
    """These are government servers, several visibly fragile. One second between
    requests costs an hourly job nothing."""
    import time as _t
    robots.reset_cache()
    fetch._LAST_REQUEST.clear()
    robots._CACHE["https://plain.gov.in/robots.txt"] = (_t.time(), None, False)
    slept = []
    orig_sleep, orig_mono = fetch.time.sleep, fetch.time.monotonic
    clock = [500.0]
    fetch.time.sleep = lambda s: slept.append(s)
    fetch.time.monotonic = lambda: clock[0]
    try:
        fetch._throttle("https://plain.gov.in/a")
        fetch._throttle("https://plain.gov.in/b")
        check("default delay applied", round(slept[0]), round(fetch.DEFAULT_CRAWL_DELAY))
    finally:
        fetch.time.sleep, fetch.time.monotonic = orig_sleep, orig_mono


def t_delay_is_per_host_not_global():
    """Waiting on host B because we just hit host A would halve throughput for
    no benefit to anyone."""
    import time as _t
    robots.reset_cache()
    fetch._LAST_REQUEST.clear()
    for h in ("a.gov.in", "b.gov.in"):
        robots._CACHE[f"https://{h}/robots.txt"] = (_t.time(), None, False)
    slept = []
    orig_sleep, orig_mono = fetch.time.sleep, fetch.time.monotonic
    fetch.time.sleep = lambda s: slept.append(s)
    fetch.time.monotonic = lambda: 100.0
    try:
        fetch._throttle("https://a.gov.in/x")
        fetch._throttle("https://b.gov.in/y")
        check("different host does not wait", slept, [])
    finally:
        fetch.time.sleep, fetch.time.monotonic = orig_sleep, orig_mono


def t_hostile_crawl_delay_cannot_hang_the_loop():
    """A Crawl-delay of 86400 is a refusal expressed as a number; respect it by
    skipping the source, not by parking the service for a day."""
    import time as _t
    robots.reset_cache()
    fetch._LAST_REQUEST.clear()
    robots._CACHE["https://hostile.gov.in/robots.txt"] = (
        _t.time(), _rp("User-agent: *\nCrawl-delay: 86400"), False)
    slept = []
    orig_sleep, orig_mono = fetch.time.sleep, fetch.time.monotonic
    fetch.time.sleep = lambda s: slept.append(s)
    fetch.time.monotonic = lambda: 100.0
    try:
        fetch._throttle("https://hostile.gov.in/a")
        fetch._throttle("https://hostile.gov.in/b")
        check("wait is capped", slept[0] <= 30.0, True)
    finally:
        fetch.time.sleep, fetch.time.monotonic = orig_sleep, orig_mono


# --------------------------------------------------------------------------
# bot walls — a source that says no
# --------------------------------------------------------------------------

def t_captcha_page_is_reported_as_refusal_not_parse_error():
    """RBI answers .PDF URLs with a CAPTCHA page. That must surface as "this
    source refuses automated access", not as a parse failure that reads like
    our bug — and it must never be treated as something to work around."""
    captcha = ("This question is for testing whether you are a human visitor "
               "and to prevent automated spam submission. What code is in the "
               "image? Your support ID is: 679480895557810163")
    try:
        fetch._reject_if_bot_wall(captcha, "https://rbidocs.rbi.org.in/x.PDF")
        check("captcha page rejected", False, True)
    except fetch.FetchError as e:
        check("captcha page raises FetchError", True, True)
        check("names bot detection", "bot detection" in str(e), True)
        check("says not to work around it", "worked around" in str(e), True)


def t_ordinary_document_is_not_mistaken_for_a_bot_wall():
    ok = ("Report of the Comptroller and Auditor General. The audit observed "
          "irregularities amounting to Rs 1,950 crore across all departments.")
    fetch._reject_if_bot_wall(ok, "https://cag.gov.in/x")   # must not raise
    check("ordinary document passes bot-wall check", True, True)


# --------------------------------------------------------------------------
# target rotation
# --------------------------------------------------------------------------

def t_disabled_targets_are_skipped():
    """A known-broken source (PIB 403s this host) must leave the rotation
    entirely rather than burn a cycle every few hours."""
    from engine.digger import targets
    keys = [t["key"] for t in targets.active_targets()]
    check("disabled target excluded", "pib-releases" in keys, False)
    check("active targets remain", len(keys) > 0, True)
    seen = set()
    k = None
    for _ in range(len(keys) * 2):
        k = targets.next_target(k)["key"]
        seen.add(k)
    check("rotation covers every active target", seen == set(keys), True)
    check("rotation never yields a disabled target", "pib-releases" in seen, False)


# --------------------------------------------------------------------------
# PDF handling — optional dependency, honest failure
# --------------------------------------------------------------------------

def _with_parser(factory, fn):
    """Swap the parser factory. Patching the FACTORY (not a cached instance) is
    deliberate — pdf_to_text builds and closes a parser per call, because
    letting liteparse reach __del__ at interpreter shutdown core-dumps the
    process."""
    orig = fetch._new_parser
    fetch._new_parser = factory
    try:
        return fn()
    finally:
        fetch._new_parser = orig


class _FakeParser:
    def __init__(self, result): self._r = result; self.closed = False
    def parse(self, data): return self._r
    def close(self): self.closed = True


def t_pdf_without_liteparse_is_an_honest_miss():
    """Without liteparse the PDF path must RAISE, not return empty text. An
    empty extraction reads downstream as 'nothing found in this document',
    which is a silent lie about a source we never actually read."""
    def _boom():
        raise ImportError("No module named 'liteparse'")
    try:
        _with_parser(_boom, lambda: fetch.pdf_to_text(b"%PDF-1.4 fake"))
        check("missing liteparse raises", False, True)
    except fetch.FetchError as e:
        check("missing liteparse raises FetchError", True, True)
        check("error names the cause", "liteparse" in str(e), True)


def t_pdf_with_no_text_layer_is_an_honest_miss():
    """A scanned PDF yields no text with OCR disabled. That must surface as a
    miss naming the reason, not as an empty successful parse."""
    class _R:
        text = ""
        pages = []
    try:
        _with_parser(lambda: _FakeParser(_R()),
                     lambda: fetch.pdf_to_text(b"%PDF-1.4"))
        check("empty text layer raises", False, True)
    except fetch.FetchError as e:
        check("empty text layer raises FetchError", True, True)
        check("error explains scanned/OCR", "text layer" in str(e), True)


def t_pdf_prefers_whole_document_text():
    """`.text` is the accessor, not `.markdown` — which stays empty unless
    output_format is set and looks exactly like 'no text layer' when misread."""
    class _R:
        text = "Audit observed irregularities of Rs 1,950 crore."
        pages = []
    out = _with_parser(lambda: _FakeParser(_R()),
                       lambda: fetch.pdf_to_text(b"%PDF-1.4"))
    check("whole-document text used", out, "Audit observed irregularities of Rs 1,950 crore.")


def t_pdf_falls_back_to_per_page_text():
    class _P:
        def __init__(self, i): self.text = f"page{i} content"
    class _R:
        text = ""
        pages = [_P(i) for i in range(500)]
    out = _with_parser(lambda: _FakeParser(_R()),
                       lambda: fetch.pdf_to_text(b"%PDF-1.4"))
    check("per-page fallback used", "page0 content" in out, True)
    check("page cap honoured", out.count("content"), fetch.MAX_PDF_PAGES)
    check("beyond-cap page absent", "page499 content" in out, False)


def t_pdf_parser_is_always_closed():
    """The close() is the whole reason this is per-call; if it stops happening
    the service core-dumps at shutdown instead of exiting."""
    holder = {}
    class _R:
        text = "ok text here"
        pages = []
    def _factory():
        holder["p"] = _FakeParser(_R())
        return holder["p"]
    _with_parser(_factory, lambda: fetch.pdf_to_text(b"%PDF-1.4"))
    check("parser closed on success", holder["p"].closed, True)

    class _Boom(_FakeParser):
        def parse(self, data): raise RuntimeError("corrupt pdf")
    def _factory2():
        holder["p"] = _Boom(_R())
        return holder["p"]
    try:
        _with_parser(_factory2, lambda: fetch.pdf_to_text(b"%PDF-1.4"))
    except fetch.FetchError:
        pass
    check("parser closed even when parse raises", holder["p"].closed, True)


# --------------------------------------------------------------------------
# source discovery — the scout nominates, a human activates
# --------------------------------------------------------------------------

def t_proposal_never_lands_active():
    """The whole guardrail. A bad story is caught at the verification gate, but
    a bad SOURCE quietly shapes every story that flows through it — so no code
    path may put one into the rotation without a person."""
    init_db()
    propose_digger_target(
        key="t-auto", name="Auto", index_url="https://x.gov.in/i",
        brief="b", robots_ok=True, fetch_ok=True, doc_links=50)
    rows = {r["key"]: r for r in digger_targets()}
    check("proposal recorded", "t-auto" in rows, True)
    check("proposal is NOT active", rows["t-auto"]["status"], "proposed")
    active = [t["key"] for t in targets.db_targets()]
    check("proposed target stays out of rotation", "t-auto" in active, False)

    set_digger_target_status("t-auto", "active", decided_by="owner")
    active = [t["key"] for t in targets.db_targets()]
    check("activated target enters rotation", "t-auto" in active, True)


def t_rejected_target_never_enters_rotation():
    init_db()
    propose_digger_target(key="t-bad", name="Bad", index_url="https://y.gov.in/i",
                          brief="b", robots_ok=True, fetch_ok=True, doc_links=9)
    set_digger_target_status("t-bad", "rejected", decided_by="owner")
    check("rejected target excluded",
          "t-bad" in [t["key"] for t in targets.db_targets()], False)


def t_validation_refuses_a_robots_disallowed_source():
    """A source that has asked not to be crawled must fail validation before we
    ever fetch its index — probing it anyway is the same discourtesy."""
    orig = discover.robots.allowed
    discover.robots.allowed = lambda u, *a, **k: False
    try:
        ev = discover.validate("https://no.gov.in/index")
        check("robots-disallowed source fails validation", ev["ok"], False)
        check("reason names robots.txt", "robots" in (ev["validation_error"] or ""), True)
        check("index never fetched", ev["fetch_ok"], False)
    finally:
        discover.robots.allowed = orig


def t_validation_rejects_an_index_with_no_documents():
    """An index yielding nothing is a dead end — exactly how the JS-rendered RBI
    listing looked before we understood it."""
    orig_r, orig_f = discover.robots.allowed, discover.fetch.fetch_index
    discover.robots.allowed = lambda u, *a, **k: True
    discover.fetch.fetch_index = lambda u, p=None: [{"url": "https://a/1", "title": "x"}]
    try:
        ev = discover.validate("https://thin.gov.in/index")
        check("thin index fails validation", ev["ok"], False)
        check("reason mentions link count",
              "document link" in (ev["validation_error"] or ""), True)
    finally:
        discover.robots.allowed, discover.fetch.fetch_index = orig_r, orig_f


def t_validation_records_failures_with_reasons():
    """'We tried this and it refuses us' is worth keeping, or the next scout run
    proposes the same dead source again."""
    init_db()
    orig = discover.robots.allowed
    discover.robots.allowed = lambda u, *a, **k: False
    try:
        ev = discover.propose("https://blocked.gov.in/i", "Blocked", "brief")
    finally:
        discover.robots.allowed = orig
    row = {r["key"]: r for r in digger_targets()}[ev["key"]]
    check("failed candidate still recorded", row["status"], "proposed")
    check("failure reason persisted", bool(row["validation_error"]), True)


def t_db_failure_degrades_to_builtin_targets():
    """Losing Postgres should cost the extra sources, not the whole rotation."""
    orig = targets.db_targets
    def _boom():
        raise RuntimeError("db down")
    import shared.db as _db
    orig_q = _db.digger_targets
    _db.digger_targets = lambda status=None: (_ for _ in ()).throw(RuntimeError("db down"))
    try:
        active = targets.active_targets()
        check("builtin targets survive a DB outage", len(active) > 0, True)
        check("no db targets during outage",
              all(t.get("source") != "db" for t in active), True)
    finally:
        _db.digger_targets = orig_q


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

def t_records_and_dedups():
    init_db()
    run_id = start_digger_run("t-target")
    record_digger_candidate(
        target_key="t-target", title="T", finding="F",
        source_url="https://example.gov.in/a", excerpt="E",
        model_a="m1", model_b="m2", answer_a="F", answer_b="F",
        agreement="agree", fetched_at="2026-09-10T00:00:00Z")
    finish_digger_run(run_id, ok=True, docs_fetched=1, candidates_found=1,
                      model_calls=2)
    seen = digger_seen_urls("t-target")
    check("recorded url is seen", "https://example.gov.in/a" in seen, True)
    check("other target unaffected", digger_seen_urls("other"), set())
    rows = digger_candidates(status="new")
    check("candidate readable", rows[0]["title"], "T")
    check("candidate defaults to new", rows[0]["status"], "new")


def main():
    print("digger cases")
    for t in (t_parses_plain_json,
              t_parses_fenced_json,
              t_parses_json_wrapped_in_prose,
              t_none_means_none,
              t_drops_incomplete_findings,
              t_caps_findings,
              t_grounded_accepts_verbatim_excerpt,
              t_grounded_accepts_reflowed_whitespace,
              t_grounded_rejects_invented_figure,
              t_grounded_blanks_unverifiable_short_excerpt,
              t_cross_check_agree,
              t_cross_check_differ,
              t_second_model_rate_limited_falls_back,
              t_cross_check_survives_total_second_model_failure,
              t_cross_check_drops_ungrounded_even_if_both_agree,
              t_html_to_text_strips_scripts_and_style,
              t_html_to_text_survives_malformed,
              t_json_is_readable_and_quotable,
              t_json_sniffed_when_mislabelled,
              t_csv_becomes_aligned_rows,
              t_csv_truncates_on_whole_rows,
              t_tsv_detected_from_plain_text,
              t_xml_strips_tags,
              t_plain_text_passes_through,
              t_html_still_wins_for_html,
              t_robots_disallow_is_respected,
              t_robots_rule_targeting_us_specifically,
              t_missing_robots_means_allowed,
              t_robots_4xx_means_allowed_per_rfc9309,
              t_robots_5xx_means_back_off,
              t_robots_check_raises_with_a_clear_reason,
              t_disallowed_host_routes_to_a_permitted_one,
              t_routing_is_host_only_never_path_guessing,
              t_unknown_host_has_no_alternates,
              t_api_key_is_used_when_held_and_absent_otherwise,
              t_every_block_gets_a_door_or_an_honest_handoff,
              t_crawl_delay_is_actually_enforced,
              t_default_delay_applies_without_robots_rule,
              t_delay_is_per_host_not_global,
              t_hostile_crawl_delay_cannot_hang_the_loop,
              t_captcha_page_is_reported_as_refusal_not_parse_error,
              t_ordinary_document_is_not_mistaken_for_a_bot_wall,
              t_disabled_targets_are_skipped,
              t_pdf_without_liteparse_is_an_honest_miss,
              t_pdf_with_no_text_layer_is_an_honest_miss,
              t_pdf_prefers_whole_document_text,
              t_pdf_falls_back_to_per_page_text,
              t_pdf_parser_is_always_closed,
              t_proposal_never_lands_active,
              t_rejected_target_never_enters_rotation,
              t_validation_refuses_a_robots_disallowed_source,
              t_validation_rejects_an_index_with_no_documents,
              t_validation_records_failures_with_reasons,
              t_db_failure_degrades_to_builtin_targets,
              t_records_and_dedups):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all digger cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
