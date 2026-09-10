"""Extraction over already-fetched text, with a two-model cross-check.

The prompt contract matters more than the model here. Every prompt in this
module:

  * supplies the document text inline and forbids outside knowledge,
  * asks for figures/dates/names that appear verbatim in that text,
  * offers an explicit "NONE" escape so a model that finds nothing says so
    instead of inventing something to fill the schema.

The cross-check runs a SECOND, different model over the same text and compares.
Disagreement is recorded as a flag for a human/Claude reviewer — never
auto-resolved. This is the cheap echo of CHARTER.md's two-independent-sources
rule: it catches extraction slips without needing an expensive model.
"""

import json
import re

from engine.digger import freellm

MAX_FINDINGS = 5

_PROMPT = """You are reading ONE document. Extract only what this document says.

ABSOLUTE RULES:
- Use ONLY the document text below. Do not use anything you know from training.
- Every figure, date, name and status must appear VERBATIM in the document.
- If the document contains nothing matching the brief, reply exactly: NONE
- Do not speculate, do not infer motive, do not editorialise.

BRIEF: {brief}

Return STRICT JSON, no prose, no markdown fence:
{{"findings": [{{"title": "...", "finding": "...", "excerpt": "..."}}]}}

- "title": under 15 words, plain description of what the document shows.
- "finding": 1-3 sentences, strictly what the document states.
- "excerpt": a SHORT verbatim quote from the document supporting the finding.

DOCUMENT ({url}):
---
{text}
---
"""


def _strip_fence(s):
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s.strip())
    return s.strip()


def parse_findings(raw):
    """Tolerant JSON parse. Free models fence, prepend chatter, and occasionally
    emit the array bare — none of which is worth failing a cycle over."""
    if raw is None:
        return []
    s = _strip_fence(raw)
    if not s or s.strip().upper().startswith("NONE"):
        return []

    obj = None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        # Salvage the outermost {...} or [...] the model wrapped in prose.
        for pattern in (r"\{.*\}", r"\[.*\]"):
            m = re.search(pattern, s, re.S)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    break
                except json.JSONDecodeError:
                    continue
    if obj is None:
        return []

    items = obj.get("findings") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return []

    out = []
    for it in items[:MAX_FINDINGS]:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        finding = (it.get("finding") or "").strip()
        excerpt = (it.get("excerpt") or "").strip()
        if not title or not finding:
            continue
        out.append({"title": title, "finding": finding, "excerpt": excerpt})
    return out


def _grounded(finding, document_text):
    """Reject a finding whose excerpt is not actually in the document.

    This is the single most valuable check in the package: it is exactly how a
    confident free model smuggles training-data recall into a 'finding'. Compare
    on collapsed whitespace, since models reflow quotes."""
    excerpt = finding.get("excerpt") or ""
    if len(excerpt) < 12:
        # Too short to verify meaningfully; keep it but mark it unverified by
        # blanking the excerpt rather than pretending it was checked.
        finding["excerpt"] = ""
        return True
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    return norm(excerpt) in norm(document_text)


def extract(doc, brief, model=None, allow_fallback=True):
    """Run one model over one fetched document. Returns (findings, model_used).

    A named free model that is rate-limited or unrouted right now falls back to
    freellmapi's own routing — losing a whole cycle to one provider's 429 would
    be the wrong trade. The model actually used is returned so the recorded
    candidate says who read it.
    """
    prompt = _PROMPT.format(brief=brief, url=doc["final_url"], text=doc["text"])
    model = model or freellm.MODEL_A
    try:
        raw = freellm.complete(prompt, model=model)
        used = model
    except freellm.FreeLLMError:
        if not allow_fallback or model == freellm.FALLBACK_MODEL:
            raise
        raw = freellm.complete(prompt, model=freellm.FALLBACK_MODEL)
        used = freellm.FALLBACK_MODEL
    findings = [f for f in parse_findings(raw) if _grounded(f, doc["text"])]
    return findings, used


def _key(finding):
    """Loose identity for comparing two models' findings — first 8 significant
    words of the title. Exact-match would call every paraphrase a disagreement."""
    words = re.findall(r"[a-z0-9]+", (finding.get("title") or "").lower())
    stop = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "is", "at"}
    return " ".join([w for w in words if w not in stop][:8])


def cross_check(doc, brief, model_a=None, model_b=None):
    """Two different models read the same document.

    Returns a list of candidate dicts carrying both answers and an agreement
    flag: 'agree' (both found it), 'single' (only one model ran or only one
    found it), 'differ' (the second model ran and did not corroborate).

    A second-model failure is NOT fatal — the cycle still yields the first
    model's grounded findings, flagged 'single'. Losing every lead because one
    free provider was rate-limited would be the wrong trade.
    """
    model_a = model_a or freellm.MODEL_A
    model_b = model_b or freellm.MODEL_B

    findings_a, used_a = extract(doc, brief, model=model_a)
    calls = 1

    findings_b, used_b, b_ok = [], model_b, True
    try:
        findings_b, used_b = extract(doc, brief, model=model_b)
        calls += 1
    except freellm.FreeLLMError:
        b_ok = False

    b_keys = {_key(f) for f in findings_b}

    out = []
    for f in findings_a:
        if not b_ok:
            agreement = "single"
            answer_b = None
        elif _key(f) in b_keys:
            agreement = "agree"
            answer_b = next(
                (x["finding"] for x in findings_b if _key(x) == _key(f)), None
            )
        else:
            agreement = "differ"
            answer_b = json.dumps([x["title"] for x in findings_b])[:500]
        out.append({
            "title": f["title"],
            "finding": f["finding"],
            "excerpt": f["excerpt"],
            "source_url": doc["final_url"],
            "fetched_at": doc["fetched_at"],
            "model_a": used_a,
            "model_b": used_b if b_ok else None,
            "answer_a": f["finding"],
            "answer_b": answer_b,
            "agreement": agreement,
        })
    return out, calls
