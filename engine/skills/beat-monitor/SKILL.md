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

---

## The "join the dots" patterns — what to actively look for

These are the cross-database patterns that produce original scoops. Run at least two of these every cycle:

**Pattern 1 — Contract → Donor → Affidavit**
> Who won a major government contract in the last 6 months? Search company name in ECI donor disclosures. Search directors in MCA21. Do any directors appear in politician affidavits as business associates?

**Pattern 2 — Declared Wealth vs Actual Trajectory**
> Pick two MLAs or MPs. Search their 2019 and 2024 affidavits on MyNeta. If assets grew more than salary + known business income can explain, flag it. What businesses does the difference coincide with?

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
