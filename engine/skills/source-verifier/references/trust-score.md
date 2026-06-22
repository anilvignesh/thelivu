# Trust Score — the gate specification

The deterministic logic that turns the verifier's per-claim verdicts into one
gate decision for a story. It is **categorical, not a vibe**: a story passes or
it doesn't, on rules. The optional 0–100 number at the end is for triage only —
never a publish criterion.

The cardinal principle: **a story is only as strong as its weakest load-bearing
claim.** One unverified load-bearing claim holds the whole story.

---

## Inputs (per claim, from the verifier)

| Field | Values |
|-------|--------|
| `verdict` | Verified / Allegation-only / Unverified / Failed |
| `independent_sources` | integer (genuinely independent only) |
| `best_tier` | 1 primary · 2 established news · 3 partisan/advocacy · 4 social/anon |
| `load_bearing` | true / false |
| `only_origin_source` | true if the originating channel is the sole source |

---

## Step 1 — Identify load-bearing claims

A claim is **load-bearing** if removing it would collapse or materially change
the article's core. Background colour is not load-bearing. **When unsure, treat
it as load-bearing** — erring toward more scrutiny is the safe error.

Only load-bearing claims gate. Decorative claims still must not be false, but a
weak decorative claim is cut, not a reason to hold the story.

## Step 2 — Resolve each load-bearing claim

Apply in order:

1. **Single-source guard.** If `only_origin_source` is true, OR the sole support
   is one Tier-3/4 source → force `verdict = Unverified`. The tip source never
   verifies its own tip.
2. **Verified sub-tests.** A `Verified` claim must have `independent_sources ≥ 2`.
   If it names a person/company or is otherwise consequential, it must also have
   `best_tier ≤ 2` (at least one primary or established source). Fail either test
   → downgrade to `Unverified`.
3. **Allegation-only conditions.** Permitted to remain in the story **only if**
   all three hold: it is attributed to a named source; the subject's denial or
   response is included; it is not the sole basis of the article. Otherwise →
   treat as `Unverified`.
4. Leave `Failed` and `Unverified` as they are.

## Step 3 — Aggregate to the FACTS gate

Scan the resolved load-bearing claims:

- any **Failed** → **KILL**
- else any **Unverified** → **HOLD**
- else (all Verified, or permitted Allegation-only) → **FACTS-PASS**

## Step 4 — Framing gate (only if FACTS-PASS)

A facts-pass is **not** publish approval. Check the throughline:

- It must **not depend** on any claim that was Failed, Unverified, or cut.
- It must fairly state the **strongest counter-case**.
- Anything beyond the verified facts — motive, intent, "this is part of a
  pattern" — must be **labelled as interpretation**, not asserted. (Under the
  transparent-perspective stance the view is allowed; disguising it as fact is
  not.)

Pass → **READY-FOR-HUMAN.** Fail → **FRAMING-FIX** (back to writer/editor).

## Step 5 — Output

```
gate: KILL | HOLD | FRAMING-FIX | READY-FOR-HUMAN
blocking_claims: [...]            # what caused a KILL/HOLD
required_actions: [...]           # what would move it forward
triage_score: 0-100 (advisory)
```

**Triage score (advisory only).** A rough priority number, e.g.:
`60×(share of load-bearing claims at Tier 1) + 30×(min independent sources, capped) + 10×(impact 0–1)`.
Use it to order the day's READY-FOR-HUMAN queue. Never use it to publish — a
high number with a HOLD still holds.

---

## Decision table

| Load-bearing claim states | Gate |
|---|---|
| any Failed | KILL |
| no Failed, any Unverified (incl. single-source, downgraded) | HOLD |
| all Verified / permitted Allegation-only, framing fails | FRAMING-FIX |
| all Verified / permitted Allegation-only, framing passes | READY-FOR-HUMAN |

---

## Worked examples

**KILL.** Central claim: "the minister said privatisation is the only way." The
cited clip shows the opposite — the minister denied any privatisation plan. The
load-bearing claim is **Failed** → **KILL**. (This is the real error from the
project's own history; the gate catches it.)

**HOLD.** Claims: (A) a public asset was transferred to a private operator —
Verified against the government order (Tier 1); (B) at one-third its value —
only the tip channel asserts it, no independent valuation → single-source guard
→ Unverified. (B) is load-bearing → **HOLD.** Required action: obtain an
independent valuation, or downgrade (B) to an attributed allegation.

**READY-FOR-HUMAN.** Claims: KIIFB raised masala bonds in 2019 (Verified,
multiple + primary); the 2026 white paper recommends disinvestment (Verified,
established news + the document); the "industry wish-list" reading is labelled
interpretation, the government's denial is included, the counter-case (audit is
warranted) is present. Facts pass, framing passes → **READY-FOR-HUMAN.**

---

## Edge cases

- **Everyone agrees, but it's an echo.** All sources share an owner or lean →
  not independent → counts as one source → HOLD. Consensus inside a bubble is
  not corroboration.
- **Primary contradicts secondary.** The filing says something different from
  the reporting → primary wins; the claim may Fail.
- **Important but unverifiable.** A topic can matter and still fail the gate.
  HOLD or park it. It may run only as "X reports; we could not independently
  confirm," clearly framed — never as fact.
- **The story IS an interpretation** (an explainer, not a scoop). The *facts* it
  rests on still gate in Steps 1–3; the interpretation itself goes through the
  Step 4 framing gate. You verify the facts; you judge the argument.
