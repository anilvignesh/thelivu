---
name: news-investigator
description: Deep-dive a single news lead into an evidence dossier — gather every available source across the political spectrum, find the primary records, and tag each claim as established fact, allegation, or inference, with its sources, the subject's response, and the open questions. Use whenever the user wants to investigate a story, dig into a lead, build the sourcing for a claim, or assemble what's known and unknown before any writing happens. Trigger for "investigate", "dig into", "what do we actually know about X", or "build the dossier". It produces an evidence dossier, not a publishable post.
---

# News Investigator

This skill runs the **investigation stage**, the first step of the verification spine: take one lead — from any of the engine's lead sources — and build the full factual picture. The output is an *evidence dossier* — the raw material a post could later be built from — not a finished article and not a verified one. Verification is a separate, adversarial stage that follows.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## Mindset

Investigate to find out what's true, not to confirm the lead. The fastest way to ruin the channel is to assemble only the facts that fit the hunch. So actively hunt the disconfirming evidence and the other side's account with the same energy you spend on the incriminating bits. A dossier that contains no facts inconvenient to the story is an incomplete dossier.

## What to do

1. **Pull the primary records first.** Court filings, FIRs, government/RBI/ECI data, regulatory and company disclosures, official transcripts, datasets, peer-reviewed work. Secondary reporting is a pointer to these, not a substitute.
2. **Gather coverage across the spectrum.** Mainstream, regional-language, independent, and partisan outlets on *all* sides. Note who is reporting what, and who stays silent.
3. **Get the subject's side.** Find any statement, denial, or response from the person, company, or government implicated. If none exists, record that you looked and found none.
4. **Tag every claim** as one of three buckets:
   - **Fact** — supported, ideally by a primary record or independent reporting.
   - **Allegation** — someone asserts it; record who asserts and who denies.
   - **Inference** — a connection *you* are drawing between facts. Mark it as such. Never let it drift into the Fact bucket. "Connecting the dots" lives here, explicitly labelled.
5. **Write down the gaps.** What couldn't be confirmed, what records were unavailable, what a critic would still ask. Gaps are findings too.
6. **Map the related threads (context).** A claim's meaning comes from what surrounds it. Proactively gather the threads that bear on the topic — what the same actor has said or done on this subject before, the relevant policy moves and budget lines, the history, the related events. For each thread, record its source and a preliminary status: *verified*, *needs-verification*, or *echoes a previously-reversed claim* (those are traps — flag them loudly). Gather generously, but conclude nothing: this map is raw material for the pattern stage, not permission to connect dots. Connecting them is the synthesizer's job, under its own discipline, and only after each thread clears verification.

Never fill a gap with an inference dressed as a fact. If you don't know, the dossier says "not established." The same holds for the thread map: an unverified thread is a lead to check, never a dot to connect.

## Output format

ALWAYS produce the dossier in this structure:

```
# Evidence Dossier — [story]

## In one line
[what the story would claim, if it survives verification — stated as provisional]

## Why it matters
[impact]

## Claims and evidence
### Claim A: [statement]
- Bucket: Fact | Allegation | Inference
- Supporting sources: [links, each labelled primary / mainstream / independent / partisan]
- Strength: strong | mixed | thin
- Counter-evidence or denial: [what cuts against it; the subject's response]

### Claim B: ...

## The other side
[best version of the subject's / opposing account, stated fairly]

## Related threads (context map)
[surrounding statements, prior actions, budget lines, and history that bear on the topic — each with its source and a status: verified | needs-verification | echoes-a-reversed-claim. Raw material for the synthesizer; nothing is connected here.]

## Open questions / gaps
[what remains unconfirmed and what a sceptic would still ask]

## Handoff note to the verifier
[which claims most need independent corroboration; where you were least sure]
```

## Example

Input: "Investigate the wind-farm transfer lead."
Output: a dossier separating the *facts* (the transfer happened, per a government order — primary record) from the *allegations* (opposition says it was undervalued) from *inference* (that it fits a privatisation pattern — flagged as inference), with the utility's stated justification included, and open questions about the valuation method left explicitly unresolved.
