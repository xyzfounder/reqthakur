import os
import sys
import asyncio
from pyrogram import Client
import config
import database
from handlers.join_request import register_join_request_handlers
from handlers.bulk_actions import register_bulk_handlers
from handlers.chat_settings import register_settings_handlers
from handlers.admin import register_admin_handlers

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BANNER = r"""
  ____  _____ ___  ____   ___ _____ 
 |  _ \| ____/ _ \| __ ) / _ \_   _|
 | |_) |  _|| | | |  _ \| | | || |  
 |  _ <| |__| |_| | |_) | |_| || |  
 |_| \_\_____\__\_\____/ \___/ |_|  
                                    
  Ultra-Fast Join Request Acceptor & Channel Manager
"""

async def main():
    print(BANNER)
    print("=" * 65)

    # Validate configuration
    if not config.API_ID or not config.API_HASH or not config.BOT_TOKEN:
        print("\n❌ CONFIGURATION ERROR:")
        print("Please edit the '.env' file in this folder and configure:")
        print("1. API_ID & API_HASH  -> https://my.telegram.org")
        print("2. BOT_TOKEN          -> @BotFather on Telegram\n")
        print("=" * 65)
        return

    # Initialize Database
    await database.init_db()
    print("✅ Database ready.")

    # Prepare sessions directory
    sessions_dir = os.path.join(os.path.dirname(__file__), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    session_path = os.path.join(sessions_dir, "reqbot_session")

    # Initialize Pyrogram Client
    app = Client(
        name=session_path,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workers=16
    )

    # Register handlers
    register_join_request_handlers(app)
    register_bulk_handlers(app)
    register_settings_handlers(app)
    register_admin_handlers(app)
    print("✅ All event handlers successfully registered.")

    # Start Client
    await app.start()
    me = await app.get_me()
    print("=" * 65)
    print(f"🚀 REQBOT IS ONLINE & READY!")
    print(f"🤖 Bot Name: {me.first_name}")
    print(f"🔗 Username: @{me.username}")
    print(f"🆔 Bot ID:   {me.id}")
    print(f"👉 Direct Link: https://t.me/{me.username}")
    print("=" * 65)

    # Keep running until disconnected
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\n🛑 Stopping REQBOT gracefully...")
        await app.stop()
        print("✅ REQBOT stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nShutdown requested by user.")
