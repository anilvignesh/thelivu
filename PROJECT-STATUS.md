# Thelivu — Project Status & Continuation Guide

*Read this to pick up the project where the build session left off. It's the living
state of the work — update it as you go. For how the engine runs, see
`engine/START-HERE.md`; for why each rule exists, see `engine/CONTEXT-AND-HISTORY.md`.*

---

## Kerala/CAG duplication fixed at the root — dig-creation blindness + paraphrase-proof dedup (2026-08-15)

Anil flagged the pipeline as "obsessed with Kerala and CAG reports, so many similar
articles." Traced to three compounding, independently-diagnosed causes — not one bug:

1. **`beat-monitor`'s CAG beat re-surfaced the same 2-3 audit reports daily**, and
   the lead-pool dedup key (`sha1(throughline)`, `orchestrator.py`) is exact-string —
   trivially defeated when the model re-describes the same finding in different
   words. Proof: Aug 5 alone produced 5 separate `pipeline_runs` rows (#150-155) all
   describing the identical ₹54,282cr CAG utilisation-certificate finding. **Fix:**
   `beat-monitor` is now handed its own last-14-days throughlines
   (`get_recent_leads_by_source`, `shared/db.py`) and told explicitly to skip a
   candidate if it's the same underlying finding as one already listed, reworded or not.
2. **Two independent dig-creation paths were blind to what was already open.**
   `run_story_scout` (weekly) was told to skip themes "already in progress" but was
   only ever shown the static `watchlist.yaml`, never the `digs` table. `run_chief_of_staff`
   (daily) proposed `NEW_DIGS` from a snapshot that showed it only parked/killed digs,
   never active ones — and its own SKILL.md few-shot example was literally titled
   *"Kerala cooperative bank stress,"* actively anchoring it toward the exact duplicate.
   Result: that theme alone was opened as a fresh dig 5 times (dig #4, #5, #19, #27, #29)
   over three weeks. **Fix:** both paths now see the open-digs list before creating
   anything; `chief-of-staff/SKILL.md` explicit rule added ("check open digs, recommend
   `advance` on the matching `dig-<id>` instead of duplicating"); the anchoring example
   swapped for an unrelated one (SEBI settlements).
3. **Digs never converged, so duplicates never had a chance to merge back.** 28 digs
   opened since Jul 15; exactly 1 ever reached `ready-to-write`; **zero** were ever
   parked or killed despite the skill's own stated discipline ("publishing nothing is a
   successful dig"). **Fix:** `run_dig_advance` now auto-parks a dig after 8 advances or
   21 days without reaching `ready-to-write`/`parked`/`killed` — it can be revived
   manually if something genuinely new lands.
4. **`watchlist.yaml` itself was structurally stacked**: 3 of 8 standing themes were
   explicit CAG/Kerala-finance, and 7 of 8 carried a Kerala anchor, despite
   `story-scout/SKILL.md` saying the anchor should be "a bonus, never the price of
   entry." **Fix:** merged `cag-findings-follow-up` into `public-money-flows` (same
   question, was itself producing duplicate digs), broadened `cooperative-bank-health`
   to national scope with Kerala as an optional strongest-case anchor rather than the
   default, and added two new non-Kerala/non-CAG themes (`digital-lending-enforcement`,
   `gulf-migrant-labour-pipeline`) so the "ripest theme" pick isn't structurally
   pre-biased. 10 themes now, 1 without a Kerala requirement at all.

**Immediate cleanup applied to the live backlog** (not just future prevention): of 28
open digs, 15 were near-duplicates of another open dig on the exact same question —
5× Kerala coop-bank stress, 5× CAG Kerala fiscal, 5× NEET/exam integrity, 2× internet
shutdowns, 2× leptospirosis, 2× E20 ethanol. Consolidated each cluster into its most-
advanced member and parked the rest with a note pointing at the survivor. **28 open
digs → 13**, none duplicated.

**Left for Anil:** dig #2 (E20 ethanol) has been sitting at `ready-to-write` since
2026-07-18 with 9 logged advances and was never promoted to the pipeline — worth a
manual `promote_dig(2)` or a look at why nothing does that automatically for
long-`ready-to-write` digs (possible follow-up: chief-of-staff should recommend
promoting stale `ready-to-write` digs, not just advancing/killing).

---

## How to continue in Claude Code (or a fresh chat)

A new assistant will **not** have the conversation that built this — it starts cold.
But the files were written to carry the operating context, so it doesn't need the
chat. To bootstrap it:

1. In Claude Code: open this repo and copy `engine/START-HERE.md` to **`CLAUDE.md`**
   at the repo root, so Claude Code auto-loads it. (Or just tell it to read the file.)
   Then read **`docs/HANDOFF.md`** — the operational layer: deployed topology,
   Railway/DB access, and the gotchas that cost real debugging time.
2. Say: *"You are continuing Thelivu. Read CLAUDE.md (START-HERE),
   engine/CONTEXT-AND-HISTORY.md, and PROJECT-STATUS.md, then [your task]."*
3. It now has the charter, the method, the history, and the state below. The only
   thing it lacks is the verbal reasoning of the original session — summarised here.

---

## The silent scout and the soft cap (2026-08-08)

Both items left open by the alternating-desks change, fixed. Full working:
`docs/the-silent-scout-and-the-soft-cap.md`.

**Correction first.** The claim that `ek:belief-scout` "ran once and added zero
rows, so its output did not survive `validate_candidate`" was a **misreading**.
Those three 2026-08-05 calls are `python -m engine.desks.ek.scout` *without*
`--commit` — the inspection CLI, which prints and writes nothing by design.
Identical input tokens across all three. `validate_candidate` is not implicated.

**The scout had never run at all, and its timestamp said otherwise.** run.py's
sweep pattern was `if not last_X: kv_set(now)` — stamp and skip. On the first
tick after the desks deployed it stamped `last_belief_scout_at = 2026-08-04` and
did not run, which deferred the first scout run by a week *and* wrote a value
indistinguishable from a successful one. The command centre read "last scout 04
Aug"; the honest answer was **never**. Four days of an empty queue were blamed on
the scout's output before anyone looked at the stamp. A weekly sweep that has
never run **is** due, and kv persists across deploys, so first sight now runs it.
The tech steward carried the identical branch (already stamped in production, so
the fix cannot fire a sweep on this deploy) and is fixed the same way.

**`_notify` was the back door the 2026-08-05 rule missed.** That change put the
capture inside `_notify_card` "so every future card is recorded by construction"
— and it did, for all nineteen card sites. But `_notify` posts plain text with no
`record_event`, and **thirteen engine call sites** still use it: the scout's
proposals, the belief desk's "run #N is ready", "no leads in the queue",
"news-monitor returned no usable selection", source-scout results,
meta-synthesis, a failed carousel. `_notify` now records before it posts, same
order and same reasoning — one place rather than thirteen, so nothing the engine
says can live only in Telegram. Probed both directions: a Telegram outage leaves
the row, a DB failure still sends the notice.

The scout's own notice fired `if added`, so a run that proposed nothing, parsed
nothing, or had everything rejected said **nothing at all**. It now reports every
outcome with a tally, and distinguishes format drift from a quiet week. A sweep
that *raises* also reports now (`_sweep_failed`), instead of dying into a Railway
log line nobody reads.

**The cap was a cap only at tick granularity.** The governor is checked once per
tick and `run_daily_cycle()` then runs to completion unwatched, so it could
refuse to start a tick but could not bound a day: $1.32, $1.28, $1.16 against a
$1.00 cap. The obvious fix — check between stages and abort — is the exact
failure `shared/budget.py` exists to prevent ("a story half-verified, a draft
never written"), so **the check moved earlier instead of getting sharper.**

Measured over **63 real cycles in 21 days**: p50 $0.211, p80 $0.337, p95 $0.993,
max $1.090. A **reserve** (kv `daily_budget_reserve_usd`, default **$0.35** = the
p80) parks model work when `spent + reserve >= cap`. At a $1.00 cap the engine
now parks at $0.65, so roughly four days in five land under the cap instead of
over it. **This is a throughput cut and it does not make the cap inviolable** — a
p95-tail cycle breaks a $1.00 cap whichever end you check. Reserve 0 restores the
old behaviour exactly. Suite: `shared.tests.run_budget_cases` (new).

**Two things the build turned up that nobody was looking for.**

1. *A NaN reserve would have uncapped the engine.* Caught by the new suite's
   first run: `float("nan")` parses, `nan <= 0` is False, and thereafter
   `spent + nan >= cap` is False for ever. Same class `cadence_days` already
   guarded and the reserve had not inherited. `math.isfinite` now gates it.
2. *The overview banner was reading a 48% undercount, and the reserve made it
   load-bearing.* The 2026-08-05 cache-accounting fix converted the governor, the
   steward and the cost report but **missed `get_daily_costs`**, which selects
   only `input_tokens`/`output_tokens`. The command centre priced today at
   **$0.2967**; the governor priced the same day from the same table at
   **$0.5707**. Both callers passed three args to a five-arg `cost_usd`, so
   nothing raised. Fixed in the overview banner and in the Costs view's 30-day
   trend — which had been drawing a lower line than the by_model table directly
   above it. The banner was also keyed to **local** date against the governor's
   UTC day. Both endpoints now report $0.5707.

`over` had three independent implementations; `util.budget_state` is now the only
one, taking pre-fetched cap/reserve so the overview keeps its no-extra-round-trip
property.

---

## The desks alternate now — the belief desk had never once run (2026-08-08)

The cadence was not broken and the code was not wrong. **The belief desk was
being asked a question whose answer was always no.** `BUDGET_HEADROOM = 0.55`
stood the desk down once 55% of the daily cap was spent, and `run.py` ran the
belief block *after* the RSS cycle so that check would read a spend figure
including the day's news work. Each half is defensible. Together they are
unsatisfiable: the news cycle fires at ~00:02 UTC and clears 55¢ of the $1.00 cap
in its first pass, so the desk was asked only once the answer was already no —
and a day's spend never goes back down.

Production kv said so plainly, and nobody had read it:

```
last_belief_cycle_result = "skipped: $0.57 of the $1.00 cap already spent
                            — the news desk has the prior claim on it"
last_belief_run_at       = 2026-08-01T05:22:56Z
```

Daily spend recomputed from `token_usage`: **$1.07, $1.28, $0.56, $1.02, $1.14,
$1.32, $0.86, $0.57** across 08-01 to 08-08. The desk needed a day under $0.55
and there wasn't one — including 08-03, which missed by a cent. Belief #3
(Koh-i-Noor) had sat `approved` with `run_id: null` since the 08-05 event card
*"Belief cadence armed for its first unattended run."* It was armed. It never had
a day to fire in. **An unsatisfiable priority test is not a priority rule, it is
an off switch.**

**The desks alternate** (`docs/alternating-desks.md`, owner's call). On its turn
the belief desk goes **first** — the block moved above the RSS cycle — so it
meets a fresh $0.00 cap and spends its ~$0.15 before the news desk starts. News
publishes every day and runs second with ~$0.85 of the cap. On a news day
`cycle_due` is false and the moved block is a no-op, so news behaviour is
unchanged. Cadence default 3 → **2**.

That is turn-taking, not calendar parity: a turn missed to a restart or a
genuinely spent day leaves the desk due, so it takes the next available day
rather than waiting out another full cycle.

**`BUDGET_HEADROOM` stays at 0.55 and keeps a narrower job** — a `force_belief_run`
tapped at 3pm on a spent day, and a turn day whose engine only came up at 20:00.
A stand-down does not stamp `LAST_RUN_KEY`, so the turn carries to tomorrow; the
suite asserts exactly that, because stamping there would consume a turn without
producing a piece and reintroduce the same silence more slowly.

**The turn had to stop being counted in seconds.** `cycle_due` compared elapsed
time against `days * 86400`, which on a 2-day cadence loses every other turn to a
rounding margin: a run stamped Mon 00:03:10 is 47h58m50s old at the Wed 00:02
tick — not due — so the RSS cycle starts, spends past the headroom, and the desk
stands down **on its own turn day**, wearing a budget excuse indistinguishable
from the bug being fixed. Whole-day cadences now compare **UTC dates**, putting
the turn boundary on the same midnight the news cycle keys off. Sub-day cadences
(`MIN_CADENCE_DAYS = 0.5`) have no whole-date expression and keep the elapsed
path. Verified against the old arithmetic: `False` then, `True` now.

The command centre shows whose turn it is (`turn_today` / `next_turn` from
`next_turn_utc`), because "the desk is quiet" has two meanings and `last_run_at`
alone cannot tell them apart. Suite: `engine.desks.ek.tests.run_cadence_cases`,
now with the turn-boundary and stand-down cases; caption (15/15) and carousel
cases unregressed.

**Still open here:** the desk has still never completed an unattended run — this
change gives it the first day it can. Separately, `ek:belief-scout` has run
exactly once (3 calls, 2026-08-05) and added **zero** rows; all four
`belief_queue` entries are `source='owner'`. Whatever it emitted did not survive
`validate_candidate`, and **no event card was written for the run** — a silent
scout breaks the nothing-lives-only-in-Telegram rule.

---

## The belief desks are finished (2026-08-04)

All six phases of `docs/everyone-knows-desk.md` §9 are done. **Everyone Knows**
(`desk='ek'`) and **Turns Out** (`desk='gk'`) now have an intake, a cadence, a
reader page, reels, and a green gate suite. Two reels exist — #26 (run #140,
Turns Out) and #27 (run #145, Everyone Knows shape B) — and run #145 is the
desk's first contested-frame piece, produced end to end by the cadence path from
a belief typed into the command centre.

**The spine was on the reader's page.** The writers emit headline, dek, article,
sources and SPOKEN SPINE as one block, and runs #136-#140 stored it whole in
`draft_text`. Published as-is, `/a/<slug>` would have taken its title from the
`## ARTICLE` heading and printed the reel's narration under the sources.
`engine/desks/ek/draft.py` splits it at write time — the page into `draft_text`
in the same house markdown a news piece uses (so publish, teaser, carousel and
the CC all work untouched), the spine and view label onto `belief_pieces`.
`backfill_drafts.py` migrated the existing rows; it is idempotent.

**A belief reel is not scripted.** `publishing/belief_reel.py` builds it from the
stored spine with no `video-script` call, because re-scripting would put a
generation step downstream of the trust gate. The words are copied. Captions,
illustration scenes and hashtags are still chosen — and a caption is read, so
`caption_ok` accepts a model's proposal only when it is a contiguous span of that
spoken line, ≤8 words, keeping the negation of the clause it quotes. It cannot
add a word the verifier never saw, and it cannot make "no man-made object is
visible" say the opposite by dropping the "no". Anything else falls back to a
deterministic clause cut. `spoken_matches_spine` then re-checks the whole
narration after parsing, so a hand-edited script that drifted is refused.
Cases: `python -m engine.desks.ek.tests.run_caption_cases`.

**Shape B wears its label where a muted viewer sees it** — an outlined
`A VIEW FROM THE RECORD` pill on every story frame of both reel looks, and a
`> [!VIEW]` callout on the page rendered as a bordered aside, not a blockquote.

**Intake + cadence.** `themes.yaml` (8 standing curiosities), an `ek:belief-scout`
proposing weekly into the new `belief_queue`, and a **Beliefs** view in the
command centre. Owner-supplied beliefs land approved; the scout's wait for a nod.
One piece every 3 days by default, and the desk stands down when the news desk
has already spent 55% of the daily cap. `belief_auto_pursue` (default off) lets
it promote its own scout's proposal when the queue is empty.

**The gate suite is 9/9, and getting there was three bugs deep.**
`gandhi-surname` was dropping — but as a *strawman*, not on consequence, on the
reasoning that "no well-informed person holds that" while its own CURRENCY line
called the belief widespread. Fixed, it dropped again with the words "Route to
GK lane." in its REASON. The prompt already forbade that in an example, a rule,
and a paragraph headed "`DROP` is not available to you here" — so **the routing
stopped being the model's to choose.** `premise-check` now answers the four
judgments as separate fields and `engine/desks/ek/gate.py` computes the verdict,
logging any disagreement. That immediately exposed a third bug wearing a passing
verdict: two cases were being dropped as strawmen rather than for breadth,
because `REAL_BELIEF` was answered against the raw input instead of the
moderated restatement. `BELIEF` now comes first in the output, and breadth is
asked of both shapes — as a shape-B-only test, the gate escaped it by calling a
seventy-year causal thesis "factual".

Editorial ruling on `gandhi-surname`: either lane is acceptable (`expect` is a
list now), `DROP` is not. Binning a true, believed, checkable claim is the one
thing the consequence floor must never do.

**Two of the four are closed (2026-08-05).** A belief piece can now become a
carousel, and one refused illustration no longer costs a reel its look — see
"Closing the belief desks' open four" below.

**Still open:** the cadence has never fired unattended on Railway; the scout has
not run against the live web. Both are code-hardened and tested but **unproven in
production** — nothing has been deployed.

*(2026-08-08: both diagnosed. The cadence fired every tick and stood down on
budget every time — see "The desks alternate now" above. The scout did run, once,
and produced nothing.)*

---

## Nothing lives only in Telegram, and the CAG story was never rejected (2026-08-05)

**Owner's rule:** the dashboard has everything; no story may be visible only in
Telegram. Nineteen `_notify_card` sites — dropped leads, halted runs, gate
decisions, source-scout results, steward sweeps, meta-synthesis — wrote to no
table at all. The capture now sits **in `_notify_card` itself**, not at the call
sites, so every future card is recorded by construction.

**The write happens before the Telegram post.** That was the half of the bug that
was easy to miss: an outage or a bad token did not delay a notice, it destroyed
the only copy. A test makes `_tg_post` raise and asserts the event survives.
Full report bodies live in `engine_events.report` and open **inline** in the CC's
new Events panel — Telegraph is on a domain the owner's ISP blocks, so an
off-site link is not a delivery mechanism here.

**The 2026-08-04 CAG topic was never an editorial decline.** `topic-intake`
returned no valid marker, retried 20s later, failed again, and raised. The
`token_usage` signature shows it exactly: two `topic-intake` calls and no
`newsworthiness-gate` call after them. Re-running the same topic returns
**PROCEED** — "in scope: yes", "worth it: yes, impact high" — and the brief names
₹54,282.32 crore in pending utilisation certificates across 15 ministries.

It was invisible for a second reason: `_halt_run` titles its card
`Run #{run_id} halted`, and a topic dying inside intake has no run, so the owner
got **"Run #None halted at topic-intake"** — a card naming neither the topic nor
anything he could recognise as his own submission. `_halt_run` now takes
`subject`. The topic was re-queued and is **run #150**, `outcome='investigating'`.

**Proven in production, not just in tests:** `pending_topics` #48 carries
`outcome`, `reason`, `run_id` and `decided_at`; #47 sits beside it with all four
null — the honest "unknown" for pre-fix rows.

**Sonnet 5 vs 4.6 — the tokenizer eats the intro discount.** Measured with
`count_tokens` on the same file: **2,428 tokens on Sonnet 4.6 vs 3,265 on
Sonnet 5, a 1.345x inflation.** Net cost for identical work:

| | relative | |
|---|---|---|
| Sonnet 4.6 ($3/$15) | 1.000 | baseline |
| Sonnet 5 intro ($2/$10, to 2026-08-31) | 0.896 | 10.4% cheaper |
| Sonnet 5 standard ($3/$15, from 09-01) | 1.345 | **34.5% dearer** |

The steward's "33% cheaper on input" compares per-token rates and ignores the
tokenizer. The real intro saving is ~10%, and on 2026-09-01 the same work costs
~34% **more**. **There is no cheap window worth racing to**, so the standing
"revisit 2026-09-01" date is fine after all. Switch only if quality justifies a
permanent ~34% rise.

**Open, with a caveat worth watching:** across 13 recorded calls the new counters
show ~26k cache **writes and zero reads**. That is expected when each skill is
called once per cycle (every call is a first call, and a write bills at 1.25x),
and the payoff only lands when the same skill repeats inside the 5-minute window
— the article-writer / editorial-reviewer revision loop. If reads stay at zero
over a larger sample, the caching is costing 1.25x for nothing and the
breakpoints need rethinking rather than keeping.

---

## The cached span was billed at zero (2026-08-05)

Chasing where `news-investigator`'s ~136k input tokens per call were going turned
up something bigger than a routing question. **`response.usage.input_tokens` is
the uncached remainder, not the prompt size** — the real prompt is
`input + cache_creation + cache_read`. `skill_runner` recorded only the first and
discarded the other two, which meant the `cache_control` markers it already sets
were invisible in the accounting, and a cache **write** — which bills at 1.25x
the input rate — contributed nothing to any total. `daily_spend_usd`, the number
the budget governor reads to enforce the daily cap, was reading that same low
figure.

`token_usage` gains `cache_write_tokens` / `cache_read_tokens`; `cost_usd` takes
them as optional trailing args at 1.25x write / 0.10x read of the tier's input
rate, so all nine existing three-arg call sites keep their old meaning. The
governor, the steward's view, the cost report and the command centre's panel all
count them now — those four must not disagree about what a day cost.

**Historical rows cannot be backfilled.** The provider reported those counters
and we discarded them, so all-time spend before 2026-08-05 (~$70 / ₹5,900 over
1,866 calls) is a **floor**, not the true figure.

What the same dig established, and what is still open:

- **The 2026-07-26 Haiku routing worked.** `news-monitor` 192 Sonnet calls end
  2026-07-21 and 26 Haiku calls begin 2026-07-28; `topic-intake` 53 → 9;
  `newsworthiness-gate` 157 → 33. The large Sonnet numbers in the all-time table
  are pre-fix history, not a live leak — there is nothing left to move there.
- **`news-investigator` is the real remaining lever** — 39 calls at ~136k input
  tokens each, the single largest line, and correctly untouched by the Haiku
  routing because it is journalism, not triage.
- The engine runs **5.7:1 input to output** (16.7M / 2.9M), so prompt size and
  cache hit rate dominate, not output length.
- **Sonnet 5's intro pricing ($2/$10 vs $3/$15) expires 2026-08-31**, and the
  standing cost-control decision is to revisit Sonnet 4.6 on **2026-09-01** —
  after the window shuts. Note also that Sonnet 5's tokenizer produces ~30% more
  tokens for the same text, so per-token parity is not cost parity. If the
  benchmark is wanted at intro pricing it has to happen before 08-31.

---

## Closing the belief desks' open four (2026-08-05)

Three commits, on `main`, **not pushed** — pushing auto-deploys, and the deploy
is the owner's call.

**A belief piece can become a carousel** (`c33a69a`). One path, both desks. A
belief piece differs in three ways and no more — a composer that opens on the
belief instead of a lede, a fixed series stamp, and the shape-B view marker on
every slide — all decided in `engine/desks/ek/carousel.py`. The composer,
renderer, fileserver and post path never learn there are two desks, because
`draft.to_markdown` already writes a belief page in the same house markdown a
news piece uses. That was the whole payoff of splitting the spine off the page.

`view_label` is persisted on `carousel_runs` rather than baked into the first
render only: the fileserver **re-renders slides from the DB** on demand (and on
`?fresh=1` after a headline edit), so a label living only in the render would
quietly vanish from the image Meta actually fetches. The suite tests the
re-render path for exactly this. `ek:carousel-composer` rides the free NVIDIA
tier for the same reason the news one does — it sequences an already-verified
page and may not add a word it does not contain.

**One refused illustration no longer costs the whole look** (`2545cc9`). A
single FLUX refusal used to drop the entire reel to text slides. One beat now
falls back to a **house ground** — an ink-dark inked field, in palette (mean
luminance ~30; stddev ~10, so it has tooth rather than reading as a failed
render), deterministic per beat so a rebuild is stable, drawn through
`draw_illustrated_frame` like any other illustration. **More than one refusal
still falls back to text slides whole:** past the exception an inked field stops
reading as a beat that chose texture, and the honest product is the consistent
text reel. The story text is never touched. 23/23 in
`publishing/tests/run_illustration_cases.py`.

**The cadence and scout are hardened but not proven** (`00d4253`).
`validate_candidate` now enforces the two conditions the skill calls mandatory
and rejects what the model actually emits when it drifts: a truncated response,
a template echo, too short, a paragraph instead of a candidate, no record, no
currency. A cut-off block is rejected while its complete sibling passes, so one
bad half does not discard a good one. **The live-web scout run and the
unattended Railway cadence observation did not happen** — both remain open.

Suites: `publishing.tests.run_illustration_cases` (23/23),
`engine.desks.ek.tests.run_carousel_cases`, `.run_cadence_cases`, and the
pre-existing `.run_caption_cases` (15/15, unregressed).

---

## Reel pacing + command-centre browse (2026-07-30)

Six changes, all on `main`. Four of them are bug fixes to things that looked finished.

**The reel's visual pacing was broken twice over.**

1. **The Ken-Burns push stalled.** `zoompan`'s increment was a constant `0.0006`/frame
   against a constant `1.08` ceiling, so it exhausted itself after 133 frames = **4.44s
   at 30fps**. Speech beats run 6-12s, so every beat drifted for 4.4s and then held a
   pixel-identical frame. Measured: 2.2 mean pixel change per half-second while moving,
   **0.001** after the ceiling — stopped, not slowed. Reel #14 was frozen for 51% of its
   runtime, #13 for 45%, #17 for 55%. Worse, it read as a glitch rather than a look,
   because the stall keys off an absolute 4.4s: #13's 2.9s and 4.1s beats never froze
   while its 12.5s beat froze for 8s. `_zoom_expr()` now derives the increment from the
   beat's own frame count. `ZOOM_MAX` (1.08) is the one knob.
2. **One picture per ~9 seconds.** Reel #14 is 110 words — *inside* the skill's 110-135
   spec, so the model obeyed; the spec's own arithmetic is the problem. 110-135 words at
   the measured 147wpm is 45-55s over the specified 5-6 frames = 8-11s per still.
   `build_reel` now takes **`shots_per_beat`** and subdivides a long beat's *video* into
   2-3 sub-shots, each with its own illustration (`TARGET_SHOT_SECS = 4.0`,
   `MAX_SHOTS_PER_BEAT = 3`). The audio is built and concatenated separately, so **the
   narration is byte-identical and nothing is re-verified.** That was the deciding
   factor: compression is where reel #12 upgraded a tabled Bill to "won", so buying
   pacing by shortening spoken lines would trade verification quality for retention.
   - `_split_duration` makes sub-shots sum to EXACTLY the beat duration — per-part
     rounding drifts against a continuous VO and accumulates over 6 beats.
   - `generate_beat_images` had ONE fixed seed for every scene. Harmless when each beat
     had a distinct prompt, fatal once sub-shots reuse the beat's scene: a shared seed
     renders them identically and the cut becomes a stutter. Seed is now per-scene.
   - Text-slide reels are **never** split (nothing varies per sub-shot → the cut would
     restart the zoom on the same frame); the illustration fallback resets the plan.
   - The silent sign-off card is one shot, never cut. Progress dots still count beats.

**The hook was specified but never enforced.** `_gen_script_nvidia` returned its output
regardless of whether the retry worked, and the only downstream check was `if not beats`
— which passes, because BEAT 1..n *are* beats. A hookless script therefore rendered a
reel opening mid-story, silently, after a ~15-minute render. Separately, `parse_script`'s
`^LABEL:\s*(.+)$` used `\s`, which matches newlines: a bare `HOOK:` **stole BEAT 1's
sentence** (and spoke BEAT 1 twice), a bare `CLOSE:` stole the HASHTAGS line, a bare
`BEAT n:` swallowed its own caption. Horizontal whitespace only now. `parse_script`
returns `hook`, and ONE predicate (`_has_hook`) guards the nvidia generator,
`run_structured_skill`'s marker, and a post-parse check, so no mode can drift weaker.

**NVIDIA calls had no transient retry** — a single 500 killed a whole reel build. Now
`shared/nvidia.py::call_with_retry`, used by all three call sites (video-script,
FLUX illustrations, `skill_runner._run_nvidia`). Retries 5xx/timeouts, **fails fast on
4xx**, never touches the quota breaker (NVIDIA has its own key). Most important on the
illustration path: ~12 FLUX calls per reel now, and all-or-nothing fallback meant one
blip cost the whole illustrated look.

**Command centre browse.** Stories/Carousels/Reels share ONE control — see
`docs/command-center-v2.md`. Includes a real filter fix: `pipeline_runs.status` carries
legacy duplicate spellings (`hold`+`held`, `kill`+`killed`), so filtering the literal hid
rows — "killed" showed 16 of the actual 25.

**Reel remake takes suggestions.** A textarea on Remake, stored on `reels.notes`,
prefilled into the next remake, injected into the script prompt inside a block that
restates that the hard rules outrank every note — the reel is post-gate, so nothing
re-verifies it after the Post tap. See `docs/reel-button.md`.

**Also:** the Streamlit dashboard is retired (killed + autostart moved to
`~/.config/autostart-retired/`; code left in place, not back-ported). The
**Vizhinjam/Adani dig is dropped** — watchlist theme removed, `/dig` with no argument now
lets the scout pick the ripest theme, and story-scout's worked examples were *replaced*
(not deleted) with live-watchlist equivalents so the skill keeps teaching
condition-vs-event, question-vs-conclusion and what a Kerala anchor is.

## Illustrated reels (productionized 2026-07-26 — plan 02)

`make_narrated_reel()` now produces the **ink-dark illustrated** reel (the reel #9
look) by default, end to end from the CC's "Make reel" button. This was a
scratchpad prototype that built one published reel by monkeypatching
`reel._render_frame`; it is now real code.

- `publishing/illustrate.py` — one conceptual illustration per beat via
  **FLUX.1-dev on the free NVIDIA key**. Serial (14 GB box), dark-ground house
  style, and it defends against the two known failure shapes: the NIM safety
  filter returning a black frame with `finishReason=CONTENT_FILTERED` (checked)
  and sub-50KB blanks (rejected). Journalism vocabulary that trips the filter
  ('somber', 'grave', 'victim'…) is softened **in the image prompt only** — never
  in the story.
- `publishing/reel_illustrated.py` — the frame builders and the sign-off card,
  ported verbatim in geometry from the prototype.
- **`reel.build_reel` takes a `render_frame`**, and `_synth` treats an empty beat
  as a deliberate **silent hold** — that's how the sign-off card gets its ~2.8s
  with no speech over it. No monkeypatching anywhere.
- The **video-script skill now emits an `IMAGE:` line per beat** (`HOOK_IMAGE`,
  `BEAT n IMAGE`, `CLOSE_IMAGE`) — a conceptual scene, with the non-photoreal
  rule stated as a brand rule. `parse_script` returns `images` aligned with
  `beats`; older scripts without them fall back to a scene derived from the
  caption.
- **All-or-nothing fallback:** if any beat's illustration fails, the whole reel
  renders as text slides. A reel mixing both looks like a bug, not a style.
  Stored `kind` is `illustrated` or `narrated`, shown on the CC reel card.

## Cost control (added 2026-07-26 — plan 01)

The engine now runs to a budget instead of running until the balance dies.

- **One cost model: `shared/costs.py`.** The USD-per-MTok table used to be
  triplicated (orchestrator report, Streamlit, command center) and had already
  diverged — gemini-pro output was priced at $5 in one place and $10 in the
  others, and neither the report nor the dashboard knew NVIDIA Gemma is free,
  so free presentation calls were billed at Claude rates. All three import from
  here now. `cost_usd()` resolves a raw model string to a tier; `RATES` is the
  introspectable table.
- **Triage runs on Haiku 4.5.** `_HAIKU_SKILLS` in `engine/agents/skill_runner.py`
  = `news-monitor`, `topic-intake`, `chief-of-staff`, `newsworthiness-gate` —
  measured 2026-07-26 as ~$20 of the ~$34/mo burn, against ~$5.4 for the writing
  core. They sift against a strict output contract; they don't write prose and
  don't touch the trust gate. **The trust-critical chain stays on `CLAUDE_MODEL`**
  (article-writer, editorial-reviewer, pattern-synthesizer, meta-synthesizer,
  source-ingestor) and research stays on Gemini. `record_usage` logs the model
  actually called, so cost accounting stays truthful.
  *Watch after the first cycles with credit:* news-monitor has a selection
  contract; if `_resolve_selected_lead` starts logging "throughline unmatched",
  revert just news-monitor to `CLAUDE_MODEL` and leave the other three.
- **Budget governor: `shared/budget.py` + the block in `run.py`.** Daily spend
  cap (default **$0.75**, kv `daily_budget_usd`, 0 disables). Sits *below* the
  quota breaker and *above* every model stage — so at the cap, model work parks
  but publishing, approvals and cleanup keep working. Self-expiring: spend is
  only ever counted for the current UTC day, so midnight releases it. One
  Telegram alert the first time it trips each day.
- **Controls:** command center System view (cap + today's spend + setter),
  Overview banner in gold when parked (it's healthy behavior, not an outage),
  `POST /api/system/budget`, and `/setbudget <usd>` in the bot.
- **Model knobs are env-overridable** (`THELIVU_CLAUDE_MODEL`,
  `THELIVU_HAIKU_MODEL`, `THELIVU_GEMINI_MODEL`) so a routing change is a
  Railway variable, not a code push.
- **Owner decision 2026-07-26:** stay on **Sonnet 4.6** for the writing core.
  Sonnet 5's intro pricing ($2/$10 to 2026-08-31) is offset by a tokenizer that
  uses ~30% more tokens, and it goes ~30% dearer after. Revisit 2026-09-01.

## Tech steward (added 2026-07-26 — plan 05)

The technical counterpart to the chief-of-staff: a **weekly advisory sweep** that
keeps the model stack apt instead of letting it drift until something 404s or a
price moves under us. `run_tech_steward()` builds a telemetry snapshot (30-day
spend by skill × model, the full routing table, the rate table we assume, budget
and breaker state), then searches the live Anthropic / Google / NVIDIA catalogues
and emits a ranked `RECOMMENDATIONS` block — each with `from` → `to`, a risk
rating and an estimated monthly saving.

- **Advisory only.** It never switches a model, never spends. Applying is one
  env var (`railway variable set THELIVU_CLAUDE_MODEL=… --service thelivu-agent`),
  so reverting is too. Never recommends moving journalism off Claude/Gemini.
- Routed to **Gemini + Google Search** — it's a search-heavy scan of pricing
  pages, and it's ops, not journalism, so the charter has no stake in it.
- Weekly in the tick (stamped before running, per the retry-storm rule) plus a
  `force_tech_steward` signal; CC System view shows the last sweep, a Run-now
  button, the recommendation cards and the full brief.

## Command Center v2 (added 2026-07-26 — the operations base)

**The Streamlit dashboard has a successor: `command_center/`** — a proper web app
(Starlette + uvicorn, hand-rolled SPA, zero new deps) that is now the intended main
operations surface. Spec: `docs/command-center-v2.md` (read it before extending).

- **Run:** `command_center/run.sh` (autostarts via
  `~/.config/autostart/thelivu-command-center.desktop`) → **http://localhost:8600**,
  phone via Tailscale `100.70.158.55:8600`. Password gate (`DASHBOARD_PASSWORD`).
- **11 views:** Overview · Gate · Stories · Carousels · Reels · Digs · Chief of
  staff · Sources · Ingest · System · Costs. Everything the Streamlit app did,
  plus: inline draft editing (human edit), AI suggestions (quota-aware,
  editorial-reviewer, pre-approval only), slide-headline editing (re-renders the
  hosted image via the fileserver's new `?fresh=1`), reel previews streamed
  locally, make/post reels and carousels as background jobs with live progress,
  voice-server start/stop, breaker status + clear, bio-links manager, signal
  triggers for every scheduled job.
- **Gate unchanged:** approve/post go through the ONE shared
  `publishing.publish` paths behind explicit confirm modals. No bypass.
- **Perf discipline (hard-won, same day):** round trips to Railway dominate —
  the CC pools connections (autocommit, dials outside the lock — see
  `command_center/db.py` docstring), batches kv reads, and fans out independent
  queries with `db.parallel`. Endpoints run 0.2–0.7s warm; a naive port ran 40s.
- The Streamlit `dashboard.py` still autostarts on :8501 — retire it once the CC
  has proven itself for a few days.

## Where things stand (updated 2026-07-20 — the "command center" era)

**Live and running in production.** Deployed on Railway, publishing daily, with a
full command-center control surface. The pre-launch snapshot below this line is
historical — this is current.

- **Deployed** on Railway project `brave-determination`: `thelivu-agent` (orchestrator
  2-min tick + public web server), `thelivu` (Telegram bot / human gate), `Postgres`.
  Auto-deploys from GitHub `main` (`anilvignesh/thelivu`). See `docs/HANDOFF.md` for
  topology, CLI, and gotchas — **read it before touching prod.**
- **~10 articles published** to the Telegram channel `@thelivu_reports`, self-hosted
  at `/a/<slug>`; **5 Instagram carousels posted** (account `thelivu.reports`).
  Numbers decay — query the DB, don't trust these.
- **20 skills** in `engine/skills/` (was 12): added `chief-of-staff`, `video-script`
  (video-script is scaffolded, NOT wired — see `docs/video-reels-research.md`), and
  the dig/tracker/ingestor family.
- **The command center** (`dashboard.py`) — a 10-tab Streamlit control panel run
  locally against the prod DB (over Tailscale for phone access). Overview · Ingest ·
  Drafts · Pipeline · Carousels · Digs · Follow-ups · Sources · Tasks · Costs.
- **Owner autonomy grant (2026-07-15):** the assistant acts autonomously on
  everything — features, story work, backend, digs — and the **only** action gated on
  the owner is the **final publish/post**. Enforced in code (no bypass flag).

### Capabilities added this era (all deployed, all end at the human gate)
1. **Persistent digs** — a thread investigated over multiple days. Tables `digs` +
   `dig_updates`; `run_dig_advance()` / `promote_dig()` in the orchestrator; daily
   auto-advance of due digs; kv signals `advance_dig_id` / `promote_dig_id`. The E20
   dig (#2) went scoping→verifying→ready-to-write autonomously.
2. **Link ingestion** — paste an article/YouTube URL; `ingestion/fetch.py` fetches
   readable text (requests+lxml, ISP-retry), `queue_ingest()` → `pending_topics`
   (source=`ingest`), and `_run_topic_intake` enriches the URL before triaging.
3. **Chief of staff** — `run_chief_of_staff()` autonomously sweeps the neglected
   backlog (held / stale-at-gate / dropped digs), checks the web for "what moved,"
   and **executes** recheck/requeue/kill/open-dig (capped 8/sweep) + opens new dig
   threads. Daily + `run_chief_of_staff` kv signal. Parser tolerates truncated blocks.
4. **Held-run loop closed** — held / needs_attention runs are readable + actionable
   from the dashboard AND Telegram: `recheck_run(note=…)` takes **owner editorial
   direction** (what to search / how to frame; **links are fetched + verified**) via
   kv `recheck_note_<id>`. `/recheck <id> <direction>` on the bot. Steers framing;
   never overrides the trust gate.
5. **Cost controls (quality-neutral)** — `_run_claude` caps the web-search tool loop
   at 6 rounds then forces a final answer (a runaway loop was ~95% of spend), plus
   prompt-caches the growing context. Gemini content-blocks now fall back to
   Claude+web-search instead of dying empty (was the "Gemini returns empty" bug).
6. **Robust Instagram + carousels** — `publishing/publish.py` holds the ONE shared
   `publish_run()` (article) and `post_carousel_run()` (carousel) both the bot and
   dashboard call (no drift). Slides render **on demand from the DB** in the
   fileserver (survive redeploys/cleanup — `dark`/`stamp` persisted on
   `carousel_runs`). IG calls retry transient errors + empty responses.
7. **Reposition** — global scope, Kerala emphasis, NOT Kerala-first (see Decisions).
8. **Reach** — story-specific + evergreen hashtags on carousels; slide count sized
   for engagement + full explanation (8–10, ceiling 10).
9. **Attended mode + the quota breaker (2026-07-22)** — the answer to "the APIs ran
   out." No cross-engine fallback; work parks, Anil runs the cycle by hand at the
   terminal. See `docs/attended-mode.md`. Details below.

### Attended mode — added 2026-07-22

On 2026-07-21 **both** providers ran dry within hours of each other (Anthropic
balance exhausted; Gemini AI Studio prepay credits depleted). The tick loop then
spent **22 hours** crashing on a 429 every 2 minutes, producing nothing, while RSS
kept queueing leads into a dead pipeline (1,504 of them by the 22nd).

Three things came out of it:

- **The Claude→Gemini auto-fallback (`9b3202f`) is REVERTED.** It contradicted an
  invariant the code already held (`_pause_run`: *"never run on a substitute
  engine"*). Silently moving the **trust gate** onto a cheaper model is exactly the
  quality drift the charter exists to prevent — cheaper output on the gates is not a
  neutral cost saving. Owner's call, and the right one.
- **A quota circuit breaker** (`shared/quota.py`). A *hard* failure (out of credit,
  quota exhausted, bad key) opens it for 60 minutes and the tick skips every model
  stage; a *transient* failure (overload/500/timeout) does not — those still pause +
  requeue per-run. It auto-expires, so a top-up or a midnight reset recovers with no
  manual switch. Work that needs no model — **approve, publish, post a carousel**,
  cleanup, the bio/article pages — deliberately sits ABOVE the breaker and keeps
  running. Losing the API must never take the publishing surface down.
- **Attended mode** (`engine/attend.py`, `./attend`). Runs the *real* orchestrator
  with only the model call replaced: each skill writes its prompt to
  `.attend/NNN-<skill>.request.md` and blocks until the assistant in Anil's
  interactive Claude Code session writes the `.response.md`. Zero pipeline
  duplication — trust gate, anti-monotony, parsing and the human gate are untouched.

  **⚠️ It is a human-operated tool and must never be automated** — not from cron,
  not from Railway, not via `claude -p`. A subscription driven by a human doing
  their own work is legitimate; a subscription wired up as an unattended API
  replacement is not. The blocking wait *is* the boundary. See
  `docs/attended-mode.md`.

Also fixed: `_last_rss_run` was only stamped on **success**, so a failing cycle
stayed permanently "due" and retried every 2 minutes. That was the actual engine of
the 22-hour loop. It now stamps on failure too, with a 30-minute backoff.

### Reels wired into the command center — added 2026-07-25
The "reels built but not wired in" gap is closed. A **Reels row on every carousel
card** builds + posts a narrated reel (Anil's cloned voice) of the same story:
🎬 Make reel (create + preview) → 📤 Post reel (the gated tap). `save_reel` finally
has a caller — `publishing/make_reel.py` — shared by the dashboard and `./attend reel`.
**Reels are attended-only for now** (`config.REEL_MODE='attended'`): the script step
never touches the API — the dashboard button hands you `./attend reel <run_id>`, which
renders locally (voice + ffmpeg) and stores it `ready` for preview + post. The **API
route is kept but inactive** (flip `THELIVU_REEL_MODE=api`), owner's call. First one
built this way: reel #3 (Varkala cliff, run 111). Full detail: `docs/reel-button.md`.
**Next visual upgrade under discussion:** replace pure text-slides with AI-generated
images / editorial cartoons per beat (see `docs/video-reels-research.md`).

### Parked (not built — pick up post-20-posts)
- Marketing/reach push: repurpose one verified story to X/WhatsApp; a political-cartoon
  prototype (concept via LLM → image model → gate).
- **Kiln** (`~/kiln`, separate repo) — a generator that turns this framework into
  clone-and-deploy Instagram content engines for any niche. Spec written; for Anil's
  wife + her brother. See `~/kiln/docs/kiln-spec.md`.

---

## Historical: pre-launch snapshot (2026-07, superseded above)

- **Engine: fully built.** Charter, 12 skills, source registry, investigative
  watchlist, two scripts (ingest, publish), all operating docs — in `engine/`.
- **Three article drafts**, all review-stage; **pushed to a private GitHub repo.**
- **Phase then: pre-launch / validation.** (Now live — see above.)

---

## Decisions locked (don't silently reverse — see CONTEXT-AND-HISTORY for why)

Name **Thelivu**. Stance: **transparent perspective** (argue a view, openly; verify
facts, judge framing). **English.** **One** human-reviewed piece a day. **Global in
scope, with a working emphasis on uncovering Kerala** (where much of the audience is)
— **never Kerala-limited**; national and international stories are fully in scope.
Emphasis is a sourcing priority, not a public frame — we do **not** brand as
"Kerala-first." *(Repositioned 2026-07-16 from the original "Kerala-first,
India-second, international as a lens; distance raises the bar" — owner's call:
open to stories from around the world, Kerala emphasised for the audience, not a
limit.)* Sources
are leads; the open web verifies. **The human gate is absolute** (only the final
publish/post is gated; everything else is autonomous per the 2026-07-15 grant).
*(Superseded: the original "run attended on an M1 Mac, no local LLMs, automation
deferred" is history — the engine now runs unattended on Railway with the human gate
as the one control. The dev machine is Anil's Pop!_OS laptop.)*

---

## The spine — the thing that must not drift

This is a **verification engine with a human gate**, not a content mill or a partisan
line. Its value was proven repeatedly in the build session — it caught compelling-but-
false claims again and again:

- a chartered flight falsely attributed to Adani (allegation, not fact);
- a health minister "endorsing privatisation" who had actually said the opposite;
- private-equity firms "funding the Congress campaign" — unsupported;
- loan write-offs "for the Modis/Ambanis/Adanis" — write-off ≠ waiver, identities
  legally shielded, named-tycoon framing unverifiable;
- "Adani & Ambani are the biggest RSS/BJP backers" — corrected: Reliance *was* a top
  disclosed BJP donor (~₹545cr), Adani was not, RSS funding is opaque;
- a privatisation "plan" the evidence supported only as a "direction."

Each was downgraded, attributed, or dropped. **Preserve this reflex above all else.**

---

## Recent build additions (the latest state)

- Trust-score gate (categorical KILL / HOLD / READY) in the verifier.
- Article-writer (transparent perspective); publisher with the human gate enforced
  in code (no bypass flag, on purpose).
- Context-gathering step in the investigator + a tightened pattern-synthesizer
  (evidence the link, name the weakest link, downgrade by default).
- A **self-similarity / anti-monotony check** in the editorial-reviewer — added
  because two early pieces both landed on "fiscal stress → privatisation."
- Geographic emphasis (Kerala prioritised for the audience; national + international
  fully in scope — not just "as a lens"). Repositioned 2026-07-16; see Decisions.
- The **dig**: `story-scout` + `watchlist.yaml` — proactive, hypothesis-driven
  investigation from primary records, to *unearth* stories rather than wait.
- Public-tips discipline in `topic-intake` (tips are leads; protect sources; guard
  against weaponisation) — for when a public tip line opens (Phase 2).
- **Bio page** (the "link in bio" the slides promise): self-hosted at the slide
  server's `/` and `/bio`, auto-updated on every publish, managed via
  `/links`, `/addlink`, `/dellink`, `/pinlink` in the bot. See `docs/bio-page.md`.
- **Self-hosted article pages** at `/a/<run_id>-<headline-slug>` on the same
  domain — Telegraph is out of the article publish path (Telegram-owned domains
  are blocked/flaky on Indian ISPs; t.me doesn't even resolve on Anil's
  connection). Rendered per request from `pipeline_runs.draft_text`; only
  `status='published'` is served, so the human gate holds in the web path too.
  See `docs/article-hosting.md`.

---

## Open threads / next steps

**Editorial:**
- Run the **validation week** (`engine/DRY-RUN-PLAYBOOK.md`): review only, fill
  `engine/dry-run-log.md`, encode each miss as a rule.
- Ripe next **dig** (on the watchlist): Aravalli degradation; El Niño/monsoon (verify
  the forecast first).

**Your to-dos (not the engine's):**
- Check `@thelivu` handle availability (Telegram bot + channel).
- Verify the YouTube `channel_id`s in `engine/sources.yaml` (only FYI's is confirmed).
- Get a media lawyer's read before going public (defamation, IT Rules 2021, AI labelling).
- Decide the Instagram ingestion path (no RSS; Graph API or manual).
- ~~Push to GitHub~~ ✅ done.

**Deferred to post-validation (Phase 2+):** automation + API keys + hosting; the
public tip line. See `engine/DEPLOYMENT.md`.

---

## Quick reference — how to run things

- **Daily cycle:** "Run today's Thelivu cycle on FYI."
- **A dig:** "Run a dig on <watchlist theme>" (story-scout method), or `/dig` with no
  argument to let the scout pick the ripest theme itself.
- **A submitted topic:** just give it — topic-intake triages scope + worth first.
- Everything ends at the **human gate**. During validation, stop before publishing.
