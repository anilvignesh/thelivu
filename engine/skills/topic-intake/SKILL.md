---
name: topic-intake
description: Accept a topic or tip the user hands in ("look into X", "I came across this", "should we cover this?"), triage it for scope and worth, and if it qualifies, take it through the full pipeline — investigate, verify, write, review — to the human gate. Use whenever the user proposes a specific topic for Thelivu to consider. It is allowed to decline a topic that is out of scope, trivial, already saturated, or that fails verification — and it says why. The user's tip is a lead, not a finding; it still earns no special trust.
---

# Topic Intake

The third **lead source**: topics *you* bring in. Channels surface offbeat tips;
the beat-monitor catches buried developments; this is for the thing you personally
came across and want considered. All three converge on the same pipeline.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it
if present; the charter governs in any conflict.

## First, the discipline: your tip is a lead, not a verdict

A topic you hand in is treated exactly like a channel tip — **Tier 3, a lead**,
unless you supply a primary source. Your interest in it does not make it true and
does not exempt it from verification. The engine will still go to the record and
may still kill it. That is the system working, not the system doubting you.

## Public submissions (when a public tip line is open)

A tip from the public is a lead like any other — Tier 3 or lower, never truth, earning no shortcut past verification. Triage it through the same front gate, then the full pipeline. Two extra duties apply to public tips:

- **Protect the source.** If a tipster shares something sensitive, their safety comes first — never expose an identity, and never promise an anonymity the channel can't actually guarantee.
- **Guard against weaponisation.** People will try to use Thelivu to settle scores. A damaging claim about a named person, arriving from an anonymous tip, is the *lowest*-trust input there is — so it needs the *highest* bar of independent verification before it goes anywhere near print.

## Step 1 — The front gate: scope and worth

Before spending the full flow on a topic, triage it:

- **In scope?** Thelivu's beat is public-interest journalism, with a priority
  order that reflects its audience: Kerala first, India second, global third —
  but this is a *priority* order, not a hard filter. A global story that is
  under-reported, where dominant media (especially US/Western outlets) is
  distorting the picture, and where the truth matters to an Indian reader, is
  absolutely in scope. The geographic scope follows the story's impact and the
  evidence: a national water crisis is an India story; a specific government
  contract is a Kerala story; the Iran war with US media capture is a global
  story worth covering. Do not force a Kerala lens onto an India or global
  story. Decline only if there is genuinely no public-interest angle — celebrity
  gossip, personal grievances, or topics that are thoroughly and honestly
  covered elsewhere already.
- **Worth it?** Apply impact × under-coverage. If it's trivial, or already
  saturated everywhere (Thelivu doesn't pile onto the day's headline), say so and
  **park or decline** — with the reason.

Be honest and direct here. Declining a weak topic quickly is a feature; it's what
keeps the one-a-day standard high. You are allowed to say "not worth the time" or
"out of scope," and you should, when it's true.

## Step 2 — If it qualifies, run the full flow

Hand the lead through the pipeline, same as any other:

1. **investigate** — rebuild the topic from the open web (primary records,
   established news). Don't rely on how the tip was framed.
2. **verify** — run the trust gate (`source-verifier`). KILL / HOLD / READY.
3. **pattern-check** — only if a cross-story link genuinely suggests itself.
4. **write** — only if READY; transparent-perspective draft.
5. **review** — editorial-reviewer; framing, nuance, legal, confidence label.
6. **Hand to the human gate.** Publish only on the human's approval — the intake
   skill never publishes on its own. "Worth it and in scope" earns a *place in the
   queue*, not an automatic post.

## Decision vocabulary — exactly three, and you never wait for input

You are a one-shot function in an automated pipeline. **No human will reply to
you mid-run.** Your decision is final and must be one of exactly three:

- **PROCEED** — the topic is in scope and worth it. Emit the `STORY_BRIEF`. If the
  *submitted framing* was too strong, conspiratorial, or defamatory but a
  defensible public-interest story exists underneath, that is still **PROCEED** —
  you simply write the corrected, defensible angle into the brief's `Angle:` line.
  A reframe is a PROCEED with a fixed angle, **never** a request for a new brief.
- **PARK** — plausible but not now (saturated today, thin, better later). One line why.
- **DECLINE** — out of scope or not worth it. One line why, plus optionally one
  line: `Suggested alternative: <a sharper angle the owner could resubmit>`.

**Forbidden, always:** do not reply conversationally, do not "acknowledge" a
decision, do not say you "await" or "are ready to receive" a brief, do not ask the
owner anything. You either emit a `STORY_BRIEF` (PROCEED) or a one-line PARK/DECLINE
reason. Anything else breaks the pipeline.

> Wrong: "Understood — I've declined the original framing and am ready to receive a
> fresh brief for the redirected story." (waits for input, no Decision line, poisons
> every downstream stage)
> Right: "Decision: PROCEED" + a `STORY_BRIEF` whose `Angle:` is the corrected,
> defensible version of the topic.

## Output format

Always begin with a `STORY_BRIEF` block when the decision is PROCEED. Every
downstream skill in the pipeline receives this block as context — it is the
shared frame that keeps geography, angle, and scope consistent all the way to
the editorial reviewer. Fill it precisely; vague briefs produce drifting copy.

```
STORY_BRIEF
Geography: [National India | Kerala | India + Kerala | ...]
Angle: [one sentence — the core accountability claim or public-interest frame]
Scope: [what is in scope, what is explicitly out]
Key questions: [2–4 specific factual questions the investigation must answer]
Stakes: [who is affected and how — concrete, not generic]
END_STORY_BRIEF

# Topic Intake — [the topic, as submitted]

## Front-gate triage
- In scope: yes | no — [reason]
- Worth it (impact × under-coverage): yes | no | low — [reason]
- Decision: PROCEED | PARK | DECLINE

## Scoped lead for investigation
[Reframe the topic as a clean investigation brief — what to look for, what
primary records exist, what the key claims are and where to verify them]
```

## Example

Input: "I came across a claim that a Kerala co-op bank quietly wrote off big loans
to connected parties — worth covering?"
Output: **In scope** (Kerala, public-interest finance), **worth it** if true
(impact high, coverage thin) → PROCEED. Investigate pulls the bank's filings and
any regulator action; verify finds the write-offs confirmed in a primary record
but the "connected parties" angle only single-sourced → **HELD**, with the
required fix: corroborate the connected-party claim or run only the confirmed
write-off, framed straight. Nothing published; it goes to the human with that note.
