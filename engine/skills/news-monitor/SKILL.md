---
name: news-monitor
description: Continuously scan a defined set of beats and sources for high-impact, under-reported news leads and surface a prioritized candidate queue. Use this whenever the user wants to monitor the news for a beat (e.g. Kerala politics or economy), find story leads, check for new developments, or follow up on tracked stories. Trigger for any "what's developing", "scan for stories", "monitor X", "run a cycle", or "find leads" request. It produces leads only — never verified or publishable copy.
---

# News Monitor

This skill runs the **first stage** of the news engine: it finds candidate stories worth investigating. It does not verify and does not write publishable copy. Its only job is to surface what's important and under-covered, and hand a ranked queue to the investigator.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## The one rule that matters most here

**Under-coverage is a signal of what's worth a look. It is never a signal of what's true.** A story being ignored by the mainstream is a reason to investigate it, never a reason to believe it. Some things are under-covered because they're important and inconvenient; others because they didn't check out. This stage cannot tell the difference — that's the verifier's job later. So pass leads forward as *leads*, never as findings.

## What to do each cycle

1. **Scan the beat.** Default priority order: Kerala (politics, economy, governance, public services) first, then India. Search across the spectrum — mainstream outlets, regional-language press, independent newsrooms, primary sources (government data, court listings, regulatory filings, company disclosures), and partisan outlets (as lead sources only).
2. **Spot two kinds of lead:**
   - **Under-covered:** important developments that are absent from, or buried by, mainstream coverage.
   - **Follow-ups:** new movement on a story the channel has already published or is tracking.
3. **Score each lead on impact × under-coverage** (impact first):
   - *Impact:* does it materially affect people's money, rights, health, safety, or governance? How many people?
   - *Under-coverage:* who is covering it, who isn't, how prominently?
4. **Discard at this stage** anything whose only hook is "it's suppressed", anything unfalsifiable, and anything that needs a conspiracy assumed to make ordinary facts cohere.
5. **Hand off** the ranked queue. Do not investigate or verify here.

## Output format

ALWAYS output a candidate queue in this structure, highest priority first:

```
# Monitoring Cycle — [date] — [beat]

## Lead 1: [one-line description of the claim or development]
- Status: New | Follow-up (of: [prior story])
- Why it matters (impact): [who is affected and how]
- Coverage: covered by [outlets] / absent from [outlets] — i.e. [well-covered | under-covered | near-invisible]
- Source leads: [links — label partisan/primary/mainstream]
- Priority: High | Medium | Low
- Open question for the investigator: [the single thing most worth digging into]

## Lead 2: ...
```

End with a one-line summary: how many leads, how many High priority, anything time-sensitive.

## Example

Input: "Run a Kerala cycle."
Output (one lead): a High-priority, under-covered lead that a state PSU quietly transferred a wind farm to a private operator, affecting power tariffs — covered only by one regional outlet, absent from national press — flagged for investigation, with the open question being the valuation and tender process. Not asserted as wrongdoing; surfaced as worth a look.
