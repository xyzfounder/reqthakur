"""
handlers/join_request.py — Handles incoming Telegram join requests.

On approval:
  • Saves user to DB (always, even if DM fails).
  • Sends personalized Welcome DM with an inline "📢 View Channel/Group" button
    linking to the chat's invite link (if available).
  • Small post-approval delay to avoid Telegram flood limits.
  • Logs outcome to LOG_CHANNEL if configured.
"""

import asyncio
from pyrogram import Client
from pyrogram.types import (
    ChatJoinRequest,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import (
    FloodWait,
    UserAlreadyParticipant,
    UserIsBlocked,
    InputUserDeactivated,
    PeerIdInvalid,
    UserNotMutualContact,
)
import config
import database
from helpers import format_welcome_message


async def handle_chat_join_request(client: Client, request: ChatJoinRequest):
    """
    Triggered for every new join request in any chat where the bot is admin.
    """
    chat = request.chat
    user = request.from_user

    config.logger.info(
        f"📩 Join Request — User {user.id} ({user.first_name}) → Chat {chat.id} ({chat.title})"
    )

    # ------------------------------------------------------------------
    # 1. Persist chat & user to database (always, regardless of outcome)
    # ------------------------------------------------------------------
    chat_type = str(chat.type.name) if hasattr(chat.type, "name") else str(chat.type)
    await database.register_chat(chat.id, chat.title or "Unknown", chat_type)
    await database.add_or_update_user(user.id, user.first_name or "", user.username or "")

    # ------------------------------------------------------------------
    # 2. Check auto-accept setting
    # ------------------------------------------------------------------
    settings = await database.get_chat_settings(chat.id)
    if not settings.get("auto_accept", True):
        config.logger.info(f"Auto-accept is OFF for chat {chat.id}. Skipping approval.")
        return

    # ------------------------------------------------------------------
    # 3. Approve the join request
    # ------------------------------------------------------------------
    approved = False
    try:
        await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
        approved = True
        await database.increment_stat("requests_approved")
        config.logger.info(f"✅ Approved {user.id} in {chat.title}")

    except FloodWait as fw:
        wait_time = max(int(fw.value), 1)
        config.logger.warning(f"FloodWait {wait_time}s while approving {user.id}. Waiting…")
        await asyncio.sleep(wait_time)
        try:
            await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
            approved = True
            await database.increment_stat("requests_approved")
        except Exception as err:
            config.logger.error(f"Approval failed after FloodWait for {user.id}: {err}")

    except UserAlreadyParticipant:
        config.logger.info(f"User {user.id} already in {chat.title} — marking as approved.")
        approved = True

    except Exception as exc:
        config.logger.error(f"Failed to approve {user.id} in {chat.id}: {exc}")

    if not approved:
        return

    # Small delay after approval to avoid triggering Telegram flood limits
    await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # 4. Build the Welcome DM
    # ------------------------------------------------------------------
    template = await database.get_global_welcome_msg()
    dm_text  = format_welcome_message(template, user, chat)

    # Build inline keyboard — link to chat if invite link is available
    reply_markup = None
    invite_link  = getattr(chat, "invite_link", None)
    if invite_link:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 View Channel/Group", url=invite_link)]
        ])

    # ------------------------------------------------------------------
    # 5. Send Welcome DM (best-effort — user is already saved to DB)
    # ------------------------------------------------------------------
    dm_success = await _send_welcome_dm(client, user.id, dm_text, reply_markup)

    if dm_success:
        await database.increment_stat("dms_sent")
        config.logger.info(f"💌 Welcome DM sent to {user.id} ({user.first_name})")
    else:
        await database.increment_stat("dms_failed")
        config.logger.info(f"⚠️ Could not DM {user.id} — DMs restricted or bot blocked")

    # ------------------------------------------------------------------
    # 6. Optional LOG_CHANNEL notification
    # ------------------------------------------------------------------
    if config.LOG_CHANNEL:
        try:
            status_emoji = "💌 DM Sent" if dm_success else "⚠️ DM Failed"
            log_text = (
                f"🎉 **New Member Approved!**\n\n"
                f"👤 **User:** [{user.first_name}](tg://user?id={user.id}) (`{user.id}`)\n"
                f"📢 **Chat:** **{chat.title}** (`{chat.id}`)\n"
                f"📬 **Status:** {status_emoji}"
            )
            await client.send_message(
                chat_id=config.LOG_CHANNEL,
                text=log_text,
                disable_web_page_preview=True,
            )
        except Exception as log_err:
            config.logger.warning(f"Failed to log to LOG_CHANNEL: {log_err}")


async def _send_welcome_dm(
    client: Client,
    user_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    """
    Sends a DM to a user. Returns True on success, False on failure.
    Retries once on FloodWait; silently ignores privacy / blocked errors.
    """
    for attempt in range(2):
        try:
            await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            return True

        except FloodWait as fw:
            if attempt == 0:
                await asyncio.sleep(max(int(fw.value), 1))
                continue
            return False

        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid, UserNotMutualContact):
            return False

        except Exception as exc:
            config.logger.warning(f"DM to {user_id} failed: {exc}")
            return False

    return False


def register_join_request_handlers(client: Client):
    """Registers the join-request event handler."""
    client.on_chat_join_request()(handle_chat_join_request)
