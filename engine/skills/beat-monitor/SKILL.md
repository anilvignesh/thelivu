---
name: beat-monitor
description: Scan primary government sources (ECI, CAG, RBI, courts, company filings, budget data) for under-covered developments and cross-database patterns on Thelivu's beats. Use for proactive primary-source monitoring — not RSS feeds, but the actual records. Trigger for "run the beat", "check primary sources", "what's in the data". Produces leads only — never verified or publishable copy.
---

# Beat Monitor

This skill digs primary records for under-covered stories — the audit paragraph nobody quoted, the court order that went unreported, the affidavit that contradicts what someone said in public. RSS feeds give you what journalists already found. This finds what they missed.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present.

**Hard exclusion:** cinema, celebrity, sports, entertainment, PR. If an item falls there, drop it immediately without scoring.

---

## Primary sources to check every cycle

Use web_search to probe each of these. Do not just check that the site exists — search for recent activity, recent filings, new entries.

### 1. Election Commission of India — follow the money

- **Candidate affidavits (MyNeta):** Search `site:myneta.info [name OR constituency] affidavit 2024` to find wealth declarations. Flag any MLA/MP where declared assets grew more than 50% term-over-term. This is a primary record — the affidavit is the primary source.
- **Electoral bonds:** Search `electoral bonds SBI ECI disclosure [company name]` — who bought, who received, what contracts followed.
- **Party accounts:** Search `ECI political party financial statement 2024` — late submissions, unexplained income.
- **Key question:** Does the trajectory of declared wealth match a plausible income path? If not, what changed?

### 2. CAG (Comptroller and Auditor General) — buried audit findings

- Search `CAG report Kerala 2024 site:cag.gov.in` and `CAG report India [ministry] 2024`.
- CAG reports are PDFs — look for summary paragraphs in press coverage too: `CAG finds Kerala [department]`.
- **What to flag:** Any paragraph showing funds diverted, scheme targets missed by >30%, expenditure without sanction, ghost beneficiaries.
- **Key pattern:** Scheme X received ₹Y crore; CAG found Z% unspent or irregularly spent. Who was the implementing officer? Is it the same department that received a budget increase the following year?

### 3. RBI — enforcement actions and bank health

- Search `RBI penalty [bank name] 2024` and `RBI enforcement action Kerala cooperative bank`.
- Search `RBI PCA prompt corrective action bank 2024` — banks under stress that may not have made news.
- **Key pattern:** A cooperative bank penalised → who are the directors? Any political connections? Are depositors at risk?

### 4. High Court and Supreme Court — orders that didn't make news

- Search `Kerala High Court order [topic] 2024 site:hcservices.ecourts.gov.in` or just `Kerala High Court [topic] order 2024`.
- Look for: PIL outcomes, contempt proceedings against government, stay orders on infrastructure projects, bail conditions for political figures.
- **Key pattern:** Court ordered X by date Y — did the government comply? A contempt case filed after non-compliance is a story most outlets miss.

### 5. Company filings — MCA21 connections

- Search `MCA21 [company name] director` or `[company name] ROC filing Kerala`.
- When a government contract is awarded: who is the contractor? Who are their directors? Do those directors share board memberships with other companies that received contracts from the same department?
- Search `[politician name] company director site:zaubacorp.com` or `site:tofler.in`.
- **Key pattern:** Director of Company A → Director of Company B → Company B wins government contract → Company A receives subcontract.

### 6. Budget and spending data

- Search `Kerala budget 2024-25 [department] allocation` vs `actual expenditure`.
- Search `[scheme name] PFMS expenditure 2024` — PFMS is the central government's payment system and often has publicly visible spending data.
- Search `unspent balance Kerala [scheme] 2024`.
- **Key pattern:** Large allocation + near-zero spending = either the scheme is a sham or there's implementation failure. Either is a story.

### 7. RTI filings and CIC orders

- Search `CIC order [topic] 2024` — Central Information Commission orders when RTI was denied.
- Search `RTI Kerala [department] disclosure 2024`.
- **Key pattern:** Government denied an RTI → CIC ruled in requester's favour → what was disclosed? Or: government still hasn't complied with a CIC order to disclose.

### 8. Legislature — questions and evasions

- Search `Lok Sabha question [topic] 2024` or `Kerala Assembly question [topic] 2024`.
- Look for: questions with evasive or contradictory answers, starred questions that went unasked, minister statements that contradict data released elsewhere.
- `site:sansad.in [topic]` for Parliament questions.

### 9. Regulatory filings — SEBI, IRDAI, TRAI

- Search `SEBI order [company] 2024` — enforcement actions, insider trading findings.
- Search `TRAI order [telecom issue] 2024` — especially surveillance, call-data, interception orders.
- Search `IRDAI penalty insurance company Kerala 2024`.

### 10. Municipal / urban local body finance

City corporations run budgets in the hundreds to thousands of crores with far less scrutiny than
state or central government — added 2026-09-10 after finding two live, apparently under-followed
leads in a single pass on BBMP alone.

- **Local-body CAG audits — nationwide, not city-specific.** `data.gov.in/catalog/cag-local-bodies-audit-reports`
  is the Open Government Data Platform's consolidated catalog of CAG local-body audits across
  states — the right first stop for any metro or tier-1 city, not just the ones already checked.
  State Accountants General also publish directly, e.g. `cag.gov.in/ag1/karnataka` for
  Karnataka/BBMP — search `cag.gov.in [state] audit report [city corporation name]` per city when the
  OGD catalog doesn't have it. These findings run into the thousands of crores and rarely get
  follow-up coverage past the initial headline.
- **Budget vs. actual expenditure.** Search `[city corporation] budget estimates [year] site:data.opencity.in`
  — a civic-data aggregator that mirrors municipal budget PDFs for multiple Indian cities (confirmed
  for GHMC; check coverage for others). Compare the claimed revenue surplus/deficit against visible
  service delivery — a paper surplus next to unaddressed civic complaints is a story.
- **Procurement and tenders.** City corporations publish e-tender awards. Cross-reference winning
  contractors against MCA21 director data (Pattern 1, below) exactly as for state contracts — the
  same director-overlap pattern applies at municipal scale and is checked far less often.
- **Key pattern:** an audit finding sits unresolved for years (BBMP has objections dating to
  1964-65) — who benefits from the non-resolution being the actual story, not just the original
  finding.

### 11. GDP and macroeconomic data

- Search `MOSPI GDP estimate [quarter/year]` and `NSO GSDP [state] [year]` — the government's own
  released growth figures, which get cited in headlines far more often than actually checked against
  the underlying release.
- Search `RBI monetary policy report [date]` for the central bank's own growth/inflation read, useful
  as a cross-check against the government's official GDP claim in the same period.
- **Key pattern:** a state or the centre claims a growth figure in a speech or press release — does
  the cited MOSPI/NSO release actually say that, or is the number rounded, cherry-picked from a
  favorable quarter, or compared against a revised-down base year? The gap between the claim and the
  primary release is the story, not the growth number itself.

### 12. Union government — scheme spend, ad spend, official travel

The centre gets less routine scrutiny than state governments on exactly the categories that are
most trackable, because the primary records already exist and are already public.

- **Scheme allocation vs. actual spend.** CAG performs Union-level audits, not just state ones —
  search `cag.gov.in Financial Audit Report Union Government [year]` and
  `CAG performance audit [scheme name]`. A CAG report tabled April 2026 flagged **₹54,282.32 crore in
  unaccounted Central expenditure** for FY2024-25 — check whether that finding, or one like it, has
  had any real follow-up before assuming it's been covered.
- **Government advertising spend.** The Central Bureau of Communication (formerly DAVP) tracks this,
  and it is RTI-able and periodically disclosed in Parliament — search
  `DAVP OR "Central Bureau of Communication" advertisement expenditure crore [year]` and
  `Lok Sabha question government advertisement expenditure [year]`. Historical figures already
  public: ~₹10,000cr over 2002-03 to 2017-18, ~₹713cr in 2019-20, digital/social spend growing from
  ~₹14cr (2020-21) to ~₹131cr (2025-26) — the pattern is to compare a period's ad spend against the
  scheme spend it's meant to be publicizing, not to report the ad figure alone.
- **PM and VVIP foreign travel.** Cost breakdowns are periodically disclosed via RTI and tabled in
  Parliament (the RTI activist Commodore Lokesh Batra's disclosures are a recurring, citable primary
  source for this) — search `Rajya Sabha OR Lok Sabha PM foreign visit cost crore [year]`.
  **Accuracy note:** the Air India One aircraft purchase (~₹8,400cr for two Boeing 777s) is a
  one-time capital cost serving the President, Vice-President and PM — never fold it into a
  routine-travel figure, that's exactly the kind of number-conflation the fact-check gate exists to
  catch.
- **Who benefits.** Same cross-referencing as Pattern 1, applied to Union-level contracts and scheme
  implementing agencies — winning vendor → MCA21 directors → any overlap with declared political
  affiliations or donor records.

### 13. Group and communal violence — accountability, record-based only

A real, legitimate beat — and the one place on this list where the charter's neutrality mandate
(§2, "no fixed villains") has to be applied most deliberately, because the failure mode here is
starting from a name instead of a record.

- **Never start from an organization.** Start from a specific incident (a date, a location, an FIR
  number) and follow the record to whoever it actually names — search `FIR [incident] [date]
  organizers named` and `chargesheet [incident] court`. If the record names an individual or a
  group, report that; if it doesn't, there is no story yet, regardless of who public suspicion has
  already settled on.
- **Distinguish stages precisely** — named in an FIR ≠ chargesheeted ≠ convicted, same discipline as
  the charter's verb-precision rule for scheme status (tabled ≠ passed, alleged ≠ found ≠ proven).
- **Apply identically regardless of which side of the aisle it lands on.** The charter's own symmetry
  test — a month with no story inconvenient to the editor's own sympathies means the lean crept back
  in — governs here exactly as it does everywhere else on this list. An outlet that investigates
  violence linked to one organization and gives every other organization a pass fails its own
  credibility test, not just a rule.
- **Key pattern:** police action or inaction after a communal incident — was an FIR filed promptly,
  against whom, and does the chargesheet (if any) match the initial public allegations or diverge
  from them? A diverging chargesheet, in either direction, is itself the story.

---

## The "join the dots" patterns — what to actively look for

These are the cross-database patterns that produce original scoops. Run at least two of these every cycle:

**Pattern 1 — Contract → Donor → Affidavit**
> Who won a major government contract in the last 6 months? Search company name in ECI donor disclosures. Search directors in MCA21. Do any directors appear in politician affidavits as business associates?

**Pattern 2 — Declared Wealth vs Actual Trajectory**
> Pick two MLAs or MPs. Search their 2019 and 2024 affidavits on MyNeta. If assets grew more than salary + known business income can explain, flag it. What businesses does the difference coincide with?

**Pattern 2b — Declared Number vs Visible Lifestyle (2026-09-10)**
> The affidavit figure and the visible lifestyle are two different signals, and the second is
> checked far less often. A politician can under-declare or hold assets benami; a genuinely
> disproportionate lifestyle — a property, a vehicle, a child's school, a foreign trip — reported in
> the record (a registered property document, a vehicle registration, court/RTI records naming an
> asset) is evidence in its own right, independent of what the affidavit says. **The distinction that
> keeps this charter-safe: report the documented record (a specific registered property, a specific
> disclosed trip), never a bare "how does he afford this" inference from visible wealth alone** — the
> latter is exactly the unverifiable-innuendo pattern the charter's neutrality mandate forbids. If a
> visible-lifestyle lead can't be traced to an actual record, it's not a lead yet, it's a hunch — hold
> it, don't publish the suspicion.

**Pattern 3 — CAG Finding → Next Budget**
> A CAG report flagged fund diversion in Scheme X in 2022. Did Scheme X receive a budget increase in 2023 or 2024? Did the implementing officer get transferred or promoted? Both are stories.

**Pattern 4 — Court Order → Compliance Gap**
> Court ordered government to act on X by Y date. Has it? Search for contempt petitions filed after the deadline. Non-compliance with court orders is both a legal story and a governance story.

**Pattern 5 — Quiet Regulatory Action**
> RBI/SEBI penalised an entity. Map who the entity is, who its directors are, whether any director is politically connected, and whether the penalty was reported anywhere. Most small regulatory actions are never covered.

**Pattern 6 — RTI → Denial → What's Hidden**
> A prominent RTI was denied. CIC ruled for disclosure. Was it disclosed? If not, what is the government protecting? If yes, what did it reveal and did any outlet report it?

---

## Output format

```
# Beat Monitor — [date]

## Lead 1: [the specific finding — what the record shows]
- Source: [exact URL or search query that surfaced it — primary source]
- Source tier: 1 (primary record) | 2 (established news)
- Pattern: [which dot-joining pattern this came from, if any]
- Why under-covered: [who has / hasn't reported this, and why that's surprising]
- Impact: [who is affected, how many, what's at stake]
- Dots to join: [what other database or record should the investigator cross-check]
- Priority: High | Medium | Low
- Open question: [the single most important thing the investigator should dig into]

## Lead 2: ...
```

If a dot-joining pattern produced a partial connection but not a full lead, surface it anyway as a Low-priority lead with the partial connection noted — the investigator may be able to complete it.

If no leads meet the under-coverage test, say so clearly and explain what you checked. Do not manufacture leads to fill the format.
