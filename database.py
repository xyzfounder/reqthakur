"""
database.py — Pure MongoDB backend via motor (async).
No SQLite. MONGO_URI must be set in .env / config.
"""

import sys
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import config

# ---------------------------------------------------------------------------
# Connection bootstrap — crash fast if MONGO_URI is absent
# ---------------------------------------------------------------------------
if not config.MONGO_URI:
    config.logger.critical(
        "MONGO_URI is not set in your .env file. "
        "Database cannot start. Please add MONGO_URI and restart."
    )
    sys.exit(1)

try:
    _mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(
        config.MONGO_URI,
        serverSelectionTimeoutMS=10_000,
    )
    mongo_db = _mongo_client["reqbot_database"]
    config.logger.info("MongoDB client created successfully.")
except Exception as _exc:
    config.logger.critical(f"Failed to create MongoDB client: {_exc}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# init_db — create indexes for performance
# ---------------------------------------------------------------------------

async def init_db():
    """Creates MongoDB indexes. Called once at bot startup."""
    try:
        # users collection
        await mongo_db.users.create_index("user_id", unique=True, background=True)
        await mongo_db.users.create_index("joined_at", background=True)

        # chats collection
        await mongo_db.chats.create_index("chat_id", unique=True, background=True)

        # stats collection
        await mongo_db.stats.create_index("key", unique=True, background=True)

        # global_settings collection
        await mongo_db.global_settings.create_index("key", unique=True, background=True)

        # Seed default stats counters (upsert — won't overwrite existing values)
        for stat_key in ("requests_approved", "dms_sent", "dms_failed"):
            await mongo_db.stats.update_one(
                {"key": stat_key},
                {"$setOnInsert": {"key": stat_key, "value": 0}},
                upsert=True,
            )

        config.logger.info("MongoDB indexes initialized successfully.")
    except Exception as exc:
        config.logger.error(f"init_db error: {exc}")
        raise


# ===========================================================================
# User Operations
# ===========================================================================

async def add_or_update_user(user_id: int, first_name: str = "", username: str = ""):
    """Upserts a user record. Called on every join-request approval and /start."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    await mongo_db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "first_name": first_name,
                "username": username,
                "last_seen": now_str,
            },
            "$setOnInsert": {"joined_at": now_str},
        },
        upsert=True,
    )


async def remove_user(user_id: int):
    """Removes a user from the database (e.g. blocked / deactivated during broadcast)."""
    await mongo_db.users.delete_one({"user_id": user_id})


async def get_all_users() -> list[int]:
    """Returns a list of every stored user_id."""
    cursor = mongo_db.users.find({}, {"user_id": 1, "_id": 0})
    return [doc["user_id"] async for doc in cursor]


async def get_all_broadcast_users() -> list[int]:
    """
    Alias for get_all_users() with a semantically clear name.
    Returns every user_id from the users collection — includes:
      • Users who interacted with /start
      • Users who were accepted via join request
    """
    return await get_all_users()


async def count_users() -> int:
    """Returns the total number of stored users."""
    return await mongo_db.users.count_documents({})


# ===========================================================================
# Chat Operations
# ===========================================================================

async def register_chat(chat_id: int, title: str, chat_type: str):
    """Registers or updates a channel / group in the database."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    await mongo_db.chats.update_one(
        {"chat_id": chat_id},
        {
            "$set": {"title": title, "chat_type": chat_type},
            "$setOnInsert": {
                "welcome_msg": None,
                "auto_accept": True,
                "custom_buttons": [],
                "added_at": now_str,
            },
        },
        upsert=True,
    )


async def get_chat_settings(chat_id: int) -> dict:
    """Returns settings dict for a chat. Falls back to safe defaults if not found."""
    doc = await mongo_db.chats.find_one({"chat_id": chat_id})
    if not doc:
        return {
            "chat_id": chat_id,
            "title": "",
            "welcome_msg": None,
            "auto_accept": True,
            "custom_buttons": [],
        }
    return {
        "chat_id": doc.get("chat_id"),
        "title": doc.get("title", ""),
        "welcome_msg": doc.get("welcome_msg"),
        "auto_accept": doc.get("auto_accept", True),
        "custom_buttons": doc.get("custom_buttons", []),
    }


async def set_chat_welcome_msg(chat_id: int, msg: str):
    """Sets a per-chat custom welcome DM message."""
    await mongo_db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"welcome_msg": msg}},
        upsert=True,
    )


async def reset_chat_welcome_msg(chat_id: int):
    """Resets per-chat welcome message to None (falls back to global template)."""
    await mongo_db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"welcome_msg": None}},
    )


# ===========================================================================
# Global Owner Welcome Message
# ===========================================================================

async def get_global_welcome_msg() -> str:
    """Returns the bot-owner's global welcome DM template, or the config default."""
    doc = await mongo_db.global_settings.find_one({"key": "welcome_msg"})
    if doc and doc.get("value"):
        return doc["value"]
    return config.DEFAULT_WELCOME_MSG


async def set_global_welcome_msg(msg: str):
    """Saves the global welcome DM template set by the bot owner."""
    await mongo_db.global_settings.update_one(
        {"key": "welcome_msg"},
        {"$set": {"value": msg}},
        upsert=True,
    )


async def reset_global_welcome_msg():
    """Deletes the custom global welcome message so the config default takes over."""
    await mongo_db.global_settings.delete_one({"key": "welcome_msg"})


# ===========================================================================
# Auto-Accept Toggle
# ===========================================================================

async def toggle_auto_accept(chat_id: int, enabled: bool):
    """Enables or disables auto-accept for a specific chat."""
    await mongo_db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"auto_accept": enabled}},
        upsert=True,
    )


# ===========================================================================
# Chat Aggregates
# ===========================================================================

async def count_chats() -> int:
    """Returns total number of registered chats."""
    return await mongo_db.chats.count_documents({})


async def get_all_chats() -> list[dict]:
    """Returns a list of all chat documents."""
    cursor = mongo_db.chats.find({})
    return [doc async for doc in cursor]


# ===========================================================================
# Stats
# ===========================================================================

async def increment_stat(key: str, amount: int = 1):
    """Atomically increments a named counter."""
    await mongo_db.stats.update_one(
        {"key": key},
        {"$inc": {"value": amount}},
        upsert=True,
    )


async def get_all_stats() -> dict:
    """Returns a dict of all stat counters."""
    result = {"requests_approved": 0, "dms_sent": 0, "dms_failed": 0}
    cursor = mongo_db.stats.find({})
    async for doc in cursor:
        key = doc.get("key")
        if key in result:
            result[key] = doc.get("value", 0)
    return result
