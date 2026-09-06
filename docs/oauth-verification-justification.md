# YouTube Data API scope justification — for Google's OAuth verification submission

*Paste this into the scope-justification field(s) when submitting the OAuth
consent screen for review. Written 2026-09-07.*

---

## `https://www.googleapis.com/auth/youtube.upload`

Thelivu is an independent news publication (https://thelivu.up.railway.app)
that produces short video explainers ("reels") alongside its written
articles. This scope is used exclusively to upload these self-produced
videos to Thelivu's own YouTube channel as a cross-post distribution
channel, identical in purpose to our existing Instagram distribution.

The integration is single-purpose and single-account: it authenticates once
as the Thelivu channel's own Google account and uploads only videos we
ourselves author. It is never used to act on behalf of, or access data
belonging to, any other YouTube channel, creator, or viewer. There is no
end-user-facing OAuth flow — no third party ever grants this app access to
their own channel.

A narrower scope is not available for this use case: uploading a video via
the YouTube Data API requires `youtube.upload`; there is no more limited
scope that permits publishing new video content.

## `https://www.googleapis.com/auth/youtube.readonly`

Used solely to read back basic public statistics (view count, like count)
on videos this same app has already uploaded to the Thelivu channel, for
our own internal editorial reporting on which stories perform well as
video. It does not read private account data, subscriber lists, or any
data belonging to other channels or users.

A narrower scope is not available: read access to a channel's own upload
statistics via the API requires `youtube.readonly`.

---

## If asked for more detail on the app itself

Thelivu publishes verification-first, transparent-perspective news
articles, primarily India-focused with Kerala emphasis. The video reels
this scope uploads are short (under 60s) narrated summaries of articles
already published on the site, in the same editorial voice — not
user-generated content, not repurposed third-party media.
