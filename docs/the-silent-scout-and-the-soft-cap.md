# Two things the 2026-08-08 dig turned up

*Context file. Requirement, diagnosis, design, and the checks the build has to
satisfy. Written before the code, compared against it after. Companion to
`alternating-desks.md`, which came out of the same session.*

---

## 0. First, a correction

I reported that `ek:belief-scout` "ran once, 3 calls on 2026-08-05, and added
zero rows — whatever it emitted did not survive `validate_candidate`."

**That was a misreading.** Those three calls are
`python -m engine.desks.ek.scout` without `--commit` — the inspection CLI at
`scout.py:590`, which calls `run_skill` directly, prints the raw output, and
writes nothing on purpose. Somebody was eyeballing the scout's proposals by
hand three times in two minutes. Identical input tokens (3,238) across all
three, varying output, no queue write: exactly the CLI's signature.

So `validate_candidate` is not implicated, and there is no parse regression.
What is true is worse and duller: **the scout has never run in committing mode
at all**, and the reason is §2.

---

## 1. The requirement

**Anil, 2026-08-08:** "fix them" — the two items left open at the end of the
alternating-desks change.

1. The belief scout is silent and has never produced a proposal.
2. The daily budget cap is $1.00 and the news desk hit $1.32 / $1.28 / $1.16.
   The governor parks work only *after* the cap is crossed, so it overruns.

---

## 2. The scout has never run, and its timestamp says it has

`run.py`, both the belief scout and the tech steward:

```python
last_bs = kv_get("last_belief_scout_at")
if not last_bs:
    kv_set("last_belief_scout_at", now_utc.isoformat())     # <- stamp, do not run
elif (now_utc - datetime.fromisoformat(last_bs)).days >= 7:
    kv_set("last_belief_scout_at", now_utc.isoformat())
    run_belief_scout()
```

On the first tick after the desks deployed, the key was unset, so the engine
**stamped it and did not run**. That does two things, and the second is worse
than the first:

- It defers the very first scout run by a full week.
- It writes a timestamp indistinguishable from a successful run. Production kv
  reads `last_belief_scout_at = 2026-08-04T04:09:38Z`, the command centre renders
  "last scout 04 Aug", and the honest value is **never**.

That is why the queue holds four rows and all four are `source='owner'`. The
scout was never asked. `PROJECT-STATUS.md`'s open item — "the scout has not run
against the live web" — was recording the symptom of a stamp, not a scout
problem.

**Fix:** on first sight, run it. A weekly sweep that has never run *is* due; the
"stamp, don't run" branch buys nothing (kv persists across deploys, so it fires
exactly once in the life of the key) and costs a week plus a false timestamp.
The retry-storm protection lives in the `elif` branch — stamp before running —
and is untouched.

The tech steward carries the identical branch. It has already had its first run
(`last_tech_steward_at = 2026-08-04`, with a real brief), so changing the pattern
there cannot fire a sweep on this deploy. Fixed anyway: the same latent bug, one
line apart.

## 3. The scout speaks only to Telegram

Owner's rule, 2026-08-05: nothing the engine says may live only in Telegram. That
change put the capture inside `_notify_card` "so every future card is recorded by
construction" — and it did, for all nineteen card sites.

**`_notify` was left as an uncaptured back door.** It is plain text straight to
`_tg_send_long` with no `record_event`, and thirteen engine call sites still use
it: the scout's proposal notice, the belief desk's own "run #N is ready", the
daily cycle's "no leads in the queue", "news-monitor returned no usable
selection", "picked an out-of-range lead", source-scout's results,
meta-synthesis, and a carousel-generation failure. Every one of those is exactly
the sort of thing the rule was written about.

The scout is the worst of them because it is *conditionally* silent:

```python
if added:
    _notify(f"🧠 Belief scout: {added} new candidate(s)...")
```

A run that proposes nothing, parses nothing, or rejects everything says nothing
at all — no card, no row, one INFO line on Railway. Indistinguishable from a
scout that never ran, which is precisely the state we could not diagnose.

**Fix, in one place rather than thirteen:** `_notify` records first, then posts,
the same order and the same reasoning as `_notify_card` — a Telegram outage must
not destroy the only copy. A plain notification has no title, so the first line
becomes the title and the remainder the body. Then **no engine utterance can
bypass capture**, which is what the 08-05 change was reaching for.

Separately, the scout reports **every** outcome, not just a productive one.

Out of scope, deliberately: `run.py:_tg_notify`, `command_center/api/runs.py`
and `dashboard.py` have their own local senders. Those are operator actions
initiated from a UI that already displays them, not the engine speaking
unprompted.

## 4. The cap is a cap only at tick granularity

The governor is correct and it is checked in the right place — top of the loop,
above every model stage, below the breaker. It is checked **once per tick**, and
then `run_daily_cycle()` runs to completion with no further check. So the cap
cannot bound a day; it can only refuse to *start* a tick.

That is not sloppiness, it is the module's stated intent: the docstring exists to
prevent "a balance draining to zero mid-spine … a story half-verified, a draft
never written." A hard mid-spine abort would manufacture the exact failure the
governor was built to avoid. **So the fix must not be a mid-cycle kill.**

**Measured, 63 real cycles over 21 days** (token_usage clustered into bursts
separated by >20 min of silence, costed with the current rate table):

| | per cycle |
|---|---|
| min | $0.056 |
| p50 | $0.211 |
| p80 | $0.337 |
| p95 | $0.993 |
| max | $1.090 |

**Fix: park before starting a cycle the day cannot afford, not after.** A
`reserve` — park when `spent + reserve > cap` rather than `spent >= cap`.
Default **$0.35**, the measured p80, in kv `daily_budget_reserve_usd` so it is
tunable without a deploy.

**What this does and does not buy, stated plainly because it is a throughput
cut:** at a $1.00 cap the engine now parks model work at $0.65 instead of $1.00.
Roughly 80% of cycles fit in the reserve, so most days land under the cap instead
of over it. The p95/max tail still overruns — a cycle that costs $1.09 breaks a
$1.00 cap whichever end you check, and the only cure is the mid-spine abort we
are refusing on purpose. The cap becomes *usually honoured* rather than
*routinely exceeded*; it does not become inviolable, and this file should not
pretend otherwise.

The skip must be visible: a parked cycle logs and alerts with the reserve named,
so "why did nothing run today?" is answerable from the dashboard.

---

## 5. Files

| file | change |
|---|---|
| `run.py` | first-sight sweeps run instead of stamping (scout + steward); reserve wired into the governor block |
| `shared/budget.py` | `reserve_usd()`, `set_reserve_usd()`, `is_over_budget()` honours the reserve |
| `engine/agents/orchestrator.py` | `_notify` records before posting |
| `engine/desks/ek/scout.py` | the scout reports every outcome, not only a productive one |
| `command_center/api/system.py` | reserve in the System view payload + setter |
| `engine/desks/ek/tests/run_cadence_cases.py` | scout-always-speaks cases |
| `shared/tests/run_budget_cases.py` | new — reserve cases |
| `PROJECT-STATUS.md` | log all of it |

---

## 6. What the build must satisfy

The scout:

1. A run that adds candidates records an event **and** posts.
2. A run that parses zero candidates records an event saying so — the case that
   was silent.
3. A run where everything is rejected records an event naming the rejections.
4. A run that raises records an event naming the failure, and does not take the
   tick down with it.
5. `record_event` failing does not stop the Telegram post, and `_tg_post`
   failing does not stop the record. Neither may lose the other.

The stamp:

6. First sight of an unset `last_belief_scout_at` **runs** the scout.
7. The `elif` still stamps before running, so a raising sweep cannot retry-storm.

The budget:

8. `reserve_usd()`: unset → 0.35; explicit '' or '0' → 0; junk → the default;
   negative → 0; clamped above by the cap itself (a reserve ≥ cap would park
   everything for ever — that is an off switch, not a budget).
9. `is_over_budget()` at cap $1.00, reserve $0.35: $0.60 spent → under;
   $0.70 → over. At reserve 0 the old behaviour returns exactly: $0.99 → under,
   $1.00 → over.
10. Attended mode still returns None regardless of reserve.
11. A disabled cap (None) is still uncapped whatever the reserve says.
12. The alert names the reserve, so the parked day is explicable.

Non-regression:

13. Existing cadence + caption + carousel suites unchanged and passing.
14. The belief desk's own `BUDGET_HEADROOM` check is independent of the reserve
    and keeps its 0.55-of-cap meaning (`alternating-desks.md` §3.3).

---

## 7. Found while building (not anticipated above)

**A NaN reserve would have uncapped the engine.** Caught by check 8 on the first
run of the new suite. `float("nan")` parses, and `nan <= 0` is False, so a typo'd
kv value flowed straight through the guard — after which `spent + nan >= cap` is
False for ever and the governor silently stops parking anything. Exactly the
class `cadence_days` already had a comment about ("NaN fails both comparisons and
falls through to the default") and the reserve had not inherited.
`math.isfinite` now gates both NaN and inf.

**The overview banner was reading a 48% undercount, and I made it load-bearing.**
The 2026-08-05 cache-accounting change converted the governor, the steward's
view and the cost report, and **missed `shared/db.get_daily_costs`** — which
selects only `input_tokens`/`output_tokens`, so the command centre's overview
priced today at **$0.2967** while the governor priced the same day from the same
table at **$0.5707**. Harmless while the banner was decorative; not harmless once
`over` came from it. Both callers were passing three args to a five-arg
`cost_usd`, so nothing raised.

Two callers, both fixed: the overview banner (`command_center/api/system.py`) and
the 30-day trend line in the Costs view (`command_center/api/ops.py`), the latter
drawing a lower number than the by_model table directly above it, which had been
converted. `get_cost_report_data` was already correct.

**The same banner was keyed to local time.** `datetime.date.today()` is
Asia/Kolkata; the governor's day is a UTC day that self-expires at midnight UTC.
For the five and a half hours either side of the boundary the banner would report
a different day's spend than the one being enforced. Now UTC on both sides.

Verified after the fix: `/api/overview` and `/api/system` both report
`spent_today_usd: 0.5707`.

**One consolidation.** `over` was being computed independently in three places
(`shared/budget.status`, `util.budget_state`, and inline in the overview). The
reserve would have had to be added to all three, so `util.budget_state` is now
the single implementation and takes optional pre-fetched `cap`/`reserve` — the
overview passes both from its existing fan-out, so the banner still costs no
round trip of its own (`command_center/db.py` perf note: round trips dominate).
