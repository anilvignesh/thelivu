# Alternating desks — giving the belief desk a turn it can count on

*Context file for the 2026-08-08 change. Requirement, design, and the checks the
build has to satisfy. Written before the code, compared against it after.*

---

## 1. The requirement

**Anil, 2026-08-08:** "lets alternate."

The belief desk (`desk='ek'` / `'gk'`) has produced nothing unattended since it
was built. Not because it is broken — because it can never win the budget test
it is asked to pass. Alternate the two desks so the belief desk gets a
**guaranteed turn** instead of competing for leftovers.

Chosen shape (of three offered): **belief goes first on its turn day, news gets
the rest.** The news desk publishes every day; on a belief day it runs second,
with whatever the belief piece did not spend.

Explicitly NOT chosen:
- News standing down entirely on belief days (halves news output).
- A hard per-desk budget ceiling (more code than the problem needs; measurement
  below shows the ceiling would never bind).

---

## 2. Why it is stuck today — the evidence

`engine/desks/ek/scout.py:56` sets `BUDGET_HEADROOM = 0.55`, and
`run_belief_cycle` stands down when `spent >= cap * 0.55`. `run.py:402` places
the belief block **after** the RSS block on purpose, so the headroom check reads
a spend figure that already includes today's news work.

Both halves are individually reasonable. Together they are unsatisfiable: the
RSS cycle fires at ~00:02 UTC and clears 55¢ of the $1.00 cap in its first pass,
so the belief desk is asked the question only once the answer is already no —
and a day's spend never goes back down.

Production `kv_store` on 2026-08-08:

```
last_belief_cycle_result = "skipped: $0.57 of the $1.00 cap already spent
                            — the news desk has the prior claim on it"
last_belief_run_at       = 2026-08-01T05:22:56Z
```

Daily spend recomputed from `token_usage` with the current rate table — the
belief desk needed a day under $0.55 and never got one:

| date | spend | headroom? |
|---|---|---|
| 2026-08-01 | $1.07 | no |
| 2026-08-02 | $1.28 | no |
| 2026-08-03 | $0.56 | no (by 1¢) |
| 2026-08-04 | $1.02 | no |
| 2026-08-05 | $1.14 | no |
| 2026-08-06 | $1.32 | no |
| 2026-08-07 | $0.86 | no |
| 2026-08-08 | $0.57 | no |

Belief #3 (Koh-i-Noor) has sat `approved` with `run_id: null` since the 08-05
event card *"Belief cadence armed for its first unattended run."* It was armed.
It has never had a day to fire in.

**What a belief run actually costs.** Summed per-call averages across the five
desk skills (`ek:premise-check` $0.0034, `ek:record-builder` $0.0066,
`ek:record-verifier` $0.030, `ek:explainer-writer` $0.031,
`ek:explainer-reviewer` $0.024) ≈ **$0.10–0.20** per piece with revision loops.
That is the number that makes "news gets the rest" safe: on a belief day the
news desk still has ~$0.80 of a $1.00 cap. A reserved slice would never bind.

---

## 3. The design

### 3.1 Alternation is the cadence, not a calendar

No new parity key. `cycle_due()` already answers "is it the belief desk's
turn", and `LAST_RUN_KEY` is already stamped when a piece runs. Alternating =
**`DEFAULT_CADENCE_DAYS` 3 → 2**.

This makes the alternation *turn-taking*, not day-parity: if a turn is missed
(engine down, budget genuinely gone), the desk stays due and takes the next
available day rather than waiting a full extra cycle for its parity to come
round. Self-correcting, and nothing new to keep in sync.

### 3.2 The turn must not be lost to a one-minute race

`cycle_due` compares **elapsed seconds** against `cadence_days * 86400`. With a
2-day cadence that is a bug waiting to fire:

```
belief run stamps  Mon 00:03:10
Wed 00:02 tick  ->  47h58m elapsed  <  48h  ->  NOT due
                    RSS cycle starts, spends past the headroom
Wed 00:04 tick  ->  due at last, but the budget is gone
```

The desk would lose every other turn to a ninety-second margin, and the failure
would look exactly like the bug being fixed. **Whole-day cadences compare UTC
dates, not elapsed seconds**, so the turn boundary lands on the same midnight
the news cycle keys off.

Sub-day cadences (`MIN_CADENCE_DAYS = 0.5`) cannot be expressed as whole dates
and keep the elapsed-seconds path. The split is on `cadence >= 1`.

### 3.3 The ordering flips on the turn day

`run.py`: the belief block moves from **after** the owner-topic/RSS block to
**before** it. On a turn day the belief cycle sees a fresh $0.00 cap, passes the
headroom check on its own merits, and spends its ~$0.15 first. The RSS cycle
then runs with ~$0.85.

On a non-turn day the moved block is a no-op (`cycle_due` false), so the news
desk's behaviour is byte-identical to today.

**`BUDGET_HEADROOM` stays at 0.55 and keeps its job.** It no longer blocks the
ordinary turn, but it still guards the two cases where a belief run would be
genuinely wrong: a `force_belief_run` tapped at 3pm on a spent day, and a turn
day whose engine only came up at 20:00 after a restart. In the second case the
stand-down does not stamp `LAST_RUN_KEY`, so the turn carries to tomorrow.

The old comments in `scout.py:50-57` and `run.py:402-413` argue for the
*opposite* ordering. They are now wrong and must be rewritten, not left to
contradict the code.

### 3.4 The turn is visible in the command centre

Standing rule: the dashboard has everything. `beliefs_state` gains
`next_turn_utc` and `turn_today`, so the Beliefs view can say when the desk runs
next instead of leaving `last_belief_cycle_result` as the only clue.

---

## 4. Files

| file | change |
|---|---|
| `engine/desks/ek/scout.py` | `DEFAULT_CADENCE_DAYS` 3→2; date-aligned `cycle_due`; `next_turn_utc()`; rewrite the `BUDGET_HEADROOM` docstring |
| `run.py` | move the belief block before the owner-topic/RSS block; rewrite the ordering comment |
| `command_center/api/beliefs.py` | expose `next_turn_utc` / `turn_today` |
| `command_center/static/app.js` | show the next turn in the Beliefs view |
| `engine/desks/ek/tests/run_cadence_cases.py` | cases in §5 |
| `PROJECT-STATUS.md` | log the change and close the "cadence never fired unattended" item once it does |

---

## 5. What the build must satisfy

Cadence and turn-taking:

1. Unset cadence → **2**, not 3.
2. A stamp 1 day old, cadence 2 → not due.
3. A stamp 2 days old, cadence 2 → due.
4. **The midnight race:** stamp `Mon 00:03:10`, now `Wed 00:02:00`, cadence 2 →
   **due**. Fails on the elapsed-seconds implementation; this is the case the
   whole §3.2 change exists for.
5. Same-UTC-day stamp, however many hours ago → not due (a turn is one per day).
6. Cadence 0.5 still uses elapsed seconds: stamp 11h ago → not due; 13h → due.
7. The existing guards survive: naive stamp → due; unparseable → due; future
   stamp → due; never run → due.

Ordering and budget:

8. On a turn day with $0.00 spent, `run_belief_cycle` runs the piece (headroom
   passes on a fresh cap).
9. A forced run on a spent day still stands down over the headroom, and the
   reason still names the figure.
10. A stand-down does **not** stamp `LAST_RUN_KEY` — the turn carries.
11. A completed run **does** stamp it, and the desk is then not due tomorrow.

Non-regression:

12. All pre-existing cases in `run_cadence_cases` still pass, with case 1 and the
    cadence-3 cases updated to the new default rather than deleted.
13. `run.py` imports cleanly and the belief block appears exactly once.

---

## 6. Open after this

- The scout has run once (3 calls, 2026-08-05) and added **zero** rows, all four
  `belief_queue` entries being `source='owner'`. Whatever it emitted did not
  survive `validate_candidate`, and **no event card was written** — a silent
  scout breaks the nothing-lives-only-in-Telegram rule. Not in scope here.
- The daily cap is $1.00 and the news desk hit $1.32 / $1.28 / $1.16: the
  governor parks work only *after* the cap is crossed, so the cap overruns by
  design. Alternation does not change that.
