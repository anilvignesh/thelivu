# News Engine — Skill Package

A modular, human-in-the-loop pipeline for surfacing **verified, high-impact, under-reported** news (Kerala first, India second). Four skills do the work in sequence; **you are the final guard** before anything publishes.

Governing document: [`CHARTER.md`](./CHARTER.md). The skills operationalise it; the charter wins any conflict.

## The pipeline

```
  ┌─────────────┐   candidate   ┌──────────────────┐   evidence    ┌─────────────────┐
  │ news-monitor │──  queue   ──▶│ news-investigator │──  dossier  ──▶│ source-verifier │
  └─────────────┘               └──────────────────┘               └────────┬────────┘
        ▲                                                                    │ verification
        │ tracks follow-ups                                                  │ report
        │                          ┌────────────────────┐   review     ┌─────▼──────────┐
        └────────── publish ───────│   ★ HUMAN GATE ★   │◀── verdict ──│ editorial-      │
                  (Telegram bot)   │  you approve/kill  │              │ reviewer        │
                                   └────────────────────┘              └─────────────────┘
```

Each stage hands the next a **defined artifact**, so the chain is auditable:

| Stage | Skill | Input | Output |
|-------|-------|-------|--------|
| 1 | `news-monitor` | a beat | ranked **candidate queue** (leads only) |
| 2 | `news-investigator` | one lead | **evidence dossier** (claims + sources, bucketed) |
| 3 | `source-verifier` | the dossier | **verification report** (per-claim verdicts; Pass/Hold/Kill) |
| 4 | `editorial-reviewer` | a verified draft | **editorial review** (Ready/Fix/Hold/Kill + edits) |
| 5 | **you** | the review + draft | **approve → publish**, or send back, or kill |

## Why it's split into four

Separation is the safeguard. The investigator is allowed to be enthusiastic; the verifier is built to distrust it; the reviewer ignores whether the facts are true and asks only whether the *writing* is fair and safe. No single stage can push a story to readers on its own — and none of them can publish at all. That's the structural reason this stays a newsroom and doesn't drift into a propaganda feed.

## The two hard guarantees

1. **Nothing auto-publishes.** Every story stops at the human gate. The bot only posts what you have explicitly approved.
2. **Under-coverage selects, it never confirms.** Obscurity tells the engine what to look at, never what to believe. Obscure claims clear a *higher* bar, not a lower one.

## Running it

These follow this environment's Agent Skills format (`SKILL.md` per folder), so they load in Claude Code or Cowork. Two ways to drive them:

- **Manual / on-demand:** invoke a skill at a time — e.g. "run a Kerala monitoring cycle", then "investigate lead 2", then "verify this dossier", then "review this draft". Good while you're tuning the charter.
- **Routine / scheduled:** wire the chain into a recurring task that runs monitor → investigator → verifier → reviewer and **drops finished candidates into a review queue** (a private Telegram drafts chat, a Slack channel, or a doc) for you. It stops there. You read, approve, and post.

The publisher (approved draft → Telegram channel) is deliberately **not** a skill in this package — it's the one step that should stay in your hands and your credentials. Build it as a small separate script once you're happy with what comes out of stage 4.

## Tuning

Treat `CHARTER.md` as the source of truth and edit it first; the skills point back to it. If you change the corroboration bar (e.g. require a primary record for any claim naming a person), change it in the charter and in `source-verifier`. Re-read the symmetry test in the charter every so often — it's the rule most likely to quietly erode.

## Suggested first test

Run one real Kerala story end to end — monitor → investigator → verifier → reviewer — and read what lands at the gate. The useful question isn't "is the story good"; it's "did the verifier catch the weak claim, and did the reviewer flag the loaded phrase." If both did their job on a live example, the pipeline works.
