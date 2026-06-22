# News Engine — System Design & Build Plan

*Status: planning document. Nothing here is built yet. Treat the charter (`CHARTER.md`) as the constitution; this document is the engineering and operations plan that implements it.*

---

## 0. What this system is

A semi-automated pipeline that:

1. **Ingests** a curated set of trusted explainer/accountability sources (YouTube channels, Instagram, etc.) — back-catalog first, then new posts as they appear.
2. Treats each post as **a lead, never a finding.**
3. **Verifies** the factual claims in that lead against the wider web, scoring them.
4. Where the facts clear a high bar, **writes an original article** built from the verified facts (not a re-voicing of the source), crediting the originating source.
5. Routes every article to **a human gate (you)** — the only thing that can authorize publishing.
6. **Publishes** approved articles to a Telegram channel, and tracks corrections.

Editorial focus: Kerala first, then India; under-appreciated, high-impact, explanatory stories rather than breaking news.

### The one decision still open

**The stance dial.** The system must be configured as one of:
- **Neutral explainer** — "we explain what matters; you decide." (ColdFusion / FYI model.)
- **Transparent perspective** — "we explain from the side of ordinary people, and we say so." (More Perfect Union model.)

This changes how the article-writer and editorial-reviewer are tuned (symmetry test, framing rules, headline tone). It does **not** affect ingestion or verification, so the system can be built up to the writer before this is settled. **Decide before the first article publishes.**

---

## 1. Non-negotiable principles (from the charter)

These are load-bearing. Every design choice below serves them.

1. **Nothing auto-publishes.** The human gate is mandatory and final.
2. **Under-coverage selects, never confirms.** Obscurity says "look here," never "this is true." Obscure claims face a *higher* bar.
3. **One source proposes, the whole web disposes.** A claim's origin never counts toward its own verification.
4. **Three buckets, always:** Fact / Allegation / Inference. Inference is never laundered into fact.
5. **Build, don't re-voice.** Articles are original synthesis from independently verified facts, crediting the source that surfaced the lead. Never a reworded transcript.
6. **Verify facts, judge framing.** A verified set of facts does not verify an *argument*. Framing is checked separately for fairness and nuance.
7. **Corrections are visible and fast.** A wrong piece pulled quickly beats a wrong piece defended.

---

## 2. Architecture overview

```
 SOURCES (YouTube, IG, ...)
        │  RSS feeds + back catalog
        ▼
 ┌──────────────────┐   transcript + claims + timestamps + cited-sources
 │  source-ingestor │   (Gemini: native video/audio/visual)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐   ranked candidate leads (impact × under-coverage)
 │   news-monitor    │   (triage; dedupe; follow-up detection)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐   evidence dossier (claims bucketed, sources gathered)
 │  news-investigator│   (Claude)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐   verification report + TRUST SCORE (Pass/Hold/Kill)
 │  source-verifier  │   (Claude; optional Gemini cross-check)
 └────────┬─────────┘
          ▼  (only Pass proceeds)
 ┌──────────────────┐   draft article (original synthesis, sourced, source credited)
 │  article-writer   │   (Claude; stance dial applies here)
 └────────┬─────────┘
          ▼
 ┌──────────────────┐   publish-readiness verdict + required edits
 │ editorial-reviewer│   (Claude; nuance/framing/symmetry/legal)
 └────────┬─────────┘
          ▼
 ┌────────────────────────────┐
 │   ★ HUMAN GATE — YOU ★      │  approve / edit / send back / kill
 └────────┬───────────────────┘
          ▼ (approved only)
 ┌──────────────────┐
 │    publisher      │  → Telegram channel
 └──────────────────┘
          │
          ▼  published log · corrections log · grievance inbox
```

### Multi-model split

- **Gemini** — ingestion only: native YouTube/IG video + audio, transcription, on-screen visual extraction, timestamped claim extraction. (Plays to its native YouTube/video strength.)
- **Claude** — reasoning and language: investigation, verification, editorial review, article writing.
- **Cross-model check (optional, recommended):** have Gemini independently re-verify a sample of the claims Claude verified (or vice versa). The two model families don't share the same blind spots, so disagreement is a useful flag to the human. Not a substitute for the gate.

---

## 3. Skill specifications

Each is a separate skill (`SKILL.md`). Drafts for the middle four already exist; the ingestor, writer, and publisher are specified here for building later.

### 3.1 source-ingestor (Gemini)
- **In:** a video/post URL (from RSS or back-catalog list).
- **Out:** `{ transcript, claims[] (each with timestamp + the source the video itself cites, if any), notable_visuals[], source_tag: "Tier3 / <channel>" }`.
- **Rules:** default to transcript-only (cheap); escalate to full video only when a `visual_dependent` flag is set. Tag everything Tier 3 (a creator asserting something is a lead, not proof). Extract *explanatory throughlines and the facts they rest on*, not just allegations.

### 3.2 news-monitor
- **In:** ingestor outputs + RSS feed state.
- **Out:** ranked candidate queue (impact × under-coverage), with new vs follow-up status.
- **Rules:** under-coverage is a selection signal only. Dedupe against already-processed items. Discard "it's suppressed" / unfalsifiable leads.

### 3.3 news-investigator (Claude)
- **In:** one lead.
- **Out:** evidence dossier — every claim bucketed (Fact/Allegation/Inference), sources gathered across the spectrum, the subject's side, open gaps.
- **Rules:** hunt disconfirming evidence as hard as confirming. Pull primary records. Never fill a gap with inference dressed as fact.

### 3.4 source-verifier (Claude; optional Gemini cross-check)
- **In:** the dossier.
- **Out:** per-claim verdicts + story-level **trust score** (see §4).
- **Rules:** re-derive every claim from the original sources; distrust the dossier. Independence test; tier test; primary-record check. Empowered to **Kill**.

### 3.5 article-writer (Claude) — *stance dial applies here*
- **In:** a Pass dossier + verification report.
- **Out:** original draft article: own synthesis, own sourcing, the originating channel **credited** as the lead, AI-authorship disclosure included.
- **Rules:** build from verified facts only. Allegations stay attributed + denied. Inference flagged as interpretation. Represent the strongest counter-case. **No re-voicing** of the source script. Tone/framing follow the chosen stance.

### 3.6 editorial-reviewer (Claude)
- **In:** the draft.
- **Out:** publish-readiness verdict (Ready / Fix / Hold / Kill) + required edits + legal flag + confidence label.
- **Rules:** facts are assumed checked; this stage guards **nuance, framing, symmetry, and legal safety.** Prime directive: preserve complexity; don't let a clean narrative bury a complicating truth.

### 3.7 publisher (human-triggered)
- **In:** a human-approved article.
- **Out:** a post to the Telegram channel + a write to the published log.
- **Rules:** runs **only** on explicit human approval, on the human's credentials. Attaches sources, confidence label, AI-disclosure, and a correction/contact line.

---

## 4. The trust score (the gate logic)

Avoid a fake single number that implies false precision. The score is a **categorical gate** derived from the verifier's per-claim verdicts, with an optional 0–100 triage number layered on top.

### Inputs
For each claim the verifier returns: `Verified | Allegation-only | Unverified | Failed`, plus the number of *independent* sources and the tier of the best source.

### Identify load-bearing claims
The claims the article's core actually depends on. Decorative or background claims don't gate; load-bearing ones do.

### Gate rules
- Any load-bearing claim **Failed** → **KILL.**
- Any load-bearing claim **Unverified** → **HOLD** (needs more sourcing before it can move).
- **Single-source guard:** if the originating channel is the *only* source for a load-bearing claim → that claim is **Unverified** by definition → **HOLD.**
- All load-bearing claims **Verified** (each ≥2 independent sources; ≥1 primary/Tier-1 where the claim is consequential), allegations properly attributed-and-denied and not the sole basis → **PASS.**

### Framing check (separate, runs at PASS)
A PASS on facts is *not* permission to publish the argument. The throughline must additionally:
- not be contradicted by any Unverified/Failed fact that was cut,
- fairly state the strongest counter-case,
- be labelled as interpretation, not fact.
If framing fails, it's a **Fix** at the editorial stage even though the facts passed.

### Worked example
A video claims: (a) a public asset was transferred to a private operator; (b) at one-third its value; (c) "part of a privatisation agenda."
- (a) **Verified** — government order is a primary record. ✓
- (b) **Unverified** — only the source asserts the valuation; no independent valuation exists. → **HOLD** until corroborated, or downgrade to attributed allegation.
- (c) **Inference** — a framing claim, not a fact; can appear only as clearly-labelled interpretation, and only if (a)/(b) hold.

Result: **HOLD.** The transfer is real and explainable; the "one-third value" cannot be asserted; the "agenda" is interpretation. An honest article waits for the valuation or reframes.

---

## 5. Data model

Core entities and their links:

- **Source** — a channel/account. (id, name, platform, rss_url, default_tier=3, stance_note)
- **Item** — one ingested post/video. (id, source_id, url, published_at, transcript, processed_at, dedupe_hash)
- **Claim** — one extracted assertion. (id, item_id, text, timestamp, bucket, video_cited_source)
- **VerificationResult** — per claim. (id, claim_id, verdict, independent_source_count, best_tier, evidence_links[], checked_by_model)
- **Story** — a candidate/draft. (id, item_id, trust_gate, framing_status, draft_text, credit_source_id, ai_disclosure)
- **ReviewDecision** — the human's call. (id, story_id, decision, edits, reviewer, decided_at)
- **Publication** — a live post. (id, story_id, channel_msg_id, published_at, confidence_label)
- **Correction** — (id, publication_id, issue, fix, corrected_at)
- **Grievance** — compliance inbox. (id, publication_id, complainant, complaint, status, resolved_at, due_at = received + 15 days)

The chain `Source → Item → Claim → VerificationResult → Story → ReviewDecision → Publication` is your **audit trail** — it's both an editorial safeguard and your legal/compliance evidence.

---

## 6. Infrastructure & systems design

### Components
- **RSS poller** — watches each Source's feed on a schedule; emits "new item" events.
- **Ingestion worker** — calls Gemini; transcript-first, full-video on demand; writes to raw store.
- **Orchestrator** — drives the stage sequence. Options: a workflow engine (Temporal / n8n), or a simpler queue + cron, or a Claude Cowork/Routine for the reasoning stages. Pick based on your comfort; n8n is a reasonable middle ground for this scale.
- **Reasoning workers** — Claude calls for investigate / verify / write / review.
- **Stores** — raw store (transcripts, extracts), a database for the entities in §5, a draft store.
- **Review queue interface** — where drafts land for you: a private Telegram "drafts" chat, a Slack channel, or a thin web page. Must show the draft + trust report + per-claim verdicts + flags.
- **Telegram bot** — publish action; human-triggered.
- **Compliance stores** — published log, corrections log, grievance inbox.
- **Secrets manager** — API keys and the bot token. The publish credential is segregated so only a human action releases it.

### Orchestration behavior
- **Event-driven** for new items (RSS → ingest → pipeline).
- **Scheduled sweeps** for back-catalog triage and periodic re-checks of held stories.
- **Idempotency:** dedupe items by hash; never reprocess the same video; dedupe claims so a recurring talking point isn't counted as new corroboration.
- **Retries:** exponential backoff on API/network failures; dead-letter queue for items that fail repeatedly, surfaced to you.
- **Rate-awareness:** respect Gemini's free-tier ~8 hours/day video cap; queue overflow to the next day or escalate to paid.

### Cost controls (ingestion is the expensive part)
- Transcript-first by default; full video (~300 tokens/sec) only when `visual_dependent`.
- Cache transcripts and verification results; never re-verify an unchanged claim.
- Per-stage token budgets; a daily spend cap with alerting.
- Back-catalog: triage by title/topic first, ingest selectively — do **not** brute-force every second of every video on day one.

### Observability & audit
- Structured logs at each stage; every published claim traceable end-to-end (source+timestamp → verification sources → verdict → approver → publish time).
- Metrics: leads in → verified → published funnel; kill/hold rates; correction rate; cost per published article; time-in-queue at the human gate.

---

## 7. The human gate

What you see per story: the draft, the trust gate result, the per-claim verdict table, the framing/nuance flags, the legal flag, and the source credit. What you can do: **Approve**, **Edit-then-approve**, **Send back** (with a note to a stage), or **Kill**. Nothing reaches the channel without an explicit Approve.

Design for sustainability: you are a single point of failure and the most likely bottleneck. Keep volume low enough that every gate decision gets real attention — a flooded queue rubber-stamped is the same as no gate. Better five solid pieces a week than fifty skimmed.

---

## 8. Legal & compliance (India)

*Not legal advice. Get a media lawyer's review before going public.*

- **IT Rules 2021 — Digital Media Ethics Code (Part III).** Applies to publishers of news and current-affairs content: requires adherence to journalistic-conduct norms and a **grievance-redressal mechanism with a 15-day resolution window** and a three-tier escalation path. Build the grievance inbox and a published grievance officer/contact from the start.
- **Feb 2026 amendment — synthetic/AI content.** Mandates **prominent labelling and traceable metadata for AI-generated content.** Your articles are AI-written, so attach a clear AI-authorship/assistance disclosure to every post. (Routine editing/transcription is excluded, but disclosure is the safe, aligned default.)
- **Draft Second Amendment 2026.** Would extend ethics-code and blocking obligations to **individual creators and news-sharing accounts**, with takedown windows compressed to ~3 hours. Emerging, contested, under consultation — but a Kerala news channel is in the target zone. Architect for **fast takedown/correction** so a 3-hour window is operationally feasible.
- **Defamation.** Now under the Bharatiya Nyaya Sanhita (2023, replacing the IPC) plus civil exposure. The verifier's named-person rule and the editorial-reviewer's legal flag are your front-line defense; truth + attribution + right-of-reply are the substantive protections.
- **Copyright / IP.** The "build, don't re-voice" rule is a legal necessity, not just an editorial one — reworded transcripts risk infringement. Original synthesis + credit + linking is the safe pattern.
- **DPDP Act 2023.** If you store personal data (e.g., of complainants), mind retention and erasure obligations.

---

## 9. Risk register

| # | Risk | Mitigation |
|---|------|-----------|
| 1 | Publishing a false claim | Two-independent-source gate; primary-record check; human gate; visible corrections |
| 2 | Defamation of a named person | Named-person rule; attribution + denial; editorial legal flag; lawyer pre-review |
| 3 | Source-echo false corroboration | Independence test — same owner/wire/lean ≠ independent |
| 4 | Oversimplification / loaded framing | Facts-vs-framing split; reviewer nuance directive; "keep it complex" |
| 5 | Re-voicing a source (IP + credibility) | Build-don't-re-voice rule; original synthesis; credit + link |
| 6 | Model hallucinating a citation | Verifier re-checks every source link; optional cross-model check |
| 7 | Lean creep despite stated neutrality | Monthly symmetry test; publish stories inconvenient to your own side |
| 8 | Single-source capture (channel = only source) | Single-source guard → auto-HOLD |
| 9 | Automation drift / gate erosion | Hard human gate; low volume; queue-time metric |
| 10 | Cost blowup on ingestion | Transcript-first; caching; daily cap; selective back-catalog |
| 11 | Regulatory takedown (3-hr window) | Takedown-ready infra; grievance inbox; AI-label; lawyer on call |
| 12 | Human bottleneck / burnout | Cap throughput; batch reviews; consider a second reviewer before scaling |

---

## 10. Failure-mode handling

- **Sources conflict:** don't average them — surface the conflict in the dossier; the claim is at best Allegation-only until resolved.
- **Only source is the channel:** auto-HOLD; may still be written as "X reports; not independently confirmed," never as fact.
- **Ingestion fails / rate-limited:** retry with backoff; defer to next day's quota; dead-letter to you.
- **Human unavailable:** stories wait in queue indefinitely — that's correct behavior, not a bug.
- **Error found post-publish:** correction on the post itself, logged, fast; never a silent edit.
- **Takedown/grievance received:** triage immediately; correct or remove within the regulatory window; log resolution.

---

## 11. Phased rollout

Each phase has a **gate to proceed** — don't advance until it's met.

- **Phase 0 — Foundations.** Finalize the charter; decide the stance dial; pick 1–2 starting sources; get a legal read. *Gate: charter signed off, stance chosen.*
- **Phase 1 — Manual dry runs.** No automation. Hand-run real stories through the stages. *Gate: the verifier reliably catches weak claims and the reviewer catches loaded framing on live examples.*
- **Phase 2 — Assisted.** Automate ingestion + verification; drafts land in your review queue; you publish manually. *Gate: a week of drafts where your edits are minor and no false claim slips through.*
- **Phase 3 — Scheduled.** Routine runs the chain on new RSS items + back-catalog triage; still human-gated publish. *Gate: stable cost, low correction rate, sustainable queue volume.*
- **Phase 4 — Scale.** Add sources; extend to India; consider a second reviewer. *Gate: throughput sustainable without gate erosion.*

---

## 12. Open decisions (parking lot)

1. **Stance dial** — neutral explainer vs transparent perspective. *(Blocks the writer.)*
2. **Starting sources** — which 1–2 channels first.
3. **Gemini tier** — free (8 hr/day cap) vs paid.
4. **Orchestrator** — workflow engine vs queue+cron vs Cowork routine.
5. **Hosting** — where the workers and stores run.
6. **Channel shape** — Telegram channel vs group; public vs invite.
7. **Reviewer capacity** — solo, or recruit a second human gate before scaling.

---

*Build order, when you're ready: source-ingestor → wire RSS monitoring → trust-score logic into the verifier → article-writer (after the stance decision) → publisher + compliance stores. Validate each against Phase 1 dry runs before automating it.*
