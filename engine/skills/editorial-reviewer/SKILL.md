---
name: editorial-reviewer
description: Apply the editorial charter to a near-final news draft — check neutrality and symmetry, framing and language, fact/allegation/inference labeling, named-person and defamation safety, source transparency, and a confidence label — then return a publish-readiness verdict with specific required edits. Use whenever the user wants an editorial review, a charter or compliance check, a bias or framing check, a defamation/legal sanity check, or a final pre-publication pass before the human gate. Trigger for "review this", "is it ready to publish", "check it against the charter", or "bias check". This is the last automated gate before the human approves.
---

# Editorial Reviewer

This skill runs the **fourth and final automated stage**, just before the human. The verifier already confirmed the facts hold; this stage checks whether the *piece as written* is fair, clean, legally safe, and charter-compliant. It catches the failure mode where every fact is true but the framing quietly editorialises.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## What to check

Run the draft against five checks. For each, return PASS or the specific fix needed.

1. **Neutrality and symmetry.**
   - Does the language lead the reader to a verdict the facts don't compel? Strip adjectives doing argumentative work.
   - Apply the symmetry test: if this exact story implicated the side the channel is sympathetic to (the LDF/Left, or critics of Adani/Ambani), would it be written the same way? If not, rebalance.
   - Is the opposing or subject's account present and stated fairly, not as a strawman?

2. **Framing and language.**
   - No "what they don't want you to know", no "exposed", no manufactured-suspense framing. The facts carry the weight.
   - No rhetorical questions standing in for claims the piece can't make outright.

3. **Labeling integrity.**
   - Is every statement still correctly Fact / Allegation / Inference? Confirm nothing the verifier marked Allegation-only or Inference is now phrased as fact.
   - Are inferences ("this fits a pattern of…") clearly flagged as interpretation?

4. **Named-person and defamation safety.**
   - Is any living person or company tied to a damaging claim that isn't Verified? If so, it must be cut or converted to an attributed, denied allegation.
   - Is every allegation attributed to its source *and* accompanied by the subject's response or a note that response was sought?
   - Flag anything a defamation lawyer would circle. When unsure, recommend the human get a legal read.

5. **Transparency.**
   - Are sources linked? Is provenance noted where a lead came from a partisan source? Is a confidence label assignable?

6. **Self-similarity (anti-monotony).**
   - Compare the draft's *opening device, throughline, and conclusion* against the last several pieces (read them from the archive). If the hook (e.g. a "two truths" paradox), the spine (e.g. "ordinary people vs private capital"), or the landing (e.g. "watch whether they invest or privatise") echoes a recent pattern, FLAG it.
   - The deeper test: could a regular reader guess this piece's verdict from its topic alone? If the outlet keeps reaching the same political conclusion, that is a house line asserting itself, not the evidence speaking — and a predictable outlet is a discounted one.
   - The fix is never to bend the facts. It is to find the angle THIS story has that the last one didn't — a different structure, a different stake, or the honest admission that the obvious frame doesn't fit here. Sometimes the public-interest story is praise; sometimes it holds the CURRENT government to account; sometimes there is no villain at all. Vary deliberately.

## Output format

```
# Editorial Review — [story]

## Checks
1. Neutrality & symmetry: PASS | FIX — [what]
2. Framing & language: PASS | FIX — [what]
3. Labeling integrity: PASS | FIX — [what]
4. Named-person / defamation: PASS | FIX — [what]
5. Transparency: PASS | FIX — [what]
6. Self-similarity / monotony: PASS | FIX — [what recent piece it echoes, and the fresh angle to take]

## Suggested confidence label: Confirmed | Developing | Contested

## Verdict: Ready | Fix-then-publish | Hold | Kill
## Required edits before it reaches the human: [numbered list, or "none"]
## Flag for human legal review: Yes | No — [why]
```

Note the verdict is a recommendation **to the human**, who remains the final guard. This stage never publishes.

## Example

Input: a fully verified draft that nonetheless calls a transaction "a brazen giveaway to cronies."
Output: facts PASS, but Neutrality and Framing return FIX — "brazen giveaway to cronies" asserts motive and corruption the verification didn't establish; replace with the neutral description of the transaction and let the reader judge. Verdict: Fix-then-publish.
