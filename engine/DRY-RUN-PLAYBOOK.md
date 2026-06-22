# Thelivu — Dry-Run Playbook (Validation Week)

**Purpose:** prove the pipeline on live stories before automating anything.
**Rule of the week:** *review only — publish nothing.* The output of this week is
not articles. It is a hardened ruleset and the confidence (or not) to automate.

---

## The morning trigger (~30–45 min)

1. Open Claude Code with the `news-engine` skills loaded — or just a Claude chat
   with the skills/charter pasted in. No bot, no cron, no API keys needed yet.
2. Say: **"Run today's Thelivu cycle on FYI."** The chain runs:
   - **monitor** — scan FYI's recent uploads; pick ONE topic worth chasing on
     impact × under-coverage. The channel is a *tip*, nothing more.
   - **investigate** — rebuild that topic from the OPEN WEB: primary records and
     established news. Ignore the channel's framing entirely.
   - **verify** — run the trust gate. Expect a lot of HOLDs early. That's healthy.
   - **pattern-check** — only if a cross-story link suggests itself; expect
     "not supported" often.
   - **write** — only if READY-FOR-HUMAN; transparent-perspective draft.
   - **review** — editorial-reviewer flags framing, nuance, legal.
3. Read the draft **and** the verification report.
4. **Stop. Do not publish.** Skip the publisher entirely this week.

---

## The daily log (record one row per run)

| Field | |
|-------|--|
| Date / source / topic picked | |
| Trust gate result (KILL / HOLD / READY) and why | |
| **Did verification catch a weak/unsupported claim?** | the key test |
| **Did the reviewer catch a loaded phrase or missing counter-case?** | the key test |
| **Did YOU catch anything the engine missed?** | the most important column |
| Time taken / quota or cost used | |
| Suggested charter or skill tweak | |

The third and fourth columns are why you're doing this. The fifth is the alarm:
every time *you* catch something the engine let through, that's a near-miss that
automation would have shipped.

---

## The tuning loop

Each time you catch something the engine missed, ask one question: **one-off, or
a rule?** If it's a rule, write it into the charter or the relevant skill before
the next morning. By Saturday the ruleset should be visibly tighter than Monday's.

---

## The gate to automate (decide at week's end)

Proceed to automation **only if** across the week:

- The verifier reliably caught weak and unsupported claims — no false claim ever
  reached a finished draft.
- The reviewer reliably caught loaded framing and missing counter-cases.
- Your gate catches were *minor polish*, never "it would have published something
  false or defamatory."
- The drafts are things you would actually have published.

If any of those fails: tune, and run another week. Automating a leaky pipeline
only scales the leak. A second or third validation week is a normal, healthy
outcome — not a delay.

---

## What this week is really testing

Not "can it write an article" — it obviously can. It's testing whether the
*guardrails hold on live material*: whether the gate kills the bad story, whether
the seams between fact and view stay visible, whether the channel's spin really
does get dropped at the door. Watch the failures more closely than the successes.
