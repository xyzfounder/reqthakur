import asyncio
import time
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from pyrogram.errors import (
    FloodWait,
    ChatAdminRequired,
    UserAdminInvalid,
    RightForbidden
)
import config
import database
from helpers import (
    is_chat_admin,
    is_sudo,
    format_welcome_message,
    send_dm_safe,
    progress_bar,
    ACTIVE_OPERATIONS
)

async def resolve_target_chat(client: Client, message: Message):
    """
    Determines the target chat ID.
    If called in a group/channel: returns message.chat.id.
    If called in private chat: checks if an argument was supplied, e.g. /command -100123456789
    """
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL):
        return message.chat.id, message.chat.title

    # Private chat: check command arguments
    parts = message.text.strip().split()
    if len(parts) > 1:
        target = parts[1]
        try:
            target_id = int(target)
            chat = await client.get_chat(target_id)
            return chat.id, chat.title
        except ValueError:
            # Username provided
            try:
                chat = await client.get_chat(target)
                return chat.id, chat.title
            except Exception as e:
                return None, f"Could not find chat `{target}`: {e}"
        except Exception as e:
            return None, f"Could not access chat `{target}`: {e}"

    return None, "Please run this command directly inside your group/channel, or provide the chat ID/username:\nExample: `/acceptall -1001234567890`"

# ==================== /acceptall Command ====================

async def accept_all_command(client: Client, message: Message):
    """
    Approves all pending join requests for the group/channel,
    and sends each approved user a Welcome DM!
    """
    user_id = message.from_user.id if message.from_user else 0

    chat_id, title_or_err = await resolve_target_chat(client, message)
    if not chat_id:
        await message.reply_text(f"❌ {title_or_err}")
        return

    # Check caller permissions
    if not await is_chat_admin(client, chat_id, user_id):
        await message.reply_text("⛔ You must be an administrator of this chat to run this command.")
        return

    # Check if another operation is already running
    if ACTIVE_OPERATIONS.get(chat_id):
        await message.reply_text("⚠️ An operation is already running for this chat. Use /cancel to stop it.")
        return

    status_msg = await message.reply_text(
        f"🔍 **Scanning pending join requests for:**\n**{title_or_err}** (`{chat_id}`)...\n"
        "Please wait."
    )

    # Check bot permissions
    try:
        me = await client.get_me()
        bot_member = await client.get_chat_member(chat_id, me.id)
        if not (bot_member.privileges and bot_member.privileges.can_invite_users):
            await status_msg.edit_text("❌ Bot lacks the **'Invite Users via Link' / 'Add Members'** permission in this chat!")
            return
    except Exception as e:
        config.logger.warning(f"Failed to check bot privileges: {e}")

    # Mark operation active
    ACTIVE_OPERATIONS[chat_id] = True

    approved_count = 0
    dm_sent_count = 0
    dm_failed_count = 0
    last_update_time = time.time()

    # Single global Welcome DM template set by the Bot Owner
    template = await database.get_global_welcome_msg()

    try:
        chat_obj = await client.get_chat(chat_id)
    except Exception:
        chat_obj = message.chat

    try:
        async for joiner in client.get_chat_join_requests(chat_id):
            if not ACTIVE_OPERATIONS.get(chat_id):
                await status_msg.edit_text(
                    f"🛑 **Operation Cancelled by Admin!**\n\n"
                    f"✅ **Approved so far:** `{approved_count}`\n"
                    f"💌 **DMs Sent:** `{dm_sent_count}`\n"
                    f"⚠️ **DMs Failed:** `{dm_failed_count}`"
                )
                return

            u = joiner.user
            if not u:
                continue

            # Approve the request
            try:
                await client.approve_chat_join_request(chat_id, u.id)
                approved_count += 1
                await database.increment_stat("requests_approved")
                await database.add_or_update_user(u.id, u.first_name or "", u.username or "")
            except FloodWait as f:
                wait_s = int(f.value)
                await asyncio.sleep(wait_s)
                try:
                    await client.approve_chat_join_request(chat_id, u.id)
                    approved_count += 1
                    await database.increment_stat("requests_approved")
                except Exception:
                    continue
            except Exception as e:
                config.logger.warning(f"Error approving join request for {u.id}: {e}")
                continue

            # Send DM to the accepted user
            dm_text = format_welcome_message(template, u, chat_obj)
            dm_ok = await send_dm_safe(client, u.id, dm_text)
            if dm_ok:
                dm_sent_count += 1
            else:
                dm_failed_count += 1

            # Update progress every 3 seconds
            if time.time() - last_update_time > 3:
                try:
                    await status_msg.edit_text(
                        f"⏳ **Accepting Pending Requests...**\n"
                        f"📢 **Chat:** {chat_obj.title}\n\n"
                        f"✅ **Approved:** `{approved_count}`\n"
                        f"💌 **DMs Sent:** `{dm_sent_count}`\n"
                        f"⚠️ **DMs Failed:** `{dm_failed_count}`\n\n"
                        f"Send `/cancel` to abort at any time."
                    )
                    last_update_time = time.time()
                except Exception:
                    pass

        # If zero requests were processed, check fast bulk approve or empty
        if approved_count == 0:
            # Try Telegram's fast bulk approve method
            try:
                res = await client.approve_all_chat_join_requests(chat_id)
                if res:
                    await status_msg.edit_text(
                        f"✅ **All pending join requests for {chat_obj.title} have been approved!**\n\n"
                        f"*(Bulk fast-approved via Telegram API)*"
                    )
                    return
            except Exception:
                pass
            await status_msg.edit_text("ℹ️ **No pending join requests found for this chat!**")
        else:
            await status_msg.edit_text(
                f"🎉 **Accept All Completed Successfully!**\n\n"
                f"📢 **Chat:** {chat_obj.title}\n"
                f"✅ **Total Requests Approved:** `{approved_count}`\n"
                f"💌 **DMs Delivered:** `{dm_sent_count}`\n"
                f"⚠️ **DMs Failed (blocked/restricted):** `{dm_failed_count}`"
            )

    except FloodWait as f:
        await asyncio.sleep(int(f.value))
    except Exception as e:
        config.logger.error(f"Error in acceptall: {e}")
        await status_msg.edit_text(f"❌ An error occurred during `/acceptall`: `{e}`")
    finally:
        ACTIVE_OPERATIONS.pop(chat_id, None)

# ==================== /kickall Command ====================

async def kick_all_command(client: Client, message: Message):
    """
    Shows confirmation to kick all non-admin members from the chat.
    """
    user_id = message.from_user.id if message.from_user else 0
    chat_id, title_or_err = await resolve_target_chat(client, message)
    if not chat_id:
        await message.reply_text(f"❌ {title_or_err}")
        return

    if not await is_chat_admin(client, chat_id, user_id):
        await message.reply_text("⛔ You must be an administrator of this chat to run this command.")
        return

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Yes, Kick All", callback_data=f"confirm_kick:{chat_id}:{user_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_action:{chat_id}")
        ]
    ])

    await message.reply_text(
        f"⚠️ **CONFIRMATION REQUIRED: KICK ALL**\n\n"
        f"Are you sure you want to **KICK all regular members** from:\n"
        f"**{title_or_err}** (`{chat_id}`)?\n\n"
        f"🛡️ *Admins and Bots will NOT be kicked.*",
        reply_markup=buttons
    )

# ==================== /banall Command ====================

async def ban_all_command(client: Client, message: Message):
    """
    Shows confirmation to ban all non-admin members from the chat.
    """
    user_id = message.from_user.id if message.from_user else 0
    chat_id, title_or_err = await resolve_target_chat(client, message)
    if not chat_id:
        await message.reply_text(f"❌ {title_or_err}")
        return

    if not await is_chat_admin(client, chat_id, user_id):
        await message.reply_text("⛔ You must be an administrator of this chat to run this command.")
        return

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⛔ Yes, Ban All", callback_data=f"confirm_ban:{chat_id}:{user_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_action:{chat_id}")
        ]
    ])

    await message.reply_text(
        f"⛔ **CONFIRMATION REQUIRED: BAN ALL**\n\n"
        f"Are you sure you want to **BAN all regular members** from:\n"
        f"**{title_or_err}** (`{chat_id}`)?\n\n"
        f"🛡️ *Admins and Bots will NOT be banned.*",
        reply_markup=buttons
    )

# ==================== /unbanall Command ====================

async def unban_all_command(client: Client, message: Message):
    """
    Unbans all banned members from the group or channel.
    """
    user_id = message.from_user.id if message.from_user else 0
    chat_id, title_or_err = await resolve_target_chat(client, message)
    if not chat_id:
        await message.reply_text(f"❌ {title_or_err}")
        return

    if not await is_chat_admin(client, chat_id, user_id):
        await message.reply_text("⛔ You must be an administrator of this chat to run this command.")
        return

    if ACTIVE_OPERATIONS.get(chat_id):
        await message.reply_text("⚠️ An operation is already running for this chat. Use /cancel to stop it.")
        return

    status_msg = await message.reply_text(
        f"🔍 **Fetching banned users for:**\n**{title_or_err}** (`{chat_id}`)...\nPlease wait."
    )

    ACTIVE_OPERATIONS[chat_id] = True
    unbanned_count = 0
    last_update_time = time.time()

    try:
        async for member in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.BANNED):
            if not ACTIVE_OPERATIONS.get(chat_id):
                await status_msg.edit_text(
                    f"🛑 **Unban All Cancelled!**\nUnbanned so far: `{unbanned_count}`"
                )
                return

            try:
                await client.unban_chat_member(chat_id, member.user.id)
                unbanned_count += 1
            except FloodWait as f:
                await asyncio.sleep(int(f.value))
                try:
                    await client.unban_chat_member(chat_id, member.user.id)
                    unbanned_count += 1
                except Exception:
                    pass
            except Exception as e:
                config.logger.warning(f"Error unbanning {member.user.id}: {e}")

            if time.time() - last_update_time > 3:
                try:
                    await status_msg.edit_text(
                        f"⏳ **Unbanning members...**\n"
                        f"📢 **Chat:** {title_or_err}\n"
                        f"🔓 **Unbanned so far:** `{unbanned_count}`\n\n"
                        f"Send `/cancel` to abort."
                    )
                    last_update_time = time.time()
                except Exception:
                    pass

        await status_msg.edit_text(
            f"✅ **Unban All Completed!**\n\n"
            f"📢 **Chat:** {title_or_err}\n"
            f"🔓 **Total Unbanned Users:** `{unbanned_count}`"
        )
    except Exception as e:
        config.logger.error(f"Error in unbanall: {e}")
        await status_msg.edit_text(f"❌ Error during `/unbanall`: `{e}`")
    finally:
        ACTIVE_OPERATIONS.pop(chat_id, None)

# ==================== /cancel Command ====================

async def cancel_command(client: Client, message: Message):
    """
    Cancels any active bulk action for the current chat.
    """
    user_id = message.from_user.id if message.from_user else 0
    chat_id, title_or_err = await resolve_target_chat(client, message)
    if not chat_id:
        await message.reply_text(f"❌ {title_or_err}")
        return

    if not await is_chat_admin(client, chat_id, user_id):
        await message.reply_text("⛔ You must be an administrator of this chat to run this command.")
        return

    if ACTIVE_OPERATIONS.get(chat_id):
        ACTIVE_OPERATIONS[chat_id] = False
        await message.reply_text("🛑 **Cancellation signal sent.** Stopping operation...")
    else:
        await message.reply_text("ℹ️ No active bulk operations are running for this chat.")

# ==================== Callback Handlers for Confirmation ====================

async def handle_bulk_callbacks(client: Client, callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    if data.startswith("cancel_action:"):
        chat_id = int(data.split(":")[1])
        ACTIVE_OPERATIONS.pop(chat_id, None)
        await callback.message.edit_text("❌ **Operation cancelled.**")
        await callback.answer("Cancelled.")
        return

    if data.startswith("confirm_kick:") or data.startswith("confirm_ban:"):
        parts = data.split(":")
        action = parts[0]
        chat_id = int(parts[1])
        requester_id = int(parts[2])

        if user_id != requester_id and not is_sudo(user_id):
            await callback.answer("⛔ Only the user who requested this can confirm!", show_alert=True)
            return

        if ACTIVE_OPERATIONS.get(chat_id):
            await callback.answer("⚠️ An operation is already running!", show_alert=True)
            return

        is_kick = (action == "confirm_kick")
        action_name = "Kick" if is_kick else "Ban"

        await callback.message.edit_text(
            f"⏳ **Starting {action_name} All process...**\nPlease do not interrupt. Use `/cancel` to abort."
        )
        await callback.answer(f"Starting {action_name} All...")

        ACTIVE_OPERATIONS[chat_id] = True
        processed_count = 0
        last_update_time = time.time()

        me = await client.get_me()

        try:
            async for member in client.get_chat_members(chat_id):
                if not ACTIVE_OPERATIONS.get(chat_id):
                    await callback.message.edit_text(
                        f"🛑 **{action_name} All Cancelled by Admin!**\n"
                        f"Processed so far: `{processed_count}`"
                    )
                    return

                # Protect bots, admins, owners, and self
                if member.user.is_bot:
                    continue
                if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    continue
                if member.user.id in config.SUDO_USERS or member.user.id == me.id:
                    continue

                try:
                    if is_kick:
                        # Kick = Ban + Unban immediately
                        await client.ban_chat_member(chat_id, member.user.id)
                        await client.unban_chat_member(chat_id, member.user.id)
                    else:
                        # Ban permanently
                        await client.ban_chat_member(chat_id, member.user.id)

                    processed_count += 1
                except FloodWait as f:
                    await asyncio.sleep(int(f.value))
                    try:
                        if is_kick:
                            await client.ban_chat_member(chat_id, member.user.id)
                            await client.unban_chat_member(chat_id, member.user.id)
                        else:
                            await client.ban_chat_member(chat_id, member.user.id)
                        processed_count += 1
                    except Exception:
                        pass
                except (ChatAdminRequired, UserAdminInvalid, RightForbidden) as err:
                    config.logger.warning(f"Permission error removing {member.user.id}: {err}")
                except Exception as err:
                    config.logger.warning(f"Error {action_name}ing {member.user.id}: {err}")

                if time.time() - last_update_time > 3:
                    try:
                        await callback.message.edit_text(
                            f"⏳ **{action_name}ing members in progress...**\n"
                            f"👥 **{action_name}ed so far:** `{processed_count}`\n\n"
                            f"Send `/cancel` to stop at any time."
                        )
                        last_update_time = time.time()
                    except Exception:
                        pass

            await callback.message.edit_text(
                f"✅ **{action_name} All Completed!**\n\n"
                f"🎯 **Total members {action_name.lower()}ed:** `{processed_count}`"
            )

        except Exception as e:
            config.logger.error(f"Error in {action_name} All: {e}")
            await callback.message.edit_text(f"❌ Error during `{action_name} All`: `{e}`")
        finally:
            ACTIVE_OPERATIONS.pop(chat_id, None)

def register_bulk_handlers(client: Client):
    """Registers commands and callbacks on client."""
    client.on_message(filters.command(["acceptall", "approveall"]))(accept_all_command)
    client.on_message(filters.command("kickall"))(kick_all_command)
    client.on_message(filters.command("banall"))(ban_all_command)
    client.on_message(filters.command("unbanall"))(unban_all_command)
    client.on_message(filters.command("cancel"))(cancel_command)
    client.on_callback_query(filters.regex(r"^(confirm_kick|confirm_ban|cancel_action):"))(handle_bulk_callbacks)
