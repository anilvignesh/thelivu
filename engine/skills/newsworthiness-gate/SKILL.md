---
name: newsworthiness-gate
description: A cheap absolute-floor check on a single selected lead, run AFTER news-monitor picks it and BEFORE the expensive investigation spine. It answers one question — is this the kind of story Thelivu exists to do — and drops commodity news before any tokens are spent investigating it. It judges newsworthiness only; it never verifies facts.
---

# Newsworthiness Gate

The last cheap checkpoint before the engine spends real money. news-monitor has
already picked the best lead from today's pool; this gate asks a different,
absolute question about that one lead: **is it worth investigating at all?**

news-monitor optimises *relative* ("best of the pool"). This gate enforces an
*absolute floor* ("does the winner clear the bar"). A weak pool can still produce
a "best" lead that is not worth a single token. That is exactly what this catches.

This skill enforces the editorial charter (`../../CHARTER.md`). Read it if present.

## The question

Thelivu does **under-covered, investigative, join-the-dots journalism on the side
of ordinary people.** Given that, is this lead worth investigating?

## DROP it (not our story) when it is:

- **Already well-covered.** Multiple mainstream outlets are already reporting it.
  Under-coverage is our whole reason to exist; wall-to-wall coverage means there
  is nothing for us to add. (A house move confirmed by five papers is not a lead.)
- **Routine political or administrative process** with no exposed accountability
  question: official-residence moves, appointments, swearing-in / oath-taking,
  cabinet reshuffles, ceremonial visits, ribbon-cuttings, foundation stones,
  courtesy calls. The *event* is not a story. Only a verifiable wrongdoing attached
  to it — misuse of funds, illegality, conflict of interest — would be.
- **Commodity daily news**: a development anyone can read anywhere, with no buried
  angle, no affected ordinary people, no "follow the dots" thread.
- **PR / press-release / product / personnel** with no accountability hook.
- **Anything whose only hook is "it's suppressed"** or that needs a conspiracy
  assumed to cohere.

## PURSUE it when it:

- Materially affects ordinary people's money, rights, health, safety, or
  governance — **and** is absent from, buried by, or distorted in mainstream
  coverage; or
- Is genuine new movement on a story the channel already tracks; or
- Exposes a concrete, checkable accountability question the mainstream is missing.

## When in doubt, PURSUE.

This gate exists to stop obvious waste, not to kill real stories. If a lead has a
plausible accountability thread and is not obviously well-covered, let it through
— the verifier downstream is the real filter for truth. Only DROP what clearly
fails the floor.

## Output (exactly this, nothing else)

```
VERDICT: PURSUE | DROP
REASON: <one line — why it clears or fails the floor>
```
