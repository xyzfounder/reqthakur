"""
handlers/admin.py — Admin panel, /start, /help, /stats, /broadcast, /cancelbroadcast.

Broadcast features:
  • Sends to ALL users in database (accepted via join request OR /start)
  • Supports plain text (from args) OR replying to any media/text message
  • Rate-limited: 0.05 s sleep between sends
  • Cancellable via /cancelbroadcast
  • Progress update every 5 seconds (sent / failed / total / % / ETA)
  • Auto-removes blocked / deactivated users from DB
  • Final summary with time taken
"""

import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import (
    FloodWait,
    UserIsBlocked,
    PeerIdInvalid,
    InputUserDeactivated,
    MessageNotModified,
)
import config
import database
from helpers import is_sudo

# ---------------------------------------------------------------------------
# Broadcast state — module-level, shared across coroutines
# ---------------------------------------------------------------------------
BROADCAST_TASK: dict = {"active": False, "cancel": False}

# ---------------------------------------------------------------------------
# UI text constants
# ---------------------------------------------------------------------------

START_TEXT = """
👋 **Hello {mention}!**

I am **Request Accept Bot**, your ultra-fast Telegram manager.

⚡ **What I Can Do:**
• 🟢 **Auto-Approve Join Requests** immediately when users request to join your channels or groups.
• 💌 **Send Custom Welcome DMs** directly to each user as soon as they are accepted!
• ⏩ **/acceptall** — Approve all pending requests that were waiting in the group/channel!
• 👢 **/kickall** — Remove all regular members safely (protects admins & bots).
• ⛔ **/banall** — Ban all regular members safely.
• 🔓 **/unbanall** — Unban all previously banned users.
• 📝 **/setmsg** — Customize the global DM welcome message.
• 📡 **/broadcast** — Broadcast a message to ALL users (owner only).

👉 **How to Use:**
Add me as an **Admin** in your Channel or Group with **"Add Members" / "Invite Users"** permission!
"""

HELP_TEXT = """
📖 **REQBOT Command Guide & Setup Instructions**

🛠️ **Group & Channel Setup:**
1. Add this bot to your Channel or Group.
2. Grant Admin rights:
   • For Auto-Accept & `/acceptall`: Enable **Invite Users via Link** (or Add Members).
   • For `/kickall`, `/banall`, `/unbanall`: Enable **Ban Users**.
3. Create an Invite Link with **"Request Admin Approval"** turned ON.

📋 **Available Commands:**

• `/acceptall` (or `/approveall`)
  Approve all pending join requests and send each user a Welcome DM!
  *(In private chat: `/acceptall <chat_id>`)*

• `/kickall`
  Kicks all regular members from the group.
  *(Admins and Bots are never kicked)*

• `/banall`
  Bans all regular members from the group.
  *(Admins and Bots are never banned)*

• `/unbanall`
  Unbans all banned members in the group/channel.

• `/cancel`
  Aborts any running bulk operation (`acceptall`, `kickall`, `banall`, `unbanall`).

• `/toggleauto` — Turn Auto-Accept ON or OFF for this chat.

👑 **Bot Owner Commands:**
• `/setmsg <text>` — Set the single global Welcome DM message sent across ALL channels & groups!
  *(Placeholders: `{name}`, `{mention}`, `{username}`, `{chat_title}`, `{user_id}`)*
• `/getmsg` — View current global Welcome DM template.
• `/previewmsg` — Test-preview how the Welcome DM looks.
• `/resetmsg` — Reset global Welcome DM to default (.env).
• `/stats` — View bot statistics and counters.
• `/broadcast <msg>` or **reply to any message** with `/broadcast`
  Sends a broadcast to **ALL users** — everyone who was ever accepted by this bot or used /start.
  Supports text, photo, video, document, audio, voice, sticker, animation, and more.
• `/cancelbroadcast` (or `/bc cancel`) — Cancel an ongoing broadcast mid-way.

ℹ️ Broadcast reaches every user in the database — including users accepted through join requests
and users who have directly interacted with the bot.
"""


# ---------------------------------------------------------------------------
# Button helpers
# ---------------------------------------------------------------------------

def get_start_buttons(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add to Channel", url=f"https://t.me/{bot_username}?startchannel=true"),
            InlineKeyboardButton("➕ Add to Group",   url=f"https://t.me/{bot_username}?startgroup=true"),
        ],
        [
            InlineKeyboardButton("📖 Help & Commands", callback_data="btn_help"),
            InlineKeyboardButton("📊 Bot Stats",        callback_data="btn_stats"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="btn_close"),
        ],
    ])


def get_help_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Back to Main", callback_data="btn_start"),
            InlineKeyboardButton("📊 Bot Stats",     callback_data="btn_stats"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="btn_close"),
        ],
    ])


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start_command(client: Client, message: Message):
    user = message.from_user
    if user:
        await database.add_or_update_user(user.id, user.first_name or "", user.username or "")

    me = await client.get_me()
    mention = user.mention if user else "Friend"
    text = START_TEXT.format(mention=mention)
    buttons = get_start_buttons(me.username)
    await message.reply_text(text, reply_markup=buttons, disable_web_page_preview=True)


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

async def help_command(client: Client, message: Message):
    buttons = get_help_buttons()
    await message.reply_text(HELP_TEXT, reply_markup=buttons, disable_web_page_preview=True)


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

async def stats_command(client: Client, message: Message):
    stats      = await database.get_all_stats()
    user_count = await database.count_users()
    chat_count = await database.count_chats()

    text = (
        "📊 **Request Accept Bot Statistics**\n\n"
        f"👥 **Total Registered Users:** `{user_count}`\n"
        f"📢 **Connected Chats:** `{chat_count}`\n"
        f"────────────────────────\n"
        f"✅ **Total Requests Approved:** `{stats.get('requests_approved', 0)}`\n"
        f"💌 **Total Welcome DMs Sent:** `{stats.get('dms_sent', 0)}`\n"
        f"⚠️ **Total DMs Failed:** `{stats.get('dms_failed', 0)}`"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="btn_stats")],
        [InlineKeyboardButton("⬅️ Back",    callback_data="btn_start")],
    ])
    await message.reply_text(text, reply_markup=buttons)


# ---------------------------------------------------------------------------
# /broadcast — full rewrite
# ---------------------------------------------------------------------------

async def _safe_edit(status_msg: Message, text: str):
    """Edit a message, silently ignoring MessageNotModified."""
    try:
        await status_msg.edit_text(text)
    except MessageNotModified:
        pass
    except Exception:
        pass


async def broadcast_command(client: Client, message: Message):
    """
    /broadcast [text]
    /bc [text]

    - Owner-only.
    - Without reply: broadcasts the text supplied after the command.
    - With reply: copies the replied-to message (any media type) to every user.
    - Cancellable via /cancelbroadcast.
    - Progress every 5 s. Removes blocked/deactivated users from DB.
    """
    sender_id = message.from_user.id if message.from_user else 0
    if not is_sudo(sender_id):
        await message.reply_text("⛔ Only the Bot Owner can use the broadcast command.")
        return

    # Guard: prevent two simultaneous broadcasts
    if BROADCAST_TASK["active"]:
        await message.reply_text(
            "⚠️ **A broadcast is already running!**\n"
            "Use /cancelbroadcast to stop it first."
        )
        return

    # Determine what to send
    reply_msg    = message.reply_to_message
    text_to_send = None

    if not reply_msg:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply_text(
                "❌ **Provide a message or reply to one.**\n\n"
                "**Usage:**\n"
                "• `/broadcast Hello everyone!`\n"
                "• Reply to any photo/video/text with `/broadcast`"
            )
            return
        text_to_send = parts[1]

    # Fetch target users
    all_users = await database.get_all_broadcast_users()
    total     = len(all_users)

    if total == 0:
        await message.reply_text("ℹ️ No users found in the database to broadcast to.")
        return

    # Activate broadcast
    BROADCAST_TASK["active"] = True
    BROADCAST_TASK["cancel"] = False

    status = await message.reply_text(
        f"🚀 **Broadcast starting...**\n\n"
        f"👥 **Target users:** `{total}`\n"
        f"📡 Sending... please wait."
    )

    sent        = 0
    failed      = 0
    blocked_rm  = 0        # users removed from DB (blocked/deactivated)
    start_time  = time.monotonic()
    last_update = start_time

    for idx, uid in enumerate(all_users, start=1):

        # Cancellation check
        if BROADCAST_TASK["cancel"]:
            break

        # Send the message
        try:
            if reply_msg:
                await reply_msg.copy(chat_id=uid)
            else:
                await client.send_message(chat_id=uid, text=text_to_send)
            sent += 1

        except FloodWait as fw:
            wait = max(int(fw.value), 1)
            config.logger.warning(f"[Broadcast] FloodWait {wait}s on user {uid}")
            await asyncio.sleep(wait)
            # Retry once after wait
            try:
                if reply_msg:
                    await reply_msg.copy(chat_id=uid)
                else:
                    await client.send_message(chat_id=uid, text=text_to_send)
                sent += 1
            except (UserIsBlocked, InputUserDeactivated):
                failed += 1
                blocked_rm += 1
                await database.remove_user(uid)
            except Exception:
                failed += 1

        except (UserIsBlocked, InputUserDeactivated):
            # Remove dead / blocked users from DB automatically
            failed      += 1
            blocked_rm  += 1
            await database.remove_user(uid)

        except (PeerIdInvalid,):
            failed += 1

        except Exception as exc:
            config.logger.warning(f"[Broadcast] Error sending to {uid}: {exc}")
            failed += 1

        # Rate-limit: 0.05 s between sends (≈ 20 msgs/s — safely below Telegram limits)
        await asyncio.sleep(0.05)

        # Progress update every 5 s
        now = time.monotonic()
        if now - last_update >= 5:
            elapsed   = now - start_time
            done      = sent + failed
            rate      = done / elapsed if elapsed > 0 else 1
            remaining = total - done
            eta_secs  = int(remaining / rate) if rate > 0 else 0
            eta_str   = f"{eta_secs // 60}m {eta_secs % 60}s"
            pct       = int(done / total * 100) if total else 0

            await _safe_edit(
                status,
                f"📡 **Broadcasting in Progress...**\n\n"
                f"📤 **Sent:** `{sent}`\n"
                f"❌ **Failed:** `{failed}`\n"
                f"🧹 **Removed (blocked/deactivated):** `{blocked_rm}`\n"
                f"👥 **Total:** `{total}`\n"
                f"📊 **Progress:** `{pct}%` ({done}/{total})\n"
                f"⏳ **ETA:** `{eta_str}`\n\n"
                f"_Use /cancelbroadcast to stop._"
            )
            last_update = now

    # Broadcast finished (or cancelled)
    elapsed_total = time.monotonic() - start_time
    minutes, secs = divmod(int(elapsed_total), 60)
    time_str      = f"{minutes}m {secs}s" if minutes else f"{secs}s"

    cancelled_note = "\n\n⚠️ **Broadcast was cancelled early.**" if BROADCAST_TASK["cancel"] else ""

    await _safe_edit(
        status,
        f"🎉 **Broadcast Completed!**{cancelled_note}\n\n"
        f"📤 **Successfully Sent:** `{sent}`\n"
        f"❌ **Failed / Skipped:** `{failed}`\n"
        f"🧹 **Removed from DB (blocked/inactive):** `{blocked_rm}`\n"
        f"👥 **Total Targeted:** `{total}`\n"
        f"⏱️ **Time Taken:** `{time_str}`"
    )

    # Reset state
    BROADCAST_TASK["active"] = False
    BROADCAST_TASK["cancel"] = False


# ---------------------------------------------------------------------------
# /cancelbroadcast
# ---------------------------------------------------------------------------

async def cancel_broadcast_command(client: Client, message: Message):
    """Sets the cancellation flag for any running broadcast."""
    sender_id = message.from_user.id if message.from_user else 0
    if not is_sudo(sender_id):
        await message.reply_text("⛔ Only the Bot Owner can cancel a broadcast.")
        return

    if not BROADCAST_TASK["active"]:
        await message.reply_text("ℹ️ There is no broadcast currently running.")
        return

    BROADCAST_TASK["cancel"] = True
    await message.reply_text("🛑 **Cancellation signal sent.** The broadcast will stop after the current user.")


# ---------------------------------------------------------------------------
# Callback Query Handler
# ---------------------------------------------------------------------------

async def admin_callback_handler(client: Client, callback: CallbackQuery):
    data = callback.data
    me   = await client.get_me()

    if data == "btn_start":
        mention = callback.from_user.mention
        text    = START_TEXT.format(mention=mention)
        buttons = get_start_buttons(me.username)
        await callback.message.edit_text(text, reply_markup=buttons, disable_web_page_preview=True)
        await callback.answer()

    elif data == "btn_help":
        buttons = get_help_buttons()
        await callback.message.edit_text(HELP_TEXT, reply_markup=buttons, disable_web_page_preview=True)
        await callback.answer()

    elif data == "btn_stats":
        stats      = await database.get_all_stats()
        user_count = await database.count_users()
        chat_count = await database.count_chats()
        text = (
            "📊 **Request Accept Bot Statistics**\n\n"
            f"👥 **Total Registered Users:** `{user_count}`\n"
            f"📢 **Connected Chats:** `{chat_count}`\n"
            f"────────────────────────\n"
            f"✅ **Total Requests Approved:** `{stats.get('requests_approved', 0)}`\n"
            f"💌 **Total Welcome DMs Sent:** `{stats.get('dms_sent', 0)}`\n"
            f"⚠️ **Total DMs Failed:** `{stats.get('dms_failed', 0)}`"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="btn_stats")],
            [InlineKeyboardButton("⬅️ Back",    callback_data="btn_start")],
        ])
        await callback.message.edit_text(text, reply_markup=buttons)
        await callback.answer()

    elif data == "btn_close":
        await callback.message.delete()
        await callback.answer("Closed")


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

def register_admin_handlers(client: Client):
    """Registers all admin-panel commands and callback handlers."""
    client.on_message(filters.command("start"))(start_command)
    client.on_message(filters.command("help"))(help_command)
    client.on_message(filters.command("stats"))(stats_command)
    client.on_message(filters.command(["broadcast", "bc"]))(broadcast_command)
    client.on_message(filters.command(["cancelbroadcast", "cancelbcast"]))(cancel_broadcast_command)
    client.on_callback_query(filters.regex(r"^btn_(start|help|stats|close)$"))(admin_callback_handler)
