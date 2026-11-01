import asyncio
import html
from pyrogram import Client, enums
from pyrogram.types import User, Chat, InlineKeyboardMarkup
from pyrogram.errors import (
    FloodWait,
    UserIsBlocked,
    PeerIdInvalid,
    InputUserDeactivated,
    ChatAdminRequired,
    UserNotMutualContact,
    BotResponseTimeout
)
import config
import database

# Dictionary to track running bulk operations: chat_id -> bool (is_cancelled)
ACTIVE_OPERATIONS = {}

def is_sudo(user_id: int) -> bool:
    """Checks if a user is the bot owner or authorized sudo."""
    return user_id in config.SUDO_USERS

async def is_chat_admin(client: Client, chat_id: int, user_id: int) -> bool:
    """Checks if a user is an administrator or owner of the given chat."""
    if is_sudo(user_id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER)
    except Exception as e:
        config.logger.warning(f"Error checking admin status for user {user_id} in {chat_id}: {e}")
        return False

async def get_bot_permissions(client: Client, chat_id: int):
    """Retrieves the bot's permissions in a chat."""
    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
        return member
    except Exception as e:
        config.logger.error(f"Failed to get bot permissions in {chat_id}: {e}")
        return None

def format_welcome_message(template: str, user: User, chat: Chat) -> str:
    """
    Substitutes dynamic variables inside the welcome message template.
    Supported placeholders:
    {name}       - User's first name (escaped)
    {mention}    - User mention
    {username}   - @username or first name
    {user_id}    - Telegram User ID
    {chat_title} - Group or Channel Title
    {chat_id}    - Group or Channel ID
    """
    first_name = user.first_name or "Friend"
    mention = user.mention
    username = f"@{user.username}" if user.username else first_name
    chat_title = chat.title or "our community"

    formatted = template.replace("{name}", first_name)
    formatted = formatted.replace("{mention}", mention)
    formatted = formatted.replace("{username}", username)
    formatted = formatted.replace("{user_id}", str(user.id))
    formatted = formatted.replace("{chat_title}", chat_title)
    formatted = formatted.replace("{chat_id}", str(chat.id))

    return formatted

async def send_dm_safe(client: Client, user_id: int, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Sends a private message to a user safely with FloodWait retry & error suppression.
    Returns True if sent, False if failed.
    """
    retries = 3
    while retries > 0:
        try:
            await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            await database.increment_stat("dms_sent")
            return True
        except FloodWait as f:
            wait_time = int(f.value)
            config.logger.warning(f"FloodWait while DMing {user_id}. Sleeping {wait_time}s...")
            await asyncio.sleep(wait_time)
            retries -= 1
        except (UserIsBlocked, PeerIdInvalid, InputUserDeactivated, UserNotMutualContact):
            # User has blocked the bot or has strict privacy settings
            await database.increment_stat("dms_failed")
            return False
        except Exception as e:
            config.logger.warning(f"Could not send DM to {user_id}: {e}")
            await database.increment_stat("dms_failed")
            return False
    return False

def progress_bar(current: int, total: int, length: int = 10) -> str:
    """Generates a text-based progress bar."""
    if total <= 0:
        return "[░░░░░░░░░░] 0%"
    percent = min(100, int((current / total) * 100))
    filled = int(length * current // total)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent}%"
