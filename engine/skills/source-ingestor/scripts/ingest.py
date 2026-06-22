#!/usr/bin/env python3
"""
source-ingestor — reference implementation.

Reads a source's RSS feed, and for each new video produces the structured
Tier-3 lead artifact defined in SKILL.md.

Design:
  1. Transcript-first (cheap, no video tokens) via youtube-transcript-api.
     Claims are then extracted from the transcript text with Claude.
  2. Falls back to Gemini native video understanding only when there is no
     transcript or the story is visual (visual_dependent=True).

This is a STARTING POINT, not production code. It has no real persistence
(swap the seen-set for your database), minimal error handling, and the model
ids should be confirmed against current docs before you run it:
  - Gemini video:  https://ai.google.dev/gemini-api/docs/video-understanding
  - Claude:        https://docs.claude.com

Dependencies:
  pip install feedparser youtube-transcript-api google-genai anthropic

Environment:
  export GEMINI_API_KEY=...      # Gemini API (NOT the consumer app plan)
  export ANTHROPIC_API_KEY=...
"""

import os
import json
import re
import feedparser

# ----- configuration -------------------------------------------------------

# FYI by Creator House — the first real source.
FYI_CHANNEL_ID = "UCPDF2ztiEnkUx2Lv7ud6Khw"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={FYI_CHANNEL_ID}"
SOURCE_NAME = "FYI by Creator House"

# Confirm current model ids before running — names change.
GEMINI_MODEL = "gemini-2.5-flash"        # video understanding
CLAUDE_MODEL = "claude-sonnet-4-6"       # claim extraction from transcript

# Replace with a real persisted store (DB table keyed by video_id).
SEEN_VIDEO_IDS: set[str] = set()


# ----- helpers -------------------------------------------------------------

def video_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else url


def get_transcript(video_id: str) -> str | None:
    """Cheap path: pull the transcript without touching the video itself."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        chunks = YouTubeTranscriptApi.get_transcript(video_id)
        # Keep timestamps so claims can be located later.
        return "\n".join(f"[{int(c['start'])//60:02d}:{int(c['start'])%60:02d}] {c['text']}"
                         for c in chunks)
    except Exception as e:
        print(f"  no transcript ({e}); will consider Gemini video fallback")
        return None


CLAIM_EXTRACTION_PROMPT = """You are the ingestion stage of a news pipeline.
Below is a timestamped transcript of a video from a single source.

Extract, faithfully and WITHOUT endorsing or improving:
1. throughline: the video's central explanatory argument, 1-2 sentences,
   phrased as the SOURCE's claim ("The source argues that ...").
2. claims: each discrete factual assertion, with its [MM:SS] timestamp, a
   PROVISIONAL bucket (fact | allegation | inference), and any source the
   video itself cites for it (or null).

Do not resolve ambiguity, add outside context, or verify anything. Return
ONLY JSON: {"throughline": "...", "claims": [{"text","timestamp",
"provisional_bucket","video_cited_source"}]}

TRANSCRIPT:
"""


def extract_claims_from_transcript(transcript: str) -> dict:
    """Reasoning path: Claude turns transcript text into the claim structure."""
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": CLAIM_EXTRACTION_PROMPT + transcript}],
    )
    text = resp.content[0].text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return json.loads(text)


def ingest_via_gemini_video(video_url: str) -> dict:
    """Expensive path: Gemini natively processes the video (visuals + audio).

    Use only when there is no transcript or the story is visual. Public
    videos only; one video per request on older models. ~300 tokens/sec.
    """
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = (CLAIM_EXTRACTION_PROMPT.replace("a timestamped transcript", "this video")
              + "\nAlso return notable_visuals: any on-screen documents, figures, or "
                "footage that carry meaning the audio alone does not.")
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=video_url)),
            types.Part(text=prompt),   # text goes AFTER the video part
        ]),
    )
    text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return json.loads(text)


def ingest_item(entry, visual_dependent: bool = False) -> dict:
    video_url = entry.link
    vid = video_id_from_url(video_url)
    print(f"Ingesting {vid} — {entry.title}")

    transcript = None if visual_dependent else get_transcript(vid)

    if transcript:
        extracted = extract_claims_from_transcript(transcript)
        method = "transcript"
        visuals = []
    else:
        extracted = ingest_via_gemini_video(video_url)
        method = "gemini_video"
        visual_dependent = True
        visuals = extracted.get("notable_visuals", [])
        transcript = extracted.get("transcript", "")

    return {
        "source": SOURCE_NAME,
        "source_tier": 3,                 # always a lead, never proof
        "platform": "youtube",
        "video_url": video_url,
        "video_id": vid,
        "published_at": getattr(entry, "published", None),
        "ingest_method": method,
        "visual_dependent": visual_dependent,
        "throughline": extracted.get("throughline", ""),
        "claims": extracted.get("claims", []),
        "notable_visuals": visuals,
        "transcript": transcript or "",
    }


# ----- main loop -----------------------------------------------------------

def run_once():
    feed = feedparser.parse(RSS_URL)
    new_items = [e for e in feed.entries if video_id_from_url(e.link) not in SEEN_VIDEO_IDS]
    print(f"{len(new_items)} new item(s) in feed for {SOURCE_NAME}")

    for entry in new_items:
        try:
            artifact = ingest_item(entry)
            SEEN_VIDEO_IDS.add(artifact["video_id"])
            # Hand off to news-monitor / news-investigator. For the dry run,
            # just print it.
            print(json.dumps(artifact, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"  FAILED to ingest {entry.link}: {e}")
            # dead-letter for human review rather than dropping silently


if __name__ == "__main__":
    run_once()
