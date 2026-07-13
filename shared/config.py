import os
from pathlib import Path

# --- Model API keys (pipeline runs on Gemini + Claude only) ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")

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

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Anil's private chat with the bot (for draft review)
TELEGRAM_DRAFT_CHAT_ID = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "")
# The public channel (@thelivu or numeric ID)
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
# Contact handle that fills the "[contact]" placeholder in the published footer
# (corrections / grievances). Override via env; defaults to the owner's handle.
CONTACT_HANDLE = os.environ.get("CONTACT_HANDLE", "@Blazedddddd")

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
CLAUDE_MODEL    = "claude-sonnet-4-6"
GEMINI_MODEL    = "gemini-2.5-flash"
# Stronger Gemini for the highest-stakes search-grounded stage (the trust gate).
GEMINI_PRO_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-2.5-pro")

# --- Paths ---
REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "engine" / "skills"
SOURCES_YAML = REPO_ROOT / "engine" / "sources.yaml"
WATCHLIST_YAML = REPO_ROOT / "engine" / "watchlist.yaml"
ARTICLES_DIR = REPO_ROOT / "articles"
DRY_RUN_LOG = REPO_ROOT / "engine" / "dry-run-log.md"
