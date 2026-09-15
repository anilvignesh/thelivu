# The investigation framework

Anil, 2026-09-15:

> *"Let's build the frameworks which can then be used anywhere. Any country. For
> that we need more agents, one finding sources, making sure we have the updated
> things, secondly the ones who read, analyse and unearth things. Third is the
> dashboard."*

and, on what it is for:

> *"There we are pulling up news which the media is not giving enough coverage,
> in this we become the primary source of news."*

This is the design. Nothing here is built yet except where marked EXISTS.

---

## 0. What today proved, which the design is built on

Every one of these is a measurement from 2026-09-14/15, not a prediction.

| finding | consequence for the design |
|---|---|
| The digger read **7.1%** of a 258-page audit report and kept a 125-char excerpt | Reading and retention are the bottleneck, not model quality |
| Four of nine sources had produced **zero** candidates in their entire history | A source fails silently; discovery without verification scales the failure |
| The sansad API was found only by **watching the page**; the Rajya Sabha one lives on a different domain entirely (`rsdoc.nic.in`) | Source discovery needs a browser and cannot be pattern-guessed |
| A scan of 126.7M chars found Punjab's **₹33,973 crore advanced, ₹1,422 crore recovered** | The material is real and it is in the annexures |
| The same scan returned three **flood-damage** figures as though they were failures | Telling *the state failed* from *it rained* is judgement, not pattern-matching |

---

## 1. The country-agnostic split

**The method is already country-agnostic. Only the inputs are not.**

Nothing that worked today is about India: find document indexes on a government
domain; detect a JS shell and watch it for its API; tell a record from an office
circular by content; notice a source that has gone quiet; read whole documents
and keep the text; compare across years and across peer entities.

India supplies the *inputs*, and they are the only things that change:

```
jurisdictions/india.yaml
  entities:      29 states + UTs        # the peer set comparisons run over
  money:         ₹ / crore / lakh       # 1 crore = 10^7, grouping 2-2-3
  fiscal_year:   starts 1 April
  audit_body:    CAG                    # the recurring-objection vocabulary
  portals:       [...]                  # seed domains for the scout
  language:      en (+ regional)
```

Everything else is code. A second country is a second YAML and a scout run — not
a fork.

**Test for whether a rule belongs in code or config:** if it mentions a rupee, a
state name, or the CAG, it is config.

---

## 2. Three agents

### Agent 1 — SCOUT (finds sources, keeps them honest)

Two jobs, and the second is the one that was missing.

**Find.** Given a jurisdiction's seed domains, locate document indexes. Three
shapes, and the third is why this needs a browser:

1. an HTML index of PDF links — `fetch_index` handles it (EXISTS)
2. a JSON API — call it directly (EXISTS for sansad, `engine/digger/jsonapi.py`)
3. **a JS shell whose documents are not in the markup** — load the page, watch
   its network traffic, find the endpoint it calls

Shape 3 cannot be guessed. Lok Sabha's API is `sansad.in/api_ls/...`; Rajya
Sabha's is `rsdoc.nic.in/Question/Search_Questions`. Same institution, same
website, unrelated hosts. The only method that works is watching.

**Verify.** Re-check every active source on a schedule, because a source that
stops working does not raise an error — it produces plausible nothing. Already
half-built: `barren_targets()` (EXISTS) reports a target that fetches and never
finds. The scout owns that signal and acts on it.

**The hard boundary: the scout PROPOSES. It never activates.**
`engine/digger/discover.py` (EXISTS) already states the reasoning — *"a bad story
gets caught at the verification gate but a bad source, once trusted, quietly
shapes every story that flows through it"* — and a proposal carries its evidence:
robots, fetch, document count, a parsed sample.

### Agent 2 — READER (reads, analyses, unearths)

Three tiers, because they have different costs and different failure modes.

| tier | runs on | job | failure mode |
|---|---|---|---|
| **ingest** | free / local | parse whole documents, retain text | a scan with no text layer |
| **extract** | free models, at volume | pull figures, objections, entities per document | hallucinated figures — caught by grounding |
| **synthesise** | paid or **attended** | what matters, across documents | calling a flood a failure |

The split is not about money. It is about what each tier can be wrong about.
An extraction error is caught by checking the quote against the document. A
synthesis error — *this is a scandal* when it is a monsoon — cannot be caught
mechanically, which is why that tier is attended.

**What synthesis can ask that no single document answers:**
- the same objection in N consecutive years, never resolved
- the same failure in N states — structural, not local (`level_finding` EXISTS,
  but sees one table at a time)
- an audit finding with no follow-through in any later report
- a figure that moves in the wrong direction after an assurance

### Agent 3 — SURFACE (dashboard)

Read-only. Mostly a surfacing problem: five per-state series and 261 documents
already exist behind no interface.

**Freshness is a first-class field, not a footnote.** Measured 2026-09-15: the
NH-projects dataset was last updated **16 months ago**. A tile reading
*"88% of highway projects delayed in Arunachal Pradesh — from a dataset the
Ministry last updated 16 months ago"* is stronger than the number alone, and it
is a finding no one else publishes. Three bands, never one "live" claim:

```
this month   parliamentary questions, enforcement orders
this year    datasets, budgets
the record   audit findings from the corpus
```

---

## 3. Build or adopt

Researched 2026-09-15.

**[OpenAleph](https://openaleph.org/) / OCCRP Aleph — NOT NOW, and the reason
matters.** It needs 8GB+ RAM and Elasticsearch, which the worker could now host.
But Aleph solves *entity networks across datasets* — "this person appears in 40
documents across 12 registries". Our documents are audit reports: the entities
are schemes and departments, and **Aleph would not have found the Punjab
finding**, because that was reading comprehension, not entity resolution.
Adopt it if and when we ingest contracts, tenders, company registries or asset
declarations — data where the entity IS the story. Note also that Aleph is
moving commercial in 2026 with OpenAleph as the community fork.

**[changedetection.io](https://github.com/dwongdev/changedetection.io) — ADOPT
for the scout's verify job.** Self-hosted, and it has a browser-rendered mode for
JS-heavy pages, which is exactly our shape-3 problem. Monitoring "has this index
published something new" is a solved problem and not worth writing.

**Build ourselves:** the reader and synthesis tiers, the corpus, the
jurisdiction config, the proposal/activation flow. These are the parts where our
requirement is genuinely unusual — a corpus of prose audit reports compared
across years and peer entities.

**Already adopted and working:** liteparse (parse + OCR), Wayback (independent
archival), data.gov.in, freellmapi (free-tier routing).

---

## 4. Invariants

These hold in every country and are not negotiable by any agent.

1. **A refusal is a refusal.** robots.txt and bot-walls end the attempt. Today:
   Supreme Court judgments and RBI's document host are both closed to us, and
   both stay closed. An API is a different door into the same building.
2. **A person activates a source.** The scout proposes with evidence; nothing
   enters the rotation unread.
3. **Every claim cites a retained document.** The archive captures bytes at read
   time, because by the time a URL rots a re-download fails too.
4. **Silence is reported.** A component that has stopped working must say so —
   `shared/health.py` (EXISTS), built because six failures in one day were all
   silent.
5. **Provenance travels with the claim.** Source and date on the frame, not only
   in the description.
6. **We publish what we can show.** A finding whose document we cannot produce
   is not a finding yet.

---

## 5. Order of work

One at a time, per Anil.

1. **Scout** — discovery (incl. browser-assisted API finding), verification,
   proposals. Highest leverage: everything downstream needs sources, and this
   is the role I have been filling by hand all week.
2. **Reader** — synthesis over the corpus that already exists. The material is
   proven to be there.
3. **Surface** — the dashboard, once there is something worth showing daily.

Existing pipelines keep running throughout, unchanged.
