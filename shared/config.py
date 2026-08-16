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

# --- Reddit (read-only, engine/social_desk.py) ---
# App-only OAuth via a free "script" app registered at reddit.com/prefs/apps.
# Read-only: never logs in as a user, never posts/votes/comments — so there is
# no account to risk, unlike the X/IG readers. Leave blank until registered;
# reddit_* functions in social_desk.py raise clearly rather than going quiet.
REDDIT_CLIENT_ID     = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = os.environ.get("REDDIT_USER_AGENT", "thelivu-social-desk/1.0 (read-only)")

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
#   "nvidia"   — free hosted Gemma 4 via NVIDIA (NVIDIA_API_KEY). No Anthropic/Gemini
#                credit, independent of the quota breaker, runs anywhere incl. the
#                dashboard. ACTIVE default (2026-07-26): reels without Claude credit.
#   "attended" — hand it to the human-driven terminal session (./attend reel <id>);
#                no API. Use when you want a human writing the script.
#   "api"      — call the Claude API directly. KEPT but INACTIVE — flip to re-enable.
# NVIDIA is a deliberate engine choice for a post-gate step, NOT the silent trust-gate
# fallback the charter forbids. Model id overridable via NVIDIA_SCRIPT_MODEL.
REEL_MODE = os.environ.get("THELIVU_REEL_MODE", "nvidia").strip().lower()

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
