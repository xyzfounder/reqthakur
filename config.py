import os
import sys
import logging
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("reqbot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("REQBOT")

# API credentials
API_ID_RAW = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    API_ID = int(API_ID_RAW) if API_ID_RAW else 0
except ValueError:
    API_ID = 0

# Owner ID & Admins
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
try:
    OWNER_ID = int(OWNER_ID_RAW) if OWNER_ID_RAW else 0
except ValueError:
    OWNER_ID = 0

SUDO_USERS = [OWNER_ID] if OWNER_ID else []

# Database
MONGO_URI = os.getenv("MONGO_URI", "").strip()
SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "reqbot.db")

# Optional Log Channel
LOG_CHANNEL_RAW = os.getenv("LOG_CHANNEL", "").strip()
try:
    LOG_CHANNEL = int(LOG_CHANNEL_RAW) if LOG_CHANNEL_RAW else None
except ValueError:
    LOG_CHANNEL = None

# Default Welcome Message sent to accepted users in DM
DEFAULT_WELCOME_MSG = os.getenv(
    "DEFAULT_WELCOME_MSG",
    "👋 Hello {mention}!\n\n🎉 Your request to join **{chat_title}** has been approved!\nWelcome aboard! 🚀"
).replace("\\n", "\n")
