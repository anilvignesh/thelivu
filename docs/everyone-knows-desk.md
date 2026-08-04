# Everyone Knows — the second desk

> **Status 2026-08-04. Complete — all six phases of §9 are done.** TWO series
> share this desk's pipeline and trust floor: **Everyone Knows** (`desk='ek'`)
> and **Turns Out** (`desk='gk'`, the GK/curiosity lane — added after the owner
> asked where the trivia department was, because the consequence rule below was
> binning exactly the GK material he had asked for). A failed consequence test
> is `ROUTE-GK`, not a kill.
>
> As of today the desk has an intake (owner submit + weekly scout), a cadence,
> a reader-facing page distinct from the reel's narration, a shape-B view label
> on both, and a green gate suite (9/9). Two reels exist: **#26** (Turns Out,
> illustrated, from run #140) and **#27** (Everyone Knows shape B, from run
> #145) — the first pieces this desk has put on screen.
>
> Run one belief by hand with
> `python -m engine.desks.ek.pipeline "<the belief>"`, or use the command
> centre's **Beliefs** view, which is the normal way in.

*Spec and context file. Written 2026-08-02, before any code. Build against this,
then check what shipped against it.*

Thelivu today is one desk: the **news desk**, which finds under-reported current
stories, verifies them, and publishes them. This document specifies a **second,
separate desk** — its own roles, its own skills, its own gate — that does a
different job on a different clock.

Public series name: **Everyone Knows**. Internal desk key: `ek`.

---

## 1. What it is

The news desk answers *"what happened that you weren't told?"*

Everyone Knows answers a different question: **"what do you already believe that
the record doesn't support?"**

Its unit of work is not an event. It's a **received belief** — a thing widely
taken as settled, where the documented record says something more interesting.
It is not tied to a news cycle, so a piece can be about 1904 or about last month.
Geography follows the news desk's rule (Kerala → India → world, ordered by
impact) but the pull here is *curiosity*, not urgency.

Two worked examples, from the owner, that define the two shapes the desk handles:

- **"Banana republic"** — a phrase everyone uses as a generic insult about a
  chaotic poor country. The record: coined by O. Henry in *Cabbages and Kings*
  (1904) about Honduras, describing a state run for the profit of the United
  Fruit Company. The phrase names a *specific mechanism of foreign corporate
  capture*, and it's now used to mean roughly the opposite — the country's own
  incompetence. The correction is **factual**.
- **"Communist states failed on their own"** — the record shows a long list of
  documented foreign interventions against elected and revolutionary left
  governments. Guatemala 1954 (CIA operation PBSuccess) and Chile 1973 (the
  Church Committee record) are declassified and airtight. But *"in most cases
  it was Western meddling"* is a **thesis**, not a fact, and there is real
  counter-evidence. The correction here is **a frame**, not a fact.

Keeping those two apart is the whole design. See §3.

## 1b. The aim, stated by the owner (2026-08-04)

> "One main aim for this desk is battling the bias from Western media. The
> entire web is dominated by them — praising them, covering their atrocities and
> stupidities. We will bring them out with satire, harmless yet knowledgable."
> …"we never mock the user, we will never bend the facts and truth. We uncover
> it and present it better and make sure it reaches people."

This is the desk's home ground, not a new direction: "banana republic" and
Guatemala 1954 are both exactly this shape. What the aim adds is a licence to be
**dry and pointed** about it, and two hard limits on that licence, which are now
written into the writers, the reviewer, the scout and the gate:

- **The target is fixed and it is never the reader.** Aim at the institution, the
  official line, the stock phrase. Someone who repeats what they were taught in
  school is who the piece is FOR. A line that makes them feel stupid is the wrong
  line however good the joke. (`explainer-writer` §Voice, reviewer check 9.)
- **The joke is a consequence of the record, never a substitute for one.** Strip
  the humour; if the plain sentence says less than the funny one did, the humour
  was doing evidentiary work it cannot do. (Reviewer check 10.)

**Where the raised bar lives, and where it must NOT.** The instinct is to make
`premise-check` suspicious of congenial corrections. That was tried on
2026-08-04 and it broke the desk's flagship case: guatemala-1954 started coming
back `MYTH_SWAP: yes` and dropping, about half the time. The reason is
structural — **premise-check has no web search.** Asked whether a correction is
under-documented, it cannot look, so it substitutes the only signal it has: does
this correction flatter our audience? That is the gate's own "strict on
narrowness, lenient on truth and currency" rule being violated by an edit meant
to strengthen it.

So `MYTH_SWAP` at the gate now means only what the gate can see — a candidate
arriving with its own replacement story attached and no nameable record — and
the symmetry test lives in `record-verifier`, which has the documents in front of
it: *if this piece corrected in the opposite direction, would I pass it on this
evidence?* A congenial conclusion lowers no floor and softens no bucket.

The failure mode to keep watching is **mirror-writing** — answering a flattering
Western account with an equally flattering account of someone else. The
counter-evidence requirement, the view label and reviewer check 11 exist for it.

## 2. Why it is a separate desk, not a mode of the news desk

Decided by the owner, 2026-08-02: separate unit, separate roles, separate
skills. The reasons are structural, not cosmetic —

- **The news desk's gate would kill every piece.** `newsworthiness-gate` DROPs
  anything "already well-covered" and anything without a live accountability
  hook. A 1904 etymology fails both. The floor for this desk is the opposite:
  *is the belief widely held, and is the record genuinely at odds with it?*
- **Under-coverage means something different.** The news desk's charter §2 says
  obscurity selects a story but never confirms it. Here the *belief* is the
  opposite of obscure — its popularity is the reason to run the piece. The
  obscurity is on the record side.
- **There is a failure mode the news desk cannot have.** A news story either
  happened or didn't. A "received belief" piece can be built on a belief nobody
  actually holds — a strawman erected to be knocked down. That needs its own
  verification step with no analogue upstream (§4, `premise-check`).
- **`_PIPELINE_CONTRACT` hardcodes "THIS IS A NEWS AGENCY"** into every skill's
  system prompt (`engine/agents/skill_runner.py:36`). The desks need different
  contracts.

## 3. The editorial core: two shapes, never blurred

Every piece is classified at the gate as exactly one shape, and the shape
determines the bar, the language, and the on-screen label.

### Shape A — the record corrects a factual belief

The popular belief contains a checkable factual error. "Banana republic means a
chaotic poor country" is wrong about where the phrase came from and what it
described.

- Bar: the corrective fact must be **established** — two independent sources
  minimum, primary or scholarly where they exist.
- Language: the piece may state the correction **as fact**.
- Label: none needed beyond the sources.

### Shape B — the record contests a frame

The popular belief is an *interpretation*. The piece's job is to put the
documented material the popular story leaves out in front of the reader, and to
argue the counter-frame **openly as a view**.

- Bar: the piece must be built on **one specific documented case**, in full.
  Guatemala 1954, worked properly, with the declassified record. Never
  "communism didn't fail" in general.
- The piece must **acknowledge the strongest counter-evidence**, not hide it.
  For the communism example that means the internal economic record and the
  Soviet-imposed systems are named, not skipped.
- Language: the documented case is stated as fact; the frame is marked as
  argument. Thelivu's existing stance — *transparent perspective*, argue a view
  and say that you are — is exactly the right machinery, and it is already in
  the charter.
- Label: an explicit view marker on the piece and in the reel.

### Killed at the gate, always

- **Broad theses.** If the claim can't be narrowed to a documented case, it does
  not run. This is the single most important rule in this document.
- **Strawman premises.** If the "everyone knows" belief isn't actually widely
  held, there is no piece. Manufacturing a myth to debunk is fabrication with
  extra steps.
- **Myth-swapping.** Replacing a popular story with a *different* under-sourced
  story that happens to flatter the audience. The charter's warning applies
  directly: the day a rule gets bent for a story too good to check is the day
  Thelivu becomes the thing it was built to replace. This desk is the most
  exposed to that failure of anything in the system, because its whole promise
  is "the truth behind what you believe."
- **Unfalsifiable claims** and anything that needs a conspiracy assumed to
  cohere. Inherited unchanged from the news desk's floor.

## 4. Roles and skills

Its own skill set, in its own directory. Named for what they do here, not
prefixed clones of news skills.

| Skill | Job | Model |
|---|---|---|
| `belief-scout` | Proposes candidate received beliefs from the themes file and the open web. The desk's discovery role. | Gemini (search-grounded) |
| `premise-check` | **The gate.** Four questions in one pass: (1) is the belief genuinely widely held — not a strawman, and restated to its moderate form if it arrived overstated; (2) shape A or shape B; (3) for shape B, is it narrow enough to be one documented case, or a broad thesis to kill; (4) does correcting it change anything — the `SO_WHAT` test. Emits `PURSUE-A` / `PURSUE-B` / `DROP` + reason. | Haiku (triage, strict contract) |
| `record-builder` | Assembles the documented record — primary documents, declassified material, scholarship. Explicitly gathers the strongest counter-evidence too, so the verifier and writer both see it. | Gemini (search-grounded) |
| `record-verifier` | **The trust gate.** Each corrective claim graded Fact / Allegation / Inference on the existing three-bucket rule, with the two-source floor. For shape B it additionally fails the piece if the counter-evidence is absent or strawmanned. Emits READY / FRAMING-FIX / HOLD / KILL, matching the news gate's vocabulary so downstream handling is shared. | Claude (Gemini Pro if it moves to search) |
| `explainer-writer` | Writes the piece: the receipt page, and the spoken spine the reel is cut from. Carries the shape label. | Claude |
| `explainer-reviewer` | Editorial review. Enforces the shape label, the counter-evidence requirement, the no-myth-swap rule, and legal. | Claude |

Model routing follows the locked split (`START-HERE.md` §3): research →
Gemini, writing/editorial/gates → Claude, presentation → free NVIDIA Gemma.
**No judgment or verification step moves to a cheaper model.**

Presentation reuses `video-script` and the reel renderer, but the news
`video-script` skill is news-shaped; an EK variant or a mode flag is needed so
the hook opens on the belief ("Everyone knows X…") rather than on a news lede.
Open item — §8.

## 5. Pipeline

```
themes.yaml + open web ──→ belief-scout ┐
owner-supplied belief  ─────────────────┴─→ premise-check ──DROP──→ ✗
                                                  │
                                          PURSUE-A / PURSUE-B
                                                  ↓
                                           record-builder
                                                  ↓
                                          record-verifier ──KILL/HOLD──→ ✗
                                                  ↓ READY / FRAMING-FIX
                                          explainer-writer
                                                  ↓
                                         explainer-reviewer
                                                  ↓
                                        ★ HUMAN GATE ★  (unchanged, non-negotiable)
                                                  ↓
                                   receipt page /a/<slug>  →  reel  →  post
```

The human gate is the same gate. Nothing about this desk relaxes it.

## 6. Intake

Both paths from day one (owner's call):

- **Owner-supplied jumps the queue.** A belief dropped via Telegram or the
  command center goes straight to `premise-check`. The banana-republic and
  communism examples enter this way.
- **The scout fills gaps.** `engine/desks/everyone-knows/themes.yaml` holds
  standing curiosities — the same shape as `engine/watchlist.yaml`, which the
  dig already uses. `belief-scout` runs on a schedule and proposes candidates
  for approval; the desk never goes idle while the owner is busy.

## 7. Data model and what is shared

**Recommendation: EK pieces are rows in `pipeline_runs`, tagged with a new
`desk` column, plus one side table for EK-only fields.**

The reason is concrete. `make_narrated_reel(run_id)` reads `get_run(run_id)` and
needs `draft_text`; `publish_run(run_id)` publishes from `pipeline_runs`;
`reels` and `carousel_runs` both carry `run_id INTEGER REFERENCES
pipeline_runs(id)`; the command center's media views are built on the same. Put
EK pieces in their own table and every one of those has to be widened or
duplicated. Put them in `pipeline_runs` with a desk tag and the reel, the
article page, the fileserver, the publish path and the CC media screens all work
on day one.

```sql
ALTER TABLE pipeline_runs ADD COLUMN desk TEXT NOT NULL DEFAULT 'news';
CREATE INDEX idx_pipeline_runs_desk ON pipeline_runs(desk);

CREATE TABLE ek_pieces (
    id            SERIAL PRIMARY KEY,
    run_id        INTEGER REFERENCES pipeline_runs(id),
    belief        TEXT NOT NULL,   -- the received belief, as people state it
    shape         TEXT NOT NULL,   -- 'A' (factual) | 'B' (frame)
    currency      TEXT,            -- premise-check's evidence that it IS widely held
    case_anchor   TEXT,            -- shape B: the one documented case
    counter_case  TEXT,            -- shape B: the strongest counter-evidence, named
    so_what       TEXT,            -- what shifts for the reader; the consequence test
    created_at    TIMESTAMP DEFAULT NOW()
);
```

Existing EK-only fields stay out of `pipeline_runs` so the news schema doesn't
accumulate columns that are null for 29 of 30 rows.

**The migration risk, stated honestly:** `pipeline_runs` is queried at **35 live
sites** (excluding the retired `dashboard.py`). Any read that should be
news-only and doesn't filter `desk='news'` will silently start counting EK
pieces — wrong RSS counters, EK items in the news gate queue, the chief of staff
recommending kills on a desk it knows nothing about. The mitigating fact is that
**25 of the 35 are inside `shared/db.py`** helpers, so the filter lands mostly
in one file. The build must enumerate all 35 and decide each one explicitly;
"add a default and hope" is how this goes wrong.

Sites: `shared/db.py` (25), `thelivu_bot/bot.py` (4), `command_center/api/system.py`
(3), `command_center/api/runs.py` (1), `command_center/api/ops.py` (1),
`engine/agents/learning.py` (1).

### Shared vs separate

| Shared unchanged | Separate per desk |
|---|---|
| Human gate, publish path, `/a/<slug>` pages | Skills and their prompts |
| Reel + carousel renderers, fileserver | The gate and its verdict vocabulary |
| Command center shell, auth, list controls | Themes / watchlist file |
| Budget governor, breaker, cost table | Intake and scheduling |
| Three-bucket rule, two-source floor, corrections policy | `_PIPELINE_CONTRACT` wording |

## 8. Open items

**Status 2026-08-04:** 1, 2, 3, 4 and 5 are closed; 6 is decided. What remains
open is listed at the end.

1. **`_PIPELINE_CONTRACT` is news-specific.** "THIS IS A NEWS AGENCY" is
   prepended to every skill's system prompt. Needs to become per-desk without
   weakening the "your training knowledge is never authoritative" clause, which
   matters *more* here — this desk works on historical material a model thinks
   it already knows, which is exactly when models confabulate.
2. **`_load_skill` reads one flat `SKILLS_DIR`.** Needs a second root
   (`engine/desks/everyone-knows/skills/`) or a `desk:skill` naming convention.
3. **Reel script skill.** News `video-script` opens on a lede. EK needs to open
   on the belief. New skill or a mode flag — decide at build time.
4. **Shape B's on-screen view label** needs a visual design in the reel and on
   the page. It must be legible to someone who watches muted and never taps
   through, because that viewer is the one most likely to take the frame as
   fact.
5. **Cadence.** The news desk is one piece a day. This desk's rate is unset;
   it competes for the same daily budget cap ($1.00) and the same reel-render
   time on the laptop.
6. **Does EK share the anti-repetition memory** (`_published_context`) with the
   news desk, or keep its own? **Its own, decided by default:** the belief
   pipeline never reads `_published_context`, and the scout dedupes against
   `taken_beliefs()` — the belief queue plus this desk's own runs — instead. A
   1904 etymology and a current story are not competing for the same reader
   slot, so the news desk's repetition memory would only have suppressed
   material for the wrong reason.

### Still open after 2026-08-04

- **No carousel has been built from a belief piece.** See §9.5.
- **A refused illustration takes the whole reel down to text slides.** Reel #27
  (Guatemala 1954) fell back because FLUX declined one shot out of eight —
  covert-action imagery is close to the model's refusal boundary, and the
  all-or-nothing rule means one refusal costs the illustrated look for the piece
  most likely to trigger it. The fallback is correct (a half-illustrated reel
  looks broken); what is wrong is that a whole class of this desk's subjects
  will reliably hit it.
- **Cadence has never actually fired on the Railway engine** — every belief run
  so far was started by hand or by `run_belief_cycle()` locally. The tick code is
  in `run.py`; the first unattended run is the thing to watch after this deploy.
- **The scout has not run against the live web yet.** `parse_candidates()` is
  checked against a hand-written sample in the prompt's exact format (two
  candidates, both lanes, trailing commentary ignored), but no real proposal has
  come back, so nobody has judged whether its candidates are any good.

## 9. Build order

Each phase ends somewhere testable; nothing publishes until the human gate, as
always.

1. ~~**Desk plumbing.**~~ **Skills-root half done (2026-08-02).** `DESKS_DIR`,
   `desk:skill` resolution in `_load_skill`, and the per-desk pipeline contract
   are in. The news desk's assembled contract is asserted byte-identical to its
   previous value, so nothing about the news desk moved. **The `desk` column and
   the 35-query-site audit are NOT done** — no EK piece can reach the DB yet.
2. ~~**The gate first.**~~ **Done (2026-08-02).** `premise-check` +
   `engine/desks/ek/tests/` — 9 cases, run with
   `python -m engine.desks.ek.tests.run_gate_cases`. **8/9, 1 known
   calibration gap.** What it establishes:
   - The breadth rule holds where it matters most: `communism-broad` is dropped
     with a specific narrowing proposed, while `guatemala-1954` — the same
     subject, narrowed — passes as shape B with PBSUCCESS as the case anchor
     and a serious counter-argument named. That pair is the desk's core
     working.
   - The trivia floor took two passes. The first version passed
     `goldfish-memory`, because the model graded verifiability rather than
     consequence. Adding a forced `SO_WHAT` field fixed that but overshot —
     it then killed borderline-consequential candidates. The calibration that
     works is **"is the belief doing work?"** (used to explain, justify, blame,
     dismiss, or claim authority) rather than asking whether the consequence
     sounds big, plus an explicit *when unsure, pursue*.
   - The restatement rule needed to be made procedural. Told only to "restate
     and judge that version", the model restated correctly and then bounced the
     candidate back as a strawman anyway. Numbering the steps, and reserving
     the strawman verdict for beliefs with no moderate version at all, fixed it.
   - **`gandhi-surname` — ruled 2026-08-04, suite now 9/9.** The case was
     failing, and not for the reason the note here assumed. Three findings, in
     the order they surfaced, because each was hiding the next:
     1. It was dropping as a **strawman**, not on consequence — reasoning that
        "no well-informed person holds that" and that the correction "has been
        repeatedly published", while its own `CURRENCY` line called the belief
        widespread. The skill now says plainly that a correction's existence is
        evidence a belief was common, and that the CURRENCY line and the verdict
        may not contradict each other.
     2. With that fixed it dropped again — and its `REASON` ended with the words
        "Route to GK lane." The prompt already forbade this in a worked example,
        a rule, and a paragraph headed "`DROP` is not available to you here".
        **More prompt was not going to fix it.** So the routing stopped being
        the model's to choose: `premise-check` now answers the four judgments as
        separate fields and `engine/desks/ek/gate.py` computes the verdict from
        them, logging any disagreement. The model judges; the arithmetic is
        arithmetic.
     3. The fields then exposed an older bug wearing a passing verdict.
        `colonialism-overstated` and `kerala-development` were being dropped as
        strawmen — the right verdict, the wrong reason, which the cases' own
        `also` notes had already said was unacceptable. `REAL_BELIEF` was being
        answered against the raw input rather than the moderated restatement, so
        `BELIEF` now comes FIRST in the output and every later field is defined
        as being about that sentence. Breadth is also asked of both shapes now:
        as a shape-B-only test, the gate escaped it by labelling a seventy-year
        causal thesis "factual".

     The editorial ruling itself: `expect` is `[PURSUE-A, ROUTE-GK]`. Which
     series the surname belief belongs to is a genuinely close call and either
     is the gate working; `DROP` is not, because binning a true, believed,
     checkable claim is the one thing the consequence floor must never do.
     Listing the acceptable verdicts says that; a single value plus `known_gap`
     only said "we know this one is off".
3. ~~**Research + verify.**~~ **Done.** `record-builder` (Gemini, grounded) +
   `record-verifier` (Claude). The verifier held the goldfish piece (#137) on the
   two-source floor unprompted — the floor is real, not decorative.
4. ~~**Write + review.**~~ **Done.** `explainer-writer`, `turns-out-writer`,
   `explainer-reviewer`, plus `pipeline.py` chaining the whole spine to
   `pending_human`. Two pieces at the gate: #139 and #140.
5. ~~**Presentation.**~~ **Done (2026-08-04).** Reels **#26** (run #140, Turns
   Out, illustrated) and **#27** (run #145, Everyone Knows shape B) are built.
   Three things had to be true first:
   - **The spine had to leave `draft_text`.** The writers emit one block —
     headline, dek, article, sources, spine — and runs #136-#140 stored it whole,
     so `/a/<slug>` would have taken its title from the `## ARTICLE` heading and
     printed the reel's narration under the sources. `engine/desks/ek/draft.py`
     splits it at write time: the reader-facing page (house markdown, same shape
     as a news piece, so publish/teaser/carousel/CC all work unchanged) into
     `draft_text`, the spine and the view label onto `belief_pieces`. Existing
     runs were migrated with `backfill_drafts.py`, which is idempotent.
   - **The reel is scripted from the spine, not from the article.**
     `publishing/belief_reel.py`. No `video-script` call, so no generation step
     lands downstream of the trust gate — the thing §9.5 said not to do. The
     words are copied; what is still chosen is captions, illustration scenes and
     hashtags. **A caption is read, so it is not free either:** a model proposes
     one and `caption_ok` accepts it only if it is a contiguous span of that
     spoken line, ≤8 words, that keeps the negation of the clause it quotes.
     It cannot introduce a word the verifier never saw, and it cannot turn "no
     man-made object is visible" into "man-made object is visible" by dropping
     the "no". Failing that test falls back to a deterministic clause cut —
     worse copy, identical guarantee. Cases:
     `python -m engine.desks.ek.tests.run_caption_cases` (no key, no network).
     After parsing, `spoken_matches_spine` re-checks the whole narration word for
     word, so a hand-edited script whose words drifted is refused too.
     Measured: the negation rule was per-sentence at first and rejected a good
     caption whose clause carried no negation at all; it is per-clause now.
   - **The shape-B label had to reach the muted viewer.** `A VIEW FROM THE
     RECORD`, an outlined pill on every story frame of both reel looks (never on
     the sign-off card — it makes no claim to qualify), and on the page as a
     `> [!VIEW]` callout rendered as a bordered aside rather than a blockquote,
     because italics say "nice line", which is the opposite of what it means.
     The wording is fixed, not the writer's sentence: a label that changes per
     piece is not a label.

   Not done here, and deliberately: **no carousel from a belief piece yet.** The
   slide composer is news-shaped and the belief page now parses like a news
   piece, so it is likely close to working — but "likely" is not "tried", and
   nobody has looked at the slides.
6. ~~**Intake + scheduling.**~~ **Done (2026-08-04).**
   - `engine/desks/ek/themes.yaml` — eight standing curiosities, same shape as
     `engine/watchlist.yaml`, each with the records that would settle it and a
     `caution` where the territory is dangerous.
   - `ek:belief-scout` (Gemini, grounded) proposes candidates weekly into a new
     `belief_queue` table, deduped against every belief the desk has already
     taken. `engine/desks/ek/scout.py`.
   - Intake is the command centre's **Beliefs** view: an owner-supplied belief
     lands `queued` (his submission IS the approval — §6), the scout's land
     `proposed` and wait for a nod. Everything there writes a row and sets a kv
     flag; the desk itself runs on the Railway engine, so a click never spends.
   - Cadence: one piece every `belief_cadence_days` (default 3), and it stands
     down for the day when more than 55% of the daily cap is already spent —
     the news desk has a clock and this desk does not, so it defers rather than
     competes. `run_belief_cycle()` returns the reason it did nothing, so a
     quiet desk is explicable.
   - `belief_auto_pursue` (default OFF) lets the cycle promote the scout's
     oldest proposal when nothing is approved. Off means Anil chooses what gets
     researched; on means the desk keeps working while he is away. Drafts stop
     at the human gate either way.

### The citation check (added 2026-08-03, not in the original spec)

`engine/desks/ek/linkcheck.py` tests every URL a piece cites and holds the run if
any are dead. It exists because the desk's first output passed the trust gate and
a clean editorial review while citing three 404s. Two findings worth keeping:

- **A model cannot catch this by reading, and prompting does not fix it.** The
  URLs were plausible and correctly shaped for real-sounding articles that are
  not at those addresses. Only asking the network settles it.
- **403 is not 404.** Merriam-Webster and Dictionary.com bot-block a scripted
  request while being perfectly real pages; treating those as dead would strip
  the best sources out of every piece.

Fixing it created the next failure, which is why "cites no URLs at all" is also
held: told it could omit addresses it had not retrieved, the writer emitted zero
URLs and degraded its sources into unfalsifiable categories. Silence is not a
pass.
