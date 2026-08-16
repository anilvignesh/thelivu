---
name: social-desk
description: Thelivu's eyes on social media — scans credible fact-checkers, journalists and channels for leads, extracts claims from YouTube reporting, and helps verify (or kill) viral footage — using safe, zero-config tools only (YouTube/web/RSS/read-only X via Nitter, all via engine/social_desk.py). Never account-scrapes X/Reddit/IG, never stores credentials. A judgment task; routes to the best model (Claude/attended), never a presentation model.
---

# Social Desk (the go-to for social)

Modern journalism can't ignore social — that's where a lot of stories break, where genuine fact-checkers debunk viral claims, and where credible independent journalists report from the ground. This desk taps that, **on Thelivu's terms**: social is a **lead** surface, and — from *identified, track-record* sources — a **corroboration** surface. It is never, by itself, the trust gate.

Enforces the charter (`../../CHARTER.md`). Read it; it governs any conflict.

## The one rule that keeps this honest
**Source credibility, not the platform, sets the tier.** A verified fact-checker (BOOM, AFP Fact Check, Newschecker) or an identified journalist with a reporting record is a real source. An anonymous/viral account is **lead-generation only, Tier 4, never proof**. And for *anyone* — social or legacy — a **load-bearing fact still gets checked against the primary record**. This desk fetches and surfaces; the trust gate still decides.

## What it does
1. **Lead scan** — watch the credible social candidates in `engine/sources.yaml` (fact-checkers, investigative desks, credible journalists; Kerala > India > world, impact-weighted, no trivia). Surface what's breaking or being debunked that the mainstream is under-covering.
2. **Claim extraction** — pull the transcript of a credible journalism YouTube video and extract its factual claims (with the source), as leads to verify — never as verified facts.
3. **Viral-footage verification** — when a photo/video claim is circulating, use the OSINT accounts (GeoConfirmed, Bellingcat, Benjamin Strick/CIR) and primary sources to establish where/when it actually happened — or to KILL it if it's miscaptioned/old/AI. This protects Thelivu from amplifying a fake.
4. **Blocked-page read** — clean-read pages our normal fetcher gets 403 on (Deccan Herald, Business Standard, ANI) via Jina Reader.

## Tools (safe subset only — `engine/social_desk.py`)
- `youtube_search(query, n)` · `channel_latest(handle, n)` · `youtube_transcript(video)` — via yt-dlp
- `web_read(url)` — clean text via Jina Reader (public, no key)
- `rss_latest(feed, n)` — via feedparser
- `x_timeline(handle, n)` · `x_search(query, n)` — recent public X/Twitter posts, **read-only, via a public Nitter RSS bridge**. No account, no cookies, no login — added 2026-07-28 after missing the Bareilly assault story (it broke on X and we had no way to read it). `x_search` is unreliable — most public bridges don't serve search RSS; prefer `x_timeline` on named handles.

CLI: `venv/bin/python -m engine.social_desk {yt-search|yt-channel|yt-transcript|web|rss|x|x-search} ...`

**⚠️ Bridge reality (owner-tested 2026-08-15):** public Nitter instances rot fast and were largely unreachable as of this date (bot-challenge walls, redirects, 403s) — X has kept tightening access. `x_timeline`/`x_search` **raise loudly** rather than return empty when every bridge fails — treat that as "no X visibility today," not "nothing happened." Never paper over a bridge failure as a quiet news day.

- `reddit_subreddit_latest(subreddit, n, sort)` · `reddit_search(query, subreddit, n)` — Reddit posts, **read-only via reddit.com's public Atom feeds** (`/r/<sub>/.rss`, `/search.rss`). No app, no registration, no account — tried PRAW's official app-only OAuth first (2026-08-16) but Reddit has gated new "script app" registration behind a "valid moderation use case" request; the plain-RSS path needs none of that. Reddit does 403 the default Python UA and 429s on rapid repeated calls, so it sends a real User-Agent and expects callers to space requests out.

CLI adds: `reddit <subreddit>` · `reddit-search <query> [--subreddit ...]`

**Still deliberately NOT available: Instagram/Facebook account-scraping, or any credential-based X access (login, cookies, session replay — e.g. Twikit-style tools).** Those aren't just an account-suspension risk to manage — they're automated access that circumvents the platform's own ToS by design (accessing internal/private APIs outside the approved channel), the same category of problem as running an unattended process against a subscription instead of a real API. A burner account doesn't fix that, it just moves the consequence off the owner. agent-reach was evaluated twice (2026-07-26, 2026-08-15) and declined both times, on top of that, for storing authenticated cookies next to the Instagram publish token and prod DB URL. If X/IG coverage matters enough, the legitimate paths are: (a) the owner personally reads and hands in a lead via `./attend topic`, or (b) X's official paid API.

## Output (structured)
```
LEADS: <bullet list — each: the claim/story, the social source + handle, why it matters
        (impact + under-coverage), and its tier (verification-grade vs lead-only)>
VERIFY: <for any viral claim checked — VERIFIED / MISLEADING / FALSE / UNCONFIRMED,
         with the primary-record or OSINT basis and the source URL>
FOR THE GATE: <the 1-3 strongest leads worth a full investigation, and what primary
               record would confirm them>
```
Never present a social claim as fact. Attribute everything. Prefer to KILL a shaky viral claim than pass it on. Permission to find nothing.
