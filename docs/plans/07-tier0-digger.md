# 07 — Tier-0 Digger

Status: **shipped and running** (2026-09-10). Implements step 5 of the build order in the vault note
`work/active/Thelivu/Free-Tier Digger Architecture.md`.

Live on `thelivu-digger` as `digger.service`, hourly cycle, 15MB of a 256MB cap.
First production candidates recorded 2026-09-10 08:00 UTC.

## What this is

A lightweight always-on service on the `thelivu-digger` VM that uses **free-tier models via
freellmapi** to do the cheap, high-volume half of investigative work — reading documents and spotting
patterns — so that Claude only ever sees a pre-filtered shortlist.

It is **Tier 0**: a new rung *underneath* Thelivu's existing three model tiers
(`engine/agents/skill_runner.py`). It does not change tiers 1–3.

## The one rule that shapes everything

Established empirically 2026-09-10: of freellmapi's ~40 free providers, **only Google/Gemini has live
search grounding.** Every other free model is frozen at training time and will confidently invent
things if asked "what is currently true".

> **Free models are for reading comprehension over content already fetched — never for recall.**

So the loop always **fetches real bytes first**, then asks a free model to read *that text*. Every
prompt is constrained to the supplied document. A candidate that cannot cite a fetched URL plus the
excerpt it came from is a bug, not a lead.

This is the same failure mode the trust gate already exists to catch (run #223's fabricated ₹1800cr;
the 2026-09-08 video-script Gemma failure, 6/6 caption leaks vs 0/5 on Haiku).

## Deliberately NOT in this step

- **No writing into `pending_topics` / `digs`.** Those tables are live in production on Railway. An
  unproven service does not get to write into the running pipeline on day one. Tier 0 writes to its
  own `digger_candidates` table; promotion happens later, under review.
- No pre-filter (step 6), no batched Claude review (step 7), no Sonnet-vs-Opus call (step 8).
- **No local model inference, ever.** The box is a burstable ⅛-OCPU / 945MB `E2.1.Micro`. It is an
  orchestrator that makes API calls. See the memory traps note — an image pull alone once took the
  whole VM down.

## Where it runs

| | |
|---|---|
| Host | `thelivu-digger` @ 129.225.67.115 (Oracle Linux 8, AMD `E2.1.Micro`) |
| Unit | `digger.service`, `User=opc`, `WorkingDirectory=/opt/thelivu` |
| Model access | freellmapi at `http://127.0.0.1:3001` on the same box (localhost-only) |
| Credential | freellmapi's existing `unified_api_key` (in its `settings` table) |
| Secrets | `/etc/thelivu/digger.env` (root:root 600) — **not** under /home, see SELinux below |
| DB | Railway Postgres via `DATABASE_URL` (= Railway's `DATABASE_PUBLIC_URL`) |
| Memory | `MemoryHigh=192M`, `MemoryMax=256M` — hard cap from day one |

Secrets follow the existing `ops/oracle-vm/deploy-secrets.sh` pattern exactly: pulled from Railway
**on the laptop**, pushed over SSH, so the VM never authenticates to Railway itself.

## The loop

One cycle:

1. **Pick a target** — round-robin over watch targets derived from beat-monitor's source categories,
   so coverage rotates instead of relying on one daily run to cover everything.
2. **Read the index** (RSS/Atom feed or HTML listing) to get candidate document URLs, and drop any
   already recorded for this target. The index is never extracted from — it exists only to choose a
   document. See "what shipped" below for why this step is not optional.
3. **Fetch** the chosen document (HTTP, size-capped, timeout-capped). This is the grounding step.
4. **Extract** — a free model reads *only* the fetched text and returns structured findings.
5. **Cross-check** — a *second, different* free model reads the same text. Disagreement is recorded,
   not silently resolved. Cheap echo of CHARTER.md's "two independent sources" discipline; catches
   extraction slips without needing a strong model.
6. **Record** each finding to `digger_candidates` with source URL, excerpt, retrieval timestamp, both
   models' answers, and an agreement flag.

Never asserts a live fact. Never emits publishable copy — leads only, same as beat-monitor.

## Cost isolation

Tier 0 must **not** intermix with `shared/budget.py` (cap $3/day, for paid Claude/Gemini). Tier 0 is
free-tier by definition and should cost $0, but a free-tier outage or misconfiguration must not
silently trip the budget cap meant for real spend. It keeps its own counters in `digger_runs` and
imports nothing from the budget governor.

## Schema (new, additive)

```sql
CREATE TABLE digger_candidates (
    id, target_key, title, finding, source_url, excerpt,
    model_a, model_b, answer_a, answer_b, agreement,   -- 'agree' | 'differ' | 'single'
    status DEFAULT 'new',                              -- new | prefiltered | promoted | rejected
    fetched_at, created_at
);
CREATE TABLE digger_runs (
    id, target_key, started_at, finished_at, ok,
    docs_fetched, candidates_found, model_calls, error
);
```

Additive only — touches no existing table. Note `pending_topics` **already has** a `source` column
(default `'owner'`), so when step 6 wires promotion in, it needs no migration there.

## Verification for this step

- Unit tests with no network: fetch/extract/cross-check logic against fixtures.
- A real end-to-end cycle on the VM against a live document, inspected by hand.
- `systemd-analyze`/`systemctl` confirming the memory caps are actually applied.
- Confirm host memory stays well clear of the OOM cliff during a cycle.


## What shipped vs. what this doc originally planned

Five things changed once real sources and the real box were involved. Recorded
because each cost time and would cost it again.

1. **An index step had to be added.** The plan had the loop fetch a target URL
   and extract from it. That is wrong for these sources: the RBI press-release
   listing is ~12k characters of navigation chrome with the releases loaded by
   JS, so a model reading it correctly finds nothing. The loop now reads an
   index (feed or HTML listing), picks an unseen document, and extracts from
   **that**. A listing page is not a document.

2. **Models are pinned, not `auto`.** `auto` routed to `nemotron-3-ultra`, a
   reasoning model that returns its chain-of-thought in `content` ("The user
   wants a summary of...") rather than the answer — which fails JSON parsing
   every time, and took 44s on a 6k-char prompt. Measured five candidates and
   pinned `gemini-3.5-flash-lite` (Google, 1.3s) + `command-a` (Cohere, 2.5s),
   two different families, with a fallback to `auto` when either is rate-limited.
   `mistral-small-4` (429), `llama-4-maverick` (503) and `gemma-4-26b-it` (502)
   were all unavailable at the time of measurement — free-tier availability is
   not stable, which is why the fallback exists.

3. **Python 3.11 had to be installed on the VM.** Oracle Linux 8 ships 3.6.8,
   which has no `psycopg2-binary` wheel and falls back to a source build that
   fails outright.

4. **SELinux dictated the layout.** It is Enforcing on this box. Code lives in
   `/opt/thelivu` and secrets in `/etc/thelivu/digger.env`, because systemd runs
   as `init_t` and cannot read an `EnvironmentFile` labelled `user_home_t` — it
   fails the unit with a bare `Permission denied` and no SELinux denial logged.

5. **The two tables had to be created in production by hand.** `init_db()` runs
   on every Railway boot (`run.py:29`) and is idempotent, so the tables would
   have appeared on the next deploy — but the service needed them immediately.
   Applied the two `CREATE TABLE IF NOT EXISTS` statements plus three indexes
   against the live Postgres. Purely additive; no existing table touched.

Also worth knowing: the deploy script originally read the freellmapi key with
inline nested quoting through ssh → sh → docker → sqlite, which silently
mangled a 59-char key into 78 characters and produced an HTTP 401 from a service
that otherwise looked healthy. It now uses a heredoc'd script file and validates
the key's shape (`freellmapi-` + 48 hex) before writing it.

## Verified 2026-09-10

- 33 offline cases pass (`python -m shared.tests.run_digger_cases`), including
  the one that matters most: a finding both models agree on is still rejected if
  its excerpt is not literally in the fetched document.
- `run_budget_cases` still passes — no regression in the budget governor.
- Live: SEBI feed → 30 documents → 4 fetched → 2 grounded candidates written to
  production, each carrying a verbatim excerpt from the real order.
- Dedup confirmed: a second run over the same target skips recorded URLs.
- `systemctl show digger` confirms `MemoryHigh=192M` / `MemoryMax=256M` applied;
  steady state 15MB, host at ~470Mi available.
- Cost: $0. No call touched a paid provider.

## Known gaps (deliberate, not oversights)

- ~~PDFs are not parsed.~~ **Closed 2026-09-10** — parsed via `liteparse`
  (13.8MB manylinux wheel, zero runtime deps, Rust + PDFium). Real CAG PDF:
  0.06s, 35MB peak RSS, 24k chars. `cag-reports` is now a verified target and
  its `.pdf` links are followed. Two caveats kept honest rather than hidden: a
  scanned PDF with no text layer raises a miss naming the reason (OCR is
  disabled on purpose — Tesseract is the memory-hungry path), and a PDF PDFium
  rejects outright reports as a parse failure. Some CAG scans also carry a poor
  embedded OCR layer ("COM PTROLLER & ATJDITOR"), which degrades extraction
  quality but not safety: grounding still matches against that same text.
- **SEBI and CAG indexes are verified.** CAG-local-bodies and MOSPI are in the
  rotation but unverified; a failing cycle is logged and slept off.
- **PIB is disabled.** Its WAF returns 403 to urllib from the VM while curl on
  the same box gets 200 — it fingerprints the client, and browser-like Accept
  headers did not change it. Not worth chasing for the least valuable target on
  the list; `targets.active_targets()` skips it so it does not burn a cycle.
- **RBI has no working feed** — the documented RSS endpoints return zero items,
  and its listing is JS-rendered, so RBI is absent from the rotation despite
  being beat-monitor category #3. A headless browser would fix it and is
  explicitly rejected: Chromium needs more memory than this whole box has
  spare. JS-only sources belong to Tier 1 (Gemini, already search-grounded),
  not here.
- Agreement so far is mostly `differ`, because these SEBI order pages are ~380
  characters and the two models pick different single facts from them. That is
  the cross-check reporting honestly, not a bug — but it means `agree` will only
  become a meaningful signal on longer documents.
