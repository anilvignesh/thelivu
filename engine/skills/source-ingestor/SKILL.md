---
name: source-ingestor
description: Ingest a video or post from a trusted source (YouTube channel, Instagram) and turn it into a structured, Tier-3 lead artifact — a transcript plus extracted claims with timestamps, the explanatory throughline, and any sources the post itself cites. Use this whenever a new item arrives from a watched source feed, when backfilling a channel's back catalog, or when the user wants to "ingest", "pull in", or "process" a video/post into the pipeline. It is the engine's entry point for a watched feed (the ingestion step of the curated-channels lead source) and produces a lead, never a verified finding.
---

# Source Ingestor

This is the **ingestion step** for the curated-channels lead source — the engine's entry point for a watched feed. It converts a source post into a structured lead for the rest of the pipeline. It does not verify, judge, or write — it only extracts, faithfully, and tags the result as what it is: one source's claims.

This skill enforces the project's editorial charter (`../../CHARTER.md`). Read it if present; the charter governs in any conflict.

## The two rules that matter most

1. **Everything out of here is Tier 3 — a lead, not proof.** A creator asserting something is the beginning of an investigation, never the end of one. Tag every claim accordingly. The verifier decides what's true; the ingestor only records what was said.
2. **Extract; do not endorse, summarise-as-fact, or improve.** Capture the claims and the throughline as the source stated them. Do not resolve ambiguities, add context, or smooth the argument. That distortion is exactly what later stages must be able to see and check.

## Cost rule: transcript-first

Ingesting full video through Gemini is expensive (~300 tokens/second) and capped on the free tier (~8 hours/day). So:

1. **Try the transcript first.** Pull the YouTube transcript (no video tokens). If it exists and the story isn't visual, extract claims from the transcript text with Claude.
2. **Escalate to Gemini video only when** there's no transcript, or the signal is visual (an on-screen document, leaked slide, chart, or footage that the words alone don't carry). Set `visual_dependent: true` for those.

This keeps the back catalog affordable and reserves video tokens for the handful of posts that actually need them.

## What to extract

- **transcript** — the spoken content.
- **throughline** — the post's central explanatory argument, in 1–2 sentences, stated as *the source's* claim ("FYI argues that…").
- **claims[]** — discrete assertions, each with a timestamp (MM:SS), a *provisional* bucket (fact / allegation / inference — provisional because the verifier re-derives it), and any source the post itself cites for that claim.
- **notable_visuals[]** — only when `visual_dependent`: on-screen documents, figures, or footage that carry meaning.

## Output format

ALWAYS emit this JSON object:

```json
{
  "source": "FYI by Creator House",
  "source_tier": 3,
  "platform": "youtube",
  "video_url": "https://www.youtube.com/watch?v=...",
  "video_id": "...",
  "published_at": "ISO-8601",
  "ingest_method": "transcript | gemini_video",
  "visual_dependent": false,
  "throughline": "The source argues that ...",
  "claims": [
    {
      "text": "the assertion, as stated in the post",
      "timestamp": "07:42",
      "provisional_bucket": "fact | allegation | inference",
      "video_cited_source": "what the post cites for this, or null"
    }
  ],
  "notable_visuals": [],
  "transcript": "..."
}
```

Hand this object to `news-monitor` (for triage) or directly to `news-investigator`. Never publish, score, or assert any of it as true.

## Reference implementation

`scripts/ingest.py` is a runnable reference: it reads a channel's RSS feed, fetches the transcript (falling back to Gemini video), extracts claims, and prints the artifact above. The FYI feed is wired in as the first source. Verify the current Gemini model id at ai.google.dev before running — model names change.

## Example

Input: a new FYI video on Kerala's electricity tariffs.
Output: the JSON artifact with the throughline ("FYI argues tariffs rose because of X"), each factual claim timestamped and provisionally bucketed, the one statistic the video cited a source for noted, everything tagged `source_tier: 3` — ready for the investigator to verify against the record, and for nothing to be asserted as true until it does.
