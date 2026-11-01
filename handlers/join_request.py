import asyncio
from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait, UserAlreadyParticipant
import config
import database
from helpers import format_welcome_message, send_dm_safe

async def handle_chat_join_request(client: Client, request: ChatJoinRequest):
    """
    Triggers automatically whenever a user sends a join request
    to any channel or group where this bot is an administrator.
    """
    chat = request.chat
    user = request.from_user

    config.logger.info(
        f"📩 New Join Request received: User {user.id} ({user.first_name}) -> Chat {chat.id} ({chat.title})"
    )

    # Save chat and user to database
    chat_type = str(chat.type.name) if hasattr(chat.type, "name") else str(chat.type)
    await database.register_chat(chat.id, chat.title or "Unknown", chat_type)
    await database.add_or_update_user(user.id, user.first_name or "", user.username or "")

    # Fetch chat-specific settings
    settings = await database.get_chat_settings(chat.id)
    if not settings.get("auto_accept", True):
        config.logger.info(f"Auto-accept is paused for chat {chat.id}. Request not approved.")
        return

    # Approve Join Request
    approved = False
    try:
        await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
        approved = True
        await database.increment_stat("requests_approved")
        config.logger.info(f"✅ Approved join request for {user.id} in {chat.title}")
    except FloodWait as f:
        wait_time = int(f.value)
        config.logger.warning(f"FloodWait on approving request for {user.id}. Waiting {wait_time}s...")
        await asyncio.sleep(wait_time)
        try:
            await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
            approved = True
            await database.increment_stat("requests_approved")
        except Exception as err:
            config.logger.error(f"Failed to approve request for {user.id} after FloodWait: {err}")
    except UserAlreadyParticipant:
        config.logger.info(f"User {user.id} is already a participant in {chat.title}.")
        approved = True
    except Exception as e:
        config.logger.error(f"Failed to approve join request for {user.id} in {chat.id}: {e}")

    if not approved:
        return

    # Single global Welcome DM template set by the Bot Owner
    template = await database.get_global_welcome_msg()

    # Format DM with user & chat variables
    dm_text = format_welcome_message(template, user, chat)

    # Send DM to the user
    dm_success = await send_dm_safe(client, user.id, dm_text)
    if dm_success:
        config.logger.info(f"💌 Sent Welcome DM to {user.id} ({user.first_name})")
    else:
        config.logger.info(f"⚠️ Could not send DM to {user.id} (DMs might be restricted or blocked)")

    # Send optional log to LOG_CHANNEL
    if config.LOG_CHANNEL:
        try:
            status_emoji = "💌 Sent DM" if dm_success else "⚠️ DM Failed"
            log_text = (
                f"🎉 **New Member Approved!**\n\n"
                f"👤 **User:** [{user.first_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"📢 **Chat:** **{chat.title}** (`{chat.id}`)\n"
                f"📬 **Status:** {status_emoji}"
            )
            await client.send_message(
                chat_id=config.LOG_CHANNEL,
                text=log_text,
                disable_web_page_preview=True
            )
        except Exception as err:
            config.logger.warning(f"Failed to send log to LOG_CHANNEL: {err}")

def register_join_request_handlers(client: Client):
    """Registers join request event handler on client."""
    client.on_chat_join_request()(handle_chat_join_request)
