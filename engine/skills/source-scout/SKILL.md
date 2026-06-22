---
name: source-scout
description: Run weekly to discover and vet NEW candidate sources for the engine, and to audit existing ones. Use whenever the user wants to find new channels or outlets to follow, expand or refresh the source list, fill coverage gaps, or run the weekly source review. It proposes candidates to the registry for human approval — it never activates a source on its own — and its core mandate is to fight echo-chamber drift by prioritizing verification-grade and cross-spectrum sources, not more of the same.
---

# Source Scout

Run this weekly. It does two jobs: **find new candidate sources** worth adding, and **audit existing sources** by their track record. It writes proposals into `../../sources.yaml` as `status: candidate` — and stops there. A human activates sources; the scout only nominates.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## Why a source is a bigger deal than a story

A bad story gets caught at the verification gate. A bad *source*, once trusted, quietly shapes every story that flows through it — what gets surfaced, what gets treated as corroboration. So the bar for adding a source is **higher** than for publishing a story, and the decision belongs to a human. The scout's job is to do the legwork so that human decision is well-informed.

## The core mandate: fight the echo chamber

The intuitive move — "find more sources like the ones we like" — is exactly the wrong one, and it quietly destroys the engine's credibility. Here's why: verification only means something if a claim is checked against **independent** sources. If the source pool all leans the same way, then "verified" just means "agreed with by people who already think like us" — consensus inside a bubble, not verification.

So the scout is biased *against* more-of-the-same. Each week, prioritize in this order:

1. **Verification-grade sources (Tier 1–2) the engine lacks.** Primary-record and established-news sources for the beat: court and ECI filings, RBI / government / CAG data portals, statistical offices, established dailies (across the spectrum). These are what make verification real, and the registry currently has none. This is the top priority.
2. **Adversarial / cross-spectrum leads.** Credible sources that would *disagree* with the current lineup. If every lead source shares a worldview, find the serious ones that don't, so the verifier has something to push against.
3. **Coverage gaps.** Beats or regions (e.g. Kerala districts, specific sectors) under-served by the current sources.
4. **Only then,** more aligned lead sources — and even then, flag explicitly when a candidate is "more of the same."

## Vetting: what to establish for each candidate

Do not nominate a source you haven't vetted. For each, establish:

- **What it is and who runs it** — individual, outlet, agency, or anonymous. Anonymous/unattributable → high caution.
- **Original reporting vs aggregation** — does it produce primary work, or just repackage others? Aggregators add little and can launder rumor.
- **Track record / credibility** — corrections culture? history of retracted or false claims? third-party reliability ratings if any.
- **Lean** — name it honestly. Lean alone doesn't disqualify a *lead* source, but it disqualifies it as a *verification* source.
- **Primary vs commentary** — closer to records = higher tier.
- **Proposed role and tier** — lead or verification; 1, 2, or 3.

## Also audit the existing sources

Each week, review the `track_record` of active sources. If a source's claims keep **failing** verification, flag it for demotion or removal — propose the change, don't make it. A source that repeatedly sends the engine chasing things that don't hold up is a liability, however appealing its content.

## Output format

Write each candidate into `sources.yaml` as `status: candidate`, and surface this dossier to the human:

```
# Source Scout — week of [date]

## New candidates (for your approval)
### [name] — [platform] — [handle]
- Found because: verification-grade gap | cross-spectrum | coverage gap | aligned lead
- What it is / who runs it: ...
- Original reporting vs aggregation: ...
- Track record & credibility: ...
- Lean (named honestly): ...
- Proposed role / tier: lead|verification / 1|2|3
- Recommendation: nominate | nominate with caution | do not add — [why]

## Existing-source audit
- [source]: reliability trend; flag for demotion/removal? [why]

## The honest check
- Did this week's candidates make the pool MORE diverse and better-verified,
  or just more of the same? If the latter, say so plainly.
```

## Example

Input: "Run the weekly source scout for Kerala."
Output: nominates the Kerala High Court and ECI data portals and one established Malayalam daily as *verification-grade* candidates (filling the engine's biggest gap), flags one suggested explainer as "more of the same — adds reach but not independence," and notes one active source whose last few leads all failed verification — proposed for review. All written to the registry as candidates; nothing activated.
