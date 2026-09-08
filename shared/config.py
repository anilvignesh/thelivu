import os
from pathlib import Path

# --- Model API keys ---
# Journalism/research runs on Gemini + Claude ONLY (no compromise). NVIDIA-hosted
# Gemma is used exclusively for the PRESENTATION side (carousel + video) — see
# skill_runner._NVIDIA_SKILLS.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
# NVIDIA build.nvidia.com — free hosted Gemma 4, OpenAI-compatible. Presentation only.
NVIDIA_API_KEY  = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_MODEL    = os.environ.get("NVIDIA_MODEL", "google/gemma-4-31b-it")
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# --- YouTube (Data API v3, Shorts upload) ---
# OAuth client (Desktop app type) + a refresh token minted once via the one-time
# consent flow (publishing/youtube_auth.py) — the channel is whichever Google
# account did that consent (the Thelivu Gmail). Leave blank until set; youtube.py
# raises YouTubeNotConfigured so callers degrade gracefully, same pattern as IG.
YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

# --- Instagram (graph.instagram.com, Content Publishing) ---
# IG_USER_ID: the Instagram professional account's numeric id. IG_ACCESS_TOKEN:
# a token issued via the "Instagram API with Instagram Login" flow, scoped
# with instagram_business_basic + instagram_business_content_publish. Leave
# blank until the Meta app is set up — slide approval degrades to "saved,
# post it yourself" until both are present.
IG_USER_ID      = os.environ.get("IG_USER_ID", "")
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")

# --- Slide file server (thelivu-agent only) ---
# Public base URL the thelivu-agent service is reachable at (Railway →
# thelivu-agent → Settings → Networking → Generate Domain). Rendered slide
# PNGs are served from here so Instagram's image_url fetch never needs a
# third-party host or an embedded secret. Port defaults to Railway's
# convention of injecting PORT for services with public networking enabled.
SLIDE_SERVER_BASE_URL = os.environ.get("SLIDE_SERVER_BASE_URL", "")
SLIDE_SERVER_PORT = int(os.environ.get("PORT", "8080"))

# --- Reels ---
# How the reel's video-script (a POST-GATE model step — the article is already
# verified + human-approved, so this never touches the trust gate) is produced:
#   "api"      — call the Claude API (Haiku 4.5; video-script is in _HAIKU_SKILLS).
#                ACTIVE default since 2026-09-08. The quota breaker guards it, so a
#                dry Claude budget now blocks reel builds — accepted deliberately.
#   "nvidia"   — free hosted model via NVIDIA (NVIDIA_API_KEY). No Anthropic/Gemini
#                credit, independent of the quota breaker, runs anywhere incl. the
#                dashboard. Was the default 2026-07-26 .. 2026-09-08.
#   "attended" — hand it to the human-driven terminal session (./attend reel <id>);
#                no API. Use when you want a human writing the script.
# Why the default moved (2026-09-08, Anil's call): the free script model was a small
# REASONING model whose deliberation bled into the output — measured 6/6 captions
# leaked on run #186, the cut that reached Instagram, and its leak-free rebuild was
# still an unusable 2-beat 8.4s fragment. Haiku: 0/5 leaked at ~$0.0095/reel. Five
# incidents (2026-08-26 .. 09-08) were all this one cause. Full note in
# engine/agents/skill_runner.py::_HAIKU_SKILLS and docs/mistakes.md.
# Either engine is charter-safe here: this is a POST-GATE step, not the silent
# trust-gate fallback the charter forbids. NVIDIA model overridable via
# NVIDIA_SCRIPT_MODEL; set THELIVU_REEL_MODE=nvidia to roll back.
REEL_MODE = os.environ.get("THELIVU_REEL_MODE", "api").strip().lower()

# Publishing behaviour — reels are the reach default; carousels are OPTIONAL, made
# on demand only for the stories where the receipts are the story (owner's call,
# 2026-07-26). So publishing no longer auto-queues a carousel. Flip to "1"/"true" to
# restore the old auto-carousel-on-every-publish behaviour.
AUTO_CAROUSEL_ON_PUBLISH = os.environ.get(
    "THELIVU_AUTO_CAROUSEL", "false").strip().lower() in ("1", "true", "yes")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Anil's private chat with the bot (for draft review)
TELEGRAM_DRAFT_CHAT_ID = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "")
# The public channel (@thelivu or numeric ID)
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
# Contact handle that fills the "[contact]" placeholder in the published footer
# (corrections / grievances). Override via env; defaults to the owner's handle.
CONTACT_HANDLE = os.environ.get("CONTACT_HANDLE", "@Blazedddddd")
# Public join link for the channel (https://t.me/<handle>), shown as a permanent
# button at the top of the bio page. Blank until the channel has a public
# @username — the numeric TELEGRAM_CHANNEL_ID is not a linkable URL.
CHANNEL_PUBLIC_URL = os.environ.get("CHANNEL_PUBLIC_URL", "")

# --- Optional web search ---
# Leave blank to use DuckDuckGo (free, no key). Set to use Brave Search.
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

# --- Storage ---
DB_PATH = os.environ.get("DB_PATH", "thelivu.db")

# --- Approval mode ---
# "telegram" : send draft to Telegram bot for approve/kill/hold (production)
# "file"     : save draft to articles/drafts/ and log to dry-run-log (ban period / local)
APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "file")

# --- Orchestrator polling interval ---
CHECK_INTERVAL_HOURS = int(os.environ.get("CHECK_INTERVAL_HOURS", "6"))

# --- Models ---
# Env-overridable so a routing change is a Railway variable, not a code push
# (the tech steward's recommendations apply this way).
CLAUDE_MODEL    = os.environ.get("THELIVU_CLAUDE_MODEL", "claude-sonnet-4-6")
# Triage/selection/gating runs here — same Claude family, ~1/3 the price.
# Journalism (writing, editorial, verification) never routes to it.
HAIKU_MODEL     = os.environ.get("THELIVU_HAIKU_MODEL", "claude-haiku-4-5")
GEMINI_MODEL    = os.environ.get("THELIVU_GEMINI_MODEL", "gemini-2.5-flash")
# Stronger Gemini for the highest-stakes search-grounded stage (the trust gate).
GEMINI_PRO_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-2.5-pro")

# --- Paths ---
REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "engine" / "skills"
# Second-desk skills live under their own root, one directory per desk:
# engine/desks/<desk>/skills/<skill>/SKILL.md. The news desk keeps SKILLS_DIR
# unprefixed so nothing about it moves. See docs/everyone-knows-desk.md.
DESKS_DIR = REPO_ROOT / "engine" / "desks"
SOURCES_YAML = REPO_ROOT / "engine" / "sources.yaml"
WATCHLIST_YAML = REPO_ROOT / "engine" / "watchlist.yaml"
ARTICLES_DIR = REPO_ROOT / "articles"
DRY_RUN_LOG = REPO_ROOT / "engine" / "dry-run-log.md"
