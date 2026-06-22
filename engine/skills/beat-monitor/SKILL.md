---
name: beat-monitor
description: Scan the open web and primary feeds (courts, ECI, RBI, CAG, government portals, established news) for NEW, UNDER-COVERED developments on Thelivu's beats, and surface them as candidate leads. Use whenever the user wants to scan the beat, check what's developing in Kerala or India, watch the primary/government feeds, or run an open-web sweep. It complements news-monitor (which watches curated channels): the channels give offbeat tips, the beat-monitor catches the buried developments on the core beats. It produces leads only — never verified or publishable copy.
---

# Beat Monitor

A second **lead source**, alongside `news-monitor`. Where news-monitor watches the
curated channels (the tip line), this watches the **open web and primary feeds**
for new developments on Thelivu's beats. Both feed the same pipeline; both produce
leads only.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it
if present; the charter governs in any conflict.

## The rule that keeps this from becoming a firehose

Thelivu does **not** cover what the whole press already covers. So this monitor's
job is **not** "all Kerala news" — it is the **under-covered** slice. Apply the
impact × under-coverage filter ruthlessly: surface the buried court order, the
unread audit paragraph, the quiet government notification — and **discard** the
front-page story everyone already ran. If an item is already well-covered, it is
out, no matter how big. Mainstream saturation is a reason to skip, not to pile on.

## What to scan

Prioritise **primary feeds** — they are double-value: a lead *and* a Tier-1
verification source at once, which also helps fill the engine's verification-source
gap.

1. **Primary / official** — Kerala High Court and district court listings, ECI
   filings, RBI notifications, CAG reports, Assembly proceedings, government
   gazettes and department portals, budget and audit documents, RTI disclosures.
2. **Established news, across the spectrum** — but only to catch what's *under*-
   reported or buried, never to echo the lead story.
3. **Statistical / data releases** — economic surveys, official datasets.

## The beats (Kerala first, India second)

Politics and governance; the state economy and budget; public services (health,
education, transport, power, water); environment and disaster resilience; social
policy and welfare; public infrastructure and procurement. Extend deliberately,
in writing, not by drift.

## Output format

Same candidate queue as `news-monitor`, highest priority first:

```
# Beat Monitor — [date] — [beat]

## Lead 1: [the development]
- Status: New | Follow-up (of: [prior story])
- Why it matters (impact): ...
- Coverage: who's covering it / who isn't — [under-covered | near-invisible]
  (if well-covered → do not surface)
- Source: [link — label primary / established]  ← primary feeds get priority
- Source tier: 1 (primary) | 2 (established)
- Priority: High | Medium | Low
- Open question for the investigator: ...
```

Dedupe against already-processed items and against anything already widely
covered. Hand the queue to `news-investigator`; verify nothing here.

## Example

Input: "Run the Kerala beat monitor."
Output: surfaces a CAG paragraph flagging cost overruns on a water project (Tier 1,
near-invisible in the press) as High priority; notes a buried High Court order on a
land transfer (Tier 1, under-covered) as Medium; and *discards* the day's headline
budget story because it's already saturated. Leads only — the investigator builds
each from the record.
