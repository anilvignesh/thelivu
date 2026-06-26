---
name: source-verifier
description: Independently verify the claims in an evidence dossier or draft against a strict corroboration gate — count independent credible sources, check source independence and tier, confirm primary records, and assign each claim a verdict (Verified, Allegation-only, Unverified, or Failed), with authority to fail the whole story. Use whenever the user wants to fact-check, double-check sources, verify claims, confirm corroboration, or decide whether a story is solid enough to publish. Trigger for "verify", "fact-check", "double-check the sources", "is this solid", or "run it through the gate". This is the adversarial check — it does not trust the investigator.
---

# Source Verifier

This skill runs the **verification stage**, the independent, adversarial re-check that follows investigation. It assumes the investigator may have been sloppy, credulous, or motivated, and it re-verifies every claim from scratch. Its job is to be the hardest reader in the room — the one looking for the reason *not* to publish.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## Tool-failure protocol

If your web search tool returns only irrelevant results, thesaurus pages, Wikipedia country pages, or blanks across **all** queries, the tool has failed — this is a infrastructure problem, not a story problem.

In this case:
1. Document the tool failure explicitly in your output.
2. Output **HOLD** (not KILL) — tool failure cannot prove a story is unverifiable.
3. Write the verification report anyway based on what was in the dossier itself (internal consistency, source quality, logical coherence) — this is partial but honest.
4. Include a `BLOCKING-REASON: Tool failure — web search returned no usable results. Re-run once search is restored.` line.

A KILL requires positive evidence that claims are false or unsupported — absence of search results is not that.

---

## Do not trust the dossier

Re-check each claim against the original sources yourself. Do not accept the investigator's bucket tags — re-derive them. If a source link doesn't say what the dossier claims it says, that's a finding. Citations that don't support their claim are the single most common failure, and catching them is the whole point of this stage.

## The gate

For each factual claim, apply these tests:

1. **Corroboration count.** Require **two independent, credible sources** for a Fact verdict. One source ⇒ at most "Unverified — single source."
2. **Independence.** Two outlets that share an owner, a wire-service origin, or an obvious shared lean do **not** independently corroborate each other. Re-running the same press release is one source, not five.
3. **Source tier** (higher beats lower):
   1. Primary records (court, government/regulator data, filings, transcripts, datasets, peer-reviewed).
   2. Established news with editorial standards and a corrections record.
   3. Partisan / advocacy outlets — may establish that an allegation *was made*, never that it is *true*.
   4. Social / anonymous — never a basis for any verdict above "lead".
4. **Primary-record check.** If a primary record exists and is reachable, confirm the claim against it directly rather than trusting secondary summaries (which routinely distort figures and attributions).
5. **Allegation handling.** A contested claim can only ever be "Allegation-only" — verified as *said by X, denied by Y*, never as fact.

## Verdicts

Assign each claim exactly one:

- **Verified** — clears the corroboration, independence, and tier tests.
- **Allegation-only** — real, attributable, contested; publishable only as an attributed allegation with the denial.
- **Unverified** — single-source, thinly sourced, or uncheckable; not publishable as fact.
- **Failed** — the sources don't support the claim, or contradict it. Must be cut.

## Trust score — from verdicts to a gate

The per-claim verdicts feed a deterministic **trust gate**. Compute it by rule,
not by feel. The full spec — inputs, the step-by-step algorithm, the decision
table, worked examples, and edge cases — is in `references/trust-score.md`. Read
it. The core of it:

1. **Find the load-bearing claims** — the ones the story collapses without. When
   unsure, treat a claim as load-bearing. Only these gate.
2. **Resolve each** — apply the single-source guard (the tip channel never
   verifies its own tip → Unverified), the Verified sub-tests (≥2 independent
   sources; a primary/established source for anything consequential), and the
   Allegation-only conditions (attributed + denial included + not the sole
   basis).
3. **Aggregate the FACTS gate:** any load-bearing claim Failed → **KILL**; else
   any Unverified → **HOLD**; else → **FACTS-PASS**.
4. **Framing gate** (only after FACTS-PASS): the throughline must not lean on a
   cut claim, must carry the counter-case, and must label interpretation as
   interpretation → **READY-FOR-HUMAN**, or **FRAMING-FIX** back to the writer.

A story is only as strong as its weakest load-bearing claim — one unverified
load-bearing claim holds the whole thing. You are explicitly empowered to **KILL**.
A killed story is the gate working, not a failure.

## Recency check — a stale fact is a failed fact

Time-sensitive claims (share prices, valuations, net worth, "first/largest",
ongoing counts, who-holds-what) must be checked against **today's date**. A figure
that was true last month but has since moved is an ERROR, not a Verified claim —
mark it Unverified/Failed and note the current value. Search for the latest before
you pass any time-sensitive claim, and never let training memory override a more
recent source.

## Output format

```
# Verification Report — [story]

## Per-claim verdicts
| Claim | Load-bearing | Verdict | Independent sources | Best tier | Note |
|-------|--------------|---------|--------------------|-----------|------|
| A | yes | Verified | 2 | Primary | confirmed vs filing |
| B | yes | Unverified | 1 | 3 | only the tip source; single-source guard |
| C | no | Failed | 0 | — | cited source doesn't say this |

## Trust gate: KILL | HOLD | FRAMING-FIX | READY-FOR-HUMAN
## Blocking claims: [which load-bearing claims caused a KILL/HOLD]
## Required before it moves: [what to fix, add, cut, or downgrade]
## Triage score (advisory): 0-100
```

## Example

Input: a dossier claiming "the asset was sold at one-third its value."
Output: marks the *sale* Verified (government order = primary), the *valuation* claim Unverified (single partisan source, no independent valuation), and issues **Hold** with the required fix: obtain an independent valuation or downgrade the claim to an attributed allegation.
