from pyrogram import Client, filters, enums
from pyrogram.types import Message
import config
import database
from helpers import is_sudo, is_chat_admin, format_welcome_message
from handlers.bulk_actions import resolve_target_chat

async def set_msg_command(client: Client, message: Message):
    """Sets the single global welcome DM message across all chats (Owner only)."""
    user_id = message.from_user.id if message.from_user else 0

    if not is_sudo(user_id):
        await message.reply_text("⛔ Only the **Bot Owner** can set the global welcome DM message!")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "❌ **Please provide the welcome message text!**\n\n"
            "**Usage:**\n`/setmsg Welcome to {chat_title}, {mention}! Enjoy your stay!`\n\n"
            "**Placeholders available:**\n"
            "• `{name}` — User's first name\n"
            "• `{mention}` — Clickable user mention link\n"
            "• `{username}` — User @username\n"
            "• `{chat_title}` — Channel or group title\n"
            "• `{chat_id}` — Channel or group ID\n"
            "• `{user_id}` — Telegram user ID"
        )
        return

    new_msg = parts[1]
    await database.set_global_welcome_msg(new_msg)
    await message.reply_text(
        "✅ **Global Welcome DM message updated successfully!**\n\n"
        "This message will now be sent in DM to every user whose join request is accepted in any group or channel.\n\n"
        f"**New Message Template:**\n{new_msg}\n\n"
        "Use `/previewmsg` to test how it looks!"
    )

async def get_msg_command(client: Client, message: Message):
    """Displays the currently set single global welcome DM message."""
    user_id = message.from_user.id if message.from_user else 0
    if not is_sudo(user_id):
        await message.reply_text("⛔ Only the **Bot Owner** can view the global welcome settings!")
        return

    current = await database.get_global_welcome_msg()
    is_custom = "Custom (Saved in DB)" if current != config.DEFAULT_WELCOME_MSG else "Default (From .env)"

    await message.reply_text(
        f"📋 **Current Global Welcome DM Message:**\n\n"
        f"**Source:** `{is_custom}`\n\n"
        f"**Template:**\n{current}\n\n"
        f"*(Use `/setmsg <text>` to change or `/resetmsg` to reset)*"
    )

async def reset_msg_command(client: Client, message: Message):
    """Resets the global welcome DM message back to default (Owner only)."""
    user_id = message.from_user.id if message.from_user else 0
    if not is_sudo(user_id):
        await message.reply_text("⛔ Only the **Bot Owner** can reset the global welcome DM message!")
        return

    await database.reset_global_welcome_msg()
    await message.reply_text(
        "🔄 **Global Welcome DM message has been reset to default!**\n\n"
        f"**Default Template:**\n{config.DEFAULT_WELCOME_MSG}"
    )

async def preview_msg_command(client: Client, message: Message):
    """Sends a live preview of the global welcome DM message to the caller."""
    template = await database.get_global_welcome_msg()

    class SampleChat:
        title = "Demo Channel"
        id = -1001234567890

    sample_chat = message.chat if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL) else SampleChat()

    preview_text = format_welcome_message(template, message.from_user, sample_chat)

    await message.reply_text(
        f"👁️ **Preview of Welcome DM:**\n"
        f"────────────────────────\n"
        f"{preview_text}\n"
        f"────────────────────────\n"
        f"*(This is the exact message new users receive in DM when approved)*"
    )

async def toggle_auto_command(client: Client, message: Message):
    """Toggles Auto Accept ON/OFF for the chat."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id, title_or_err = await resolve_target_chat(client, message)
    if not chat_id:
        await message.reply_text(f"❌ {title_or_err}")
        return

    if not await is_chat_admin(client, chat_id, user_id):
        await message.reply_text("⛔ You must be an administrator of that chat to toggle settings.")
        return

    settings = await database.get_chat_settings(chat_id)
    current_status = settings.get("auto_accept", True)
    new_status = not current_status

    await database.toggle_auto_accept(chat_id, new_status)
    status_str = "🟢 **ENABLED**" if new_status else "🔴 **DISABLED**"

    await message.reply_text(
        f"⚙️ **Auto Accept Status Updated!**\n\n"
        f"📢 **Chat:** {title_or_err}\n"
        f"Status: {status_str}"
    )

def register_settings_handlers(client: Client):
    """Registers settings commands."""
    client.on_message(filters.command("setmsg"))(set_msg_command)
    client.on_message(filters.command("getmsg"))(get_msg_command)
    client.on_message(filters.command("resetmsg"))(reset_msg_command)
    client.on_message(filters.command("previewmsg"))(preview_msg_command)
    client.on_message(filters.command(["toggleauto", "autotoggle"]))(toggle_auto_command)
