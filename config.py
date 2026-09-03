# MegaBot — env-based configuration (mirrors AniwatchTvdl/config.py style)
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── Telegram ────────────────────────────────────────────────
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

# ─── MongoDB ─────────────────────────────────────────────────
MONGO_URL = os.environ.get("MONGO_URL", "")
MONGO_NAME = os.environ.get("MONGO_NAME", "megabot")

# ─── MEGA account ────────────────────────────────────────────
MEGA_EMAIL = os.environ.get("MEGA_EMAIL", "")
MEGA_PASSWORD = os.environ.get("MEGA_PASSWORD", "")

# ─── Paths & limits ──────────────────────────────────────────
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.getcwd(), "downloads"))
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", 2000))   # TG MTProto upload cap ~2 GB
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", 2))
MAX_JOBS_PER_USER = int(os.environ.get("MAX_JOBS_PER_USER", 1))
MIN_FREE_DISK_MB = int(os.environ.get("MIN_FREE_DISK_MB", 500))
LINK_CACHE_TTL_H = int(os.environ.get("LINK_CACHE_TTL_H", 24))
RETRY_ATTEMPTS = int(os.environ.get("RETRY_ATTEMPTS", 3))
PROGRESS_EDIT_INTERVAL = float(os.environ.get("PROGRESS_EDIT_INTERVAL", 3.0))
MIN_IMAGES_FOR_PDF = int(os.environ.get("MIN_IMAGES_FOR_PDF", 3))
PORT = int(os.environ.get("PORT", 8080))

# ─── Progress bar UI ─────────────────────────────────────────
BAR_LENGTH = 10
BAR_FULL = "▰"
BAR_EMPTY = "▱"

# ─── OpenRouter AI ───────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

PROGRESS_TEMPLATE = os.environ.get("PROGRESS_TEMPLATE", """<blockquote>{bar} <b>{percent}%</b>
📁 <b>{name}</b>
⚡ {speed} • ⏱ {eta}
📦 {current} / {total}</blockquote>""")