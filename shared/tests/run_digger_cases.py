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
from engine.digger import freellm                 # noqa: E402
from shared.db import (                           # noqa: E402
    init_db, record_digger_candidate, digger_seen_urls,
    start_digger_run, finish_digger_run, digger_candidates,
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
