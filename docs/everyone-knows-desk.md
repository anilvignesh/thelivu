# Everyone Knows — the second desk

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
   news desk, or keep its own? Probably its own — a 1904 etymology and a
   current story are not competing for the same reader slot.

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
   - **Open editorial question:** `gandhi-surname` is dropped as trivia. The
     gate's reasoning is defensible (the dynasty's legitimacy rests on other
     grounds), but it may be too strict. Owner's ruling needed. Forcing it to
     pass would loosen the floor that correctly kills the two trivia cases —
     see the case's note in `gate_cases.yaml`.
3. **Research + verify.** `record-builder` + `record-verifier`, tested on both
   worked examples end to end, output inspected by hand.
4. **Write + review.** `explainer-writer` + `explainer-reviewer`, producing a
   receipt page for banana republic. First human-gate review.
5. **Presentation.** EK reel script + the shape-B label design; one reel end to
   end.
6. **Intake + scheduling.** `themes.yaml`, `belief-scout`, owner-supplied path,
   CC view, cadence.
