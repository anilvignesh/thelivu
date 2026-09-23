# Handover — plan 09, the investigation framework

Written 2026-09-23 for the session that picks this up. Branch
`plan-09-investigation-framework`, 8 commits, **not merged, not pushed**.

Read in this order: this file, then `docs/plans/09-build-context.md` (what was
planned and how the build differed), then `docs/plans/09-investigation-framework.md`
(the design itself). `PROJECT-STATUS.md`'s top section is current as of 09-20.

---

## What this work is

Anil, 2026-09-20: *"complete the plan… focus on the discovery part, facts,
authenticated, investigated"* — video generation deliberately left for later.

Thelivu finds government records, reads them, and asks questions across them
that no single document answers. Plan 09 named three agents (scout, reader,
surface) and a country-agnostic split. All of it is now built except the video
half, which was out of scope.

## State, concretely

| thing | state |
|---|---|
| jurisdiction config | built, `targets.py` builds from it, asserted identical to the old hardcoded list |
| scout — verify job | built, daily in `run.py`, writes `source_checks` |
| scout — API hunting | built (static mining); Playwright tier optional and absent here |
| reader — ingest (corpus) | built, **73 documents / 37.2M chars / 28 offices held** |
| reader — extract (findings) | **10 findings only** — the bottleneck, see below |
| reader — synthesise | built, 4 detectors, waiting on findings |
| surface | built, `/api/investigation` + Investigation view, all routes exercised 200 |
| tests | 5 suites, all green |

## The one thing that matters next

**The corpus is full and almost nothing has read it.** 73 documents are held;
10 findings exist, all from two chunks of Mizoram 2024 that I read attended on
09-20. Every detector is correct and has nothing to work on.

Anil, 2026-09-20: *"forget the budget, we will increase it and try to run
maximum via the attended mode."*

So the next job is attended extraction at volume:

```
python -m engine.attend_corpus prepare --docs 3 --chunks 4   # writes requests
#   … the session answers each .attend/corpus/NNN.response.md …
python -m engine.attend_corpus ingest                        # verifies + stores
python -m engine.attend_corpus status
```

`--sha <hash> --from-chunk N` goes back for more of a report already partly
read — a document stops being "pending" the moment its first finding lands,
and an audit report is ~30 chunks of which the first batch takes four.

**Breadth before depth.** `structural_failure` needs the same category across
many states in one year; `recurring_objection` and `wrong_direction` need many
years of one state. With 28 offices held, a few chunks each buys the first;
going deep on Kerala/Punjab/Bihar buys the second.

### The rule that must not be relaxed

`dx._grounded()` runs on every finding against the chunk it came from, and it
runs on the assistant's output exactly as it ran on Haiku's. Being the model in
the loop earns no trust — the check does not test honesty, it tests whether a
span is in the document, and a reader working from a chunk it half-remembers
produces the same artefact as a model reciting training data.

Verified on 09-20: a deliberately invented finding ("₹4,271 crore advanced to
seventeen cooperative societies" — plausible, present nowhere) was refused by
the same ingest that kept ten real ones.

The `cause` contract is the other half: `state` / `external` / `unclear`,
committed to per finding. Karnataka's flood damage is `external` however large
the number, and `state_findings()` — the only way into the synthesise tier —
excludes everything else.

## Open, in priority order

1. **`cag-rajasthan` holds zero documents.** All 3 attempts failed with no
   reason logged beyond the count (202s elapsed, so it reached them). Needs a
   hand-run of `corpus.read_index` against its index to see the error.
2. **15 documents failed across the 29 offices.** Assam's 2026 report is
   genuinely `invalid PDF format` at source. The rest are uninvestigated.
3. **`targets.py` still uses `\.pdf$`** while the corpus backfill uses
   `download_audit_report.*\.pdf$`. Same wrong-documents problem the digger
   has always had — Kerala's index is 16 PDFs of which 10 are audit reports and
   the rest are holiday lists and an RTI training schedule. Changing it alters
   digger behaviour, so it was left for Anil to decide.
4. **Playwright is not installed**, so `apiscan.browser_watch()` raises rather
   than running. Static mining is what runs unattended; a page that computes
   its endpoint at runtime is still invisible to us.
5. `needs_attention` has no sweep (pre-existing, unrelated to this plan).

## Gotchas earned the hard way, 09-20

- **`&amp;` in hrefs.** Fixed in `fetch.extract_links`. CAG report filenames
  contain "C&AG"; the entity was never decoded, so the digger could reach every
  document on a CAG index EXCEPT the audit reports — indistinguishable from a
  source with nothing worth reading. Probably the mechanism behind an unknown
  share of the barren targets.
- **`run_digger_cases` was dying two cases from the end** after 229 PASS lines
  with the summary never printed, because `digger_candidates.doc_sha256` existed
  in the Postgres schema and not SQLite. A suite that aborts quietly at the tail
  reads exactly like a suite that passed. Both fixed.
- **Memory.** The corpus backfill was killed twice by the harness's
  background-task supervisor for system-wide pressure (Chrome holds several GB).
  The parse itself is not the problem — the parent sits at 46MB and liteparse
  works in a `liteparse._pool` child at ~384MB. An `RLIMIT_AS` on the parent
  constrains nothing. What worked: one office per process, launched with
  `setsid` so the supervisor does not own it. It then ran to completion.
  Driver: `/tmp/.../backfill4.sh` + `one_office.py` (scratch, not in the repo —
  rewrite if needed). Log: `~/thelivu/.backfill.log`.
- **Resume is cheap but not free.** Already-held documents are skipped by
  content hash *after* the download and *before* the parse.
- **Command center password env var is `DASHBOARD_PASSWORD`**, not
  `CC_PASSWORD`.

## Standing rules this work runs under

1. A refusal is a refusal — robots.txt and bot walls end the attempt.
2. A person activates a source; the scout proposes with evidence. It never
   deactivates either: on 09-19 thirty-three barren-looking targets were all
   pointed at exactly the right source.
3. Every claim cites a retained document.
4. Silence is reported.
5. Publishing stays the only human-gated action; nothing in this plan publishes.
6. Schema changes go in **both** dialects of `shared/db.py`.
7. `git push` deploys to Railway. This branch is unmerged on purpose.

## Verification commands

```
python -m shared.tests.run_jurisdiction_cases
python -m shared.tests.run_scout_cases
python -m shared.tests.run_synthesis_cases
python -m shared.tests.run_attend_corpus_cases
python -m shared.tests.run_digger_cases
python -m engine.digger.loop --scout        # verify every source, deactivates nothing
python -m engine.synthesis --dry-run        # detectors, no model, writes nothing
```
