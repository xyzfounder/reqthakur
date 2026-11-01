import json
import time
import aiosqlite
import config
from datetime import datetime

# Check if MongoDB is enabled
USE_MONGO = bool(config.MONGO_URI)
mongo_client = None
mongo_db = None

if USE_MONGO:
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_client = AsyncIOMotorClient(config.MONGO_URI)
        mongo_db = mongo_client["reqbot_database"]
        config.logger.info("Connected to MongoDB database.")
    except Exception as e:
        config.logger.warning(f"MongoDB connection failed: {e}. Falling back to SQLite.")
        USE_MONGO = False

async def init_db():
    """Initializes tables for SQLite if not using MongoDB."""
    if not USE_MONGO:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    joined_at TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    chat_type TEXT,
                    welcome_msg TEXT,
                    auto_accept INTEGER DEFAULT 1,
                    custom_buttons TEXT DEFAULT '[]',
                    added_at TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS global_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # Initialize stats if empty
            await db.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('requests_approved', 0)")
            await db.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('dms_sent', 0)")
            await db.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('dms_failed', 0)")
            await db.commit()
            config.logger.info("SQLite database initialized at " + config.SQLITE_DB_PATH)

# ==================== User Operations ====================

async def add_or_update_user(user_id: int, first_name: str = "", username: str = ""):
    """Adds or updates a user in the database."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if USE_MONGO:
        await mongo_db.users.update_one(
            {"user_id": user_id},
            {"$set": {"first_name": first_name, "username": username, "last_seen": now_str},
             "$setOnInsert": {"joined_at": now_str}},
            upsert=True
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                INSERT INTO users (user_id, first_name, username, joined_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    username=excluded.username
            """, (user_id, first_name, username, now_str))
            await db.commit()

async def get_all_users():
    """Returns list of all user IDs."""
    if USE_MONGO:
        cursor = mongo_db.users.find({}, {"user_id": 1})
        return [doc["user_id"] async for doc in cursor]
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

async def count_users():
    """Returns count of saved users."""
    if USE_MONGO:
        return await mongo_db.users.count_documents({})
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

# ==================== Chat Operations ====================

async def register_chat(chat_id: int, title: str, chat_type: str):
    """Registers a channel or group in the database."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if USE_MONGO:
        await mongo_db.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"title": title, "chat_type": chat_type},
             "$setOnInsert": {
                 "welcome_msg": None,
                 "auto_accept": True,
                 "custom_buttons": [],
                 "added_at": now_str
             }},
            upsert=True
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                INSERT INTO chats (chat_id, title, chat_type, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=excluded.title,
                    chat_type=excluded.chat_type
            """, (chat_id, title, chat_type, now_str))
            await db.commit()

async def get_chat_settings(chat_id: int):
    """Retrieves settings for a specific chat."""
    if USE_MONGO:
        doc = await mongo_db.chats.find_one({"chat_id": chat_id})
        if not doc:
            return {
                "chat_id": chat_id,
                "title": "",
                "welcome_msg": None,
                "auto_accept": True,
                "custom_buttons": []
            }
        return {
            "chat_id": doc.get("chat_id"),
            "title": doc.get("title", ""),
            "welcome_msg": doc.get("welcome_msg"),
            "auto_accept": doc.get("auto_accept", True),
            "custom_buttons": doc.get("custom_buttons", [])
        }
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            async with db.execute("""
                SELECT title, welcome_msg, auto_accept, custom_buttons
                FROM chats WHERE chat_id = ?
            """, (chat_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return {
                        "chat_id": chat_id,
                        "title": "",
                        "welcome_msg": None,
                        "auto_accept": True,
                        "custom_buttons": []
                    }
                try:
                    btns = json.loads(row[3]) if row[3] else []
                except Exception:
                    btns = []
                return {
                    "chat_id": chat_id,
                    "title": row[0],
                    "welcome_msg": row[1],
                    "auto_accept": bool(row[2]),
                    "custom_buttons": btns
                }

async def set_chat_welcome_msg(chat_id: int, msg: str):
    """Updates the custom welcome DM message for a chat."""
    if USE_MONGO:
        await mongo_db.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"welcome_msg": msg}},
            upsert=True
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                INSERT INTO chats (chat_id, welcome_msg)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET welcome_msg=excluded.welcome_msg
            """, (chat_id, msg))
            await db.commit()

async def reset_chat_welcome_msg(chat_id: int):
    """Resets the welcome DM message to default."""
    if USE_MONGO:
        await mongo_db.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"welcome_msg": None}}
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("UPDATE chats SET welcome_msg = NULL WHERE chat_id = ?", (chat_id,))
            await db.commit()

# ==================== Global Owner Welcome Message ====================

async def get_global_welcome_msg() -> str:
    """Returns the single global welcome DM message set by the bot owner."""
    if USE_MONGO:
        doc = await mongo_db.global_settings.find_one({"key": "welcome_msg"})
        if doc and doc.get("value"):
            return doc["value"]
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            async with db.execute("SELECT value FROM global_settings WHERE key = 'welcome_msg'") as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return row[0]
    return config.DEFAULT_WELCOME_MSG

async def set_global_welcome_msg(msg: str):
    """Sets the single global welcome DM message across all chats."""
    if USE_MONGO:
        await mongo_db.global_settings.update_one(
            {"key": "welcome_msg"},
            {"$set": {"value": msg}},
            upsert=True
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                INSERT INTO global_settings (key, value) VALUES ('welcome_msg', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (msg,))
            await db.commit()

async def reset_global_welcome_msg():
    """Resets the global welcome DM message back to config.DEFAULT_WELCOME_MSG."""
    if USE_MONGO:
        await mongo_db.global_settings.delete_one({"key": "welcome_msg"})
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("DELETE FROM global_settings WHERE key = 'welcome_msg'")
            await db.commit()

async def toggle_auto_accept(chat_id: int, enabled: bool):
    """Toggles auto acceptance for a chat."""
    if USE_MONGO:
        await mongo_db.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {"auto_accept": enabled}},
            upsert=True
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                INSERT INTO chats (chat_id, auto_accept)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET auto_accept=excluded.auto_accept
            """, (chat_id, 1 if enabled else 0))
            await db.commit()

async def count_chats():
    """Returns total count of registered groups and channels."""
    if USE_MONGO:
        return await mongo_db.chats.count_documents({})
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM chats") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

async def get_all_chats():
    """Returns list of registered chats."""
    if USE_MONGO:
        cursor = mongo_db.chats.find({})
        return [doc async for doc in cursor]
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM chats") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

# ==================== Stats Operations ====================

async def increment_stat(key: str, amount: int = 1):
    """Increments a counter in stats."""
    if USE_MONGO:
        await mongo_db.stats.update_one(
            {"key": key},
            {"$inc": {"value": amount}},
            upsert=True
        )
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            await db.execute("""
                INSERT INTO stats (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = value + ?
            """, (key, amount, amount))
            await db.commit()

async def get_all_stats():
    """Returns a dict of all stats."""
    result = {"requests_approved": 0, "dms_sent": 0, "dms_failed": 0}
    if USE_MONGO:
        cursor = mongo_db.stats.find({})
        async for doc in cursor:
            if doc.get("key") in result:
                result[doc["key"]] = doc.get("value", 0)
    else:
        async with aiosqlite.connect(config.SQLITE_DB_PATH) as db:
            async with db.execute("SELECT key, value FROM stats") as cursor:
                rows = await cursor.fetchall()
                for key, val in rows:
                    if key in result:
                        result[key] = val
    return result
