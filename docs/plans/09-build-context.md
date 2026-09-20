# Plan 09 — build context

Written 2026-09-20, before writing any code. This is step 2 of Anil's five-step
workflow (understand → context file → build → compare → test); step 4 compares
what shipped against this document, so it is written to be checkable, not to be
agreeable.

Anil, 2026-09-20: *"complete the plan. You can leave the video generation part
to the end. Currently lets focus on the discovery part, facts, authenticated,
investigated."*

So: SCOUT and READER, and the SURFACE needed to see their output. Nothing in
`publishing/longform*` or `publishing/reel*` is touched by this work.

---

## What already exists (verified in the tree, not assumed)

| piece | where | state |
|---|---|---|
| fetch an HTML index of PDFs | `engine/digger/fetch.py` `fetch_index` | works |
| call a known JSON API | `engine/digger/jsonapi.py` | works, sansad only |
| validate a candidate source | `engine/digger/discover.py` | works, called by hand |
| a proposal that a person activates | `digger_targets` table | works |
| report a target that finds nothing | `shared/db.py` `barren_targets()` | reports; nothing acts |
| read a whole document, keep the text | `engine/corpus.py` | works (ingest tier) |
| pull findings from a document | `engine/analyst.py` | works (extract tier) |
| findings with a `cause` column | `findings` table | works |
| one table's level finding | `engine/digger/dataset_watch.py` `level_finding` | works, one table at a time |

**The gap is four things**, and each is a named hole in the plan:

1. Nothing turns a jurisdiction into inputs — 29 states are hardcoded in
   `targets.py`, "crore" is hardcoded in an analyst prompt. Plan §1.
2. The scout has no verify job and no way to find a JS-shell's API. Plan §2
   Agent 1. `barren_targets()` reports into a log nobody reads.
3. There is no synthesise tier. Extraction answers "what does this document
   say"; nothing asks the four cross-document questions. Plan §2 Agent 2.
4. 261 documents and five per-state series sit behind no interface. Plan §2
   Agent 3.

---

## What gets built

### A. Jurisdiction config — `jurisdictions/india.yaml` + `shared/jurisdiction.py`

The plan's own test: **if a rule mentions a rupee, a state name, or the CAG, it
is config.** Applied honestly, that means this is not a new file sitting beside
the old hardcoded lists — `targets.py` must *build* `CAG_STATE_TARGETS` from the
YAML, or the config is decoration.

- `entities` — the peer set every comparison runs over (29 + UTs)
- `money` — symbol, scale names (`crore` = 10^7, `lakh` = 10^5), grouping
- `fiscal_year` — starts 1 April, labelled `2023-24`
- `audit_body` — CAG, plus the recurring-objection vocabulary
- `portals` — seed domains for the scout
- `language` — en + regional

A second country is a second YAML and a scout run. Not a fork.

### B. SCOUT — `engine/digger/scout.py` + `engine/digger/apiscan.py`

**Verify** (the job that was missing). Re-check every active source on a
schedule: robots still permits us, the index still fetches, it still yields
links, and it is not barren. Each check writes a `source_checks` row, so
"this source has been dead for six days" is a query and not an inference from
logs.

**The scout proposes. It never activates — and it never deactivates either.**
A source that stops working gets `needs_review` and an alert. Killing a source
is as consequential as trusting one; both are a person's call.

**Find.** `apiscan.py` handles the plan's shape 3 — a JS shell whose documents
are not in the markup. Two tiers, because the honest version of "watch the
network" is a browser and this repo has no browser:

1. static endpoint mining — fetch the page, pull candidate endpoints out of
   inline JS, `__NEXT_DATA__`, `fetch(`/`axios` calls and `data-*` attributes,
   then probe each one and keep those that return typed rows. No new dependency.
2. browser network-watch via Playwright *if installed*. Optional extra, never
   a hard requirement — the digger box is 945MB under a 256MB cap and will
   never run a browser.

When tier 2 is unavailable that is **reported, not silently skipped** (invariant
4: silence is reported).

### C. READER, synthesise tier — `engine/synthesis.py`

The four questions from the plan, over `findings` + `documents`:

| detector | question |
|---|---|
| `recurring_objection` | the same objection in N consecutive years, never resolved |
| `structural_failure` | the same failure in N entities — structural, not local |
| `no_follow_through` | an audit finding with no follow-through in any later report |
| `wrong_direction` | a figure that moves the wrong way after an assurance |

**No model is in the detection loop.** Like `dataset_watch`, these are SQL and
arithmetic over grounded rows, so there is nothing here that could be a
hallucination. The model enters only at the attended write-up step, which a
person triggers.

**The flood rule is enforced structurally**: detectors read only `cause='state'`
rows. An `external` or `unclear` finding cannot reach a synthesis, because
"the state failed" and "it rained" are different stories and confusing them once
costs more than every finding is worth.

Output → a `syntheses` table, `status` starting at `new`, promoted by a person.

### D. SURFACE — command-center endpoints + page

Read-only. Proposals awaiting activation, source health, findings triage,
syntheses. **Freshness is a first-class field, in three bands** — `this month`
(parliamentary questions, enforcement orders), `this year` (datasets, budgets),
`the record` (audit findings). Never one "live" claim. A dataset last updated
16 months ago says so on the tile.

### E. Tests

`shared/tests/run_jurisdiction_cases.py`, `run_scout_cases.py`,
`run_synthesis_cases.py` — scratch SQLite via `DB_PATH`, no network, no API key,
matching `run_digger_cases.py`.

The property each one protects:

- jurisdiction: the India YAML reproduces the 29 targets that are hardcoded
  today, exactly. A config that quietly drops a state is worse than no config.
- scout: a proposal is never `active`; a barren source is flagged and never
  auto-removed.
- synthesis: an `external`-cause finding never reaches a synthesis, and every
  synthesis names the finding ids it rests on.

---

## Invariants this build must not break

From the plan §4, plus the repo's standing rules:

1. A refusal is a refusal — robots.txt and bot walls end the attempt.
2. A person activates a source. The scout proposes with evidence.
3. Every claim cites a retained document.
4. Silence is reported — a component that stopped working must say so.
5. Provenance travels with the claim.
6. We publish what we can show.
7. Publishing stays the only human-gated *action*; nothing here publishes.
8. Schema changes go in **both** dialects in `shared/db.py` — it is dual-dialect
   and a Postgres-only change works locally and breaks on Railway.

## Out of scope, deliberately

Video generation (reels, long-form) — Anil's instruction, left to the end.
OpenAleph — rejected 2026-09-15, it solves entity networks and would not have
found the Punjab finding. changedetection.io — the verify job it would replace
is being written here against sources we already hold; adopt it later if the
verify load outgrows a cron.

---

# Step 4 — what shipped, against what this document said

Written after the build, 2026-09-20. Every row was checked against the tree,
not remembered.

| planned | shipped | where |
|---|---|---|
| A. jurisdiction config | yes | `jurisdictions/india.yaml`, `shared/jurisdiction.py` |
| …and `targets.py` builds FROM it | yes — byte-identical output, asserted | `engine/digger/targets.py` |
| B. scout verify job | yes | `engine/digger/scout.py` `verify_all()` |
| …never activates, never deactivates | yes, and tested | `run_scout_cases.py` §4 |
| …writes a row per check | yes | `source_checks` table |
| B. static endpoint mining | yes | `engine/digger/apiscan.py` |
| B. browser tier, optional | yes, raises when absent | `apiscan.browser_watch()` |
| C. four detectors, no model | yes | `engine/synthesis.py` |
| …flood rule enforced structurally | yes — `db.state_findings()` is the only way in | `shared/db.py` |
| D. surface with three freshness bands | yes | `command_center/api/investigation.py`, `static/app.js` |
| E. three test suites | yes, all passing | `shared/tests/run_{jurisdiction,scout,synthesis}_cases.py` |

## Changed from the plan, with reasons

**`MIN_GROWTH` added to `wrong_direction`.** The plan said "a figure that moves
in the wrong direction". Implemented as monotonic-and-nothing-else, a series
drifting 100 → 105 over six years rises every year and is a story about
nothing — it came out of the test fixture looking identical to Punjab's
1,000 → 4,000. A run must now grow by half again before the direction is
reportable.

**`no_follow_through` requires coverage.** The plan says "no follow-through in
any later report". Taken literally that conflates *the later report was silent*
with *we never read a later report*, which are opposite conclusions from the
same absence. It now fires only where the corpus holds a later report for that
entity, and the claim says "not named again in any later report we hold".

**`wrong_direction` does not mention an assurance.** The plan's phrasing is "a
figure that moves in the wrong direction after an assurance". An assurance is
not something this corpus records. Claiming one would be inventing the half of
the sentence that makes it a story.

**The sweep goes one page deeper than planned — twice corrected, both live.**
The plan says "locate document indexes". First implementation examined the seed
host root, which is a homepage; `cag.gov.in` keeps its audit reports four paths
down. Then scoring links by the same vocabulary ranked six press-release PDFs
above every listing page, because a document's filename says "press release"
louder than the page that lists it. Then preferring deeper paths ranked
`/en/audit-report/details/31829` — one 2017 report — above `/en/audit-report`,
which lists all of them. Final: documents excluded, shallow-and-not-a-record-id
preferred. Verified live against cag.gov.in.

**Not built: changedetection.io adoption.** Out of scope as stated. The verify
job it would replace now exists as a daily cron over sources we already hold;
adopt it if that load outgrows a cron.

**Not built: Playwright in production.** `browser_watch()` works where
Playwright is installed and raises `ApiscanUnavailable` where it is not, which
is the digger box. The static tier is what runs unattended. This is a real
limitation, not a finished feature: a page that loads its endpoint from a
variable computed at runtime is still invisible to us, and the plan's
`rsdoc.nic.in` case was found by a human watching a browser.

## Live checks run

- `cag-kerala` verified end to end: robots ok, 16 document links, verdict `ok`.
- `cag.gov.in` swept: 6 listing candidates, `/en/audit-report` among the top two.
- `mospi.gov.in` swept: 0 candidates — reported as zero, not as an error.

## Still open after this build

1. The corpus has to be filled before the synthesise tier has anything to say.
   `engine/corpus.py backfill()` is the job; the detectors are waiting on it.
2. `needs_attention` still has no sweep (pre-existing, unrelated to this plan).
3. `PROJECT-STATUS.md` was 92 commits stale when this build started.
