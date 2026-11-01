import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from pyrogram.errors import FloodWait, UserIsBlocked, PeerIdInvalid, InputUserDeactivated
import config
import database
from helpers import is_sudo

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
• 📝 **/setmsg** — Customize the DM welcome message per chat.

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
  Approve all pending join requests waiting in the chat and send each user a Welcome DM!
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
• `/broadcast <msg>` — Send broadcast to all saved bot users.
"""

def get_start_buttons(bot_username: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add to Channel", url=f"https://t.me/{bot_username}?startchannel=true"),
            InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bot_username}?startgroup=true")
        ],
        [
            InlineKeyboardButton("📖 Help & Commands", callback_data="btn_help"),
            InlineKeyboardButton("📊 Bot Stats", callback_data="btn_stats")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="btn_close")
        ]
    ])

def get_help_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Back to Main", callback_data="btn_start"),
            InlineKeyboardButton("📊 Bot Stats", callback_data="btn_stats")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="btn_close")
        ]
    ])

# ==================== /start Command ====================

async def start_command(client: Client, message: Message):
    user = message.from_user
    if user:
        await database.add_or_update_user(user.id, user.first_name or "", user.username or "")

    me = await client.get_me()
    mention = user.mention if user else "Friend"
    text = START_TEXT.format(mention=mention)
    buttons = get_start_buttons(me.username)

    await message.reply_text(text, reply_markup=buttons, disable_web_page_preview=True)

# ==================== /help Command ====================

async def help_command(client: Client, message: Message):
    buttons = get_help_buttons()
    await message.reply_text(HELP_TEXT, reply_markup=buttons, disable_web_page_preview=True)

# ==================== /stats Command ====================

async def stats_command(client: Client, message: Message):
    stats = await database.get_all_stats()
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
        [InlineKeyboardButton("⬅️ Back", callback_data="btn_start")]
    ])
    await message.reply_text(text, reply_markup=buttons)

# ==================== /broadcast Command ====================

async def broadcast_command(client: Client, message: Message):
    """Broadcasts a message to all users who have interacted with the bot."""
    user_id = message.from_user.id if message.from_user else 0
    if not is_sudo(user_id):
        await message.reply_text("⛔ Only the Bot Owner can use broadcast!")
        return

    if not message.reply_to_message and len(message.text.split()) < 2:
        await message.reply_text(
            "❌ **Please provide a message or reply to a message to broadcast.**\n\n"
            "Usage: `/broadcast Hello everyone!` or reply to any photo/text with `/broadcast`."
        )
        return

    all_users = await database.get_all_users()
    total = len(all_users)
    if total == 0:
        await message.reply_text("ℹ️ No users found in database to broadcast to.")
        return

    status = await message.reply_text(f"🚀 **Starting broadcast to {total} users...**")

    sent = 0
    failed = 0
    last_update = time.time()

    for uid in all_users:
        try:
            if message.reply_to_message:
                await message.reply_to_message.copy(chat_id=uid)
            else:
                text_to_send = message.text.split(maxsplit=1)[1]
                await client.send_message(chat_id=uid, text=text_to_send)
            sent += 1
        except FloodWait as f:
            await asyncio.sleep(int(f.value))
            try:
                if message.reply_to_message:
                    await message.reply_to_message.copy(chat_id=uid)
                else:
                    text_to_send = message.text.split(maxsplit=1)[1]
                    await client.send_message(chat_id=uid, text=text_to_send)
                sent += 1
            except Exception:
                failed += 1
        except (UserIsBlocked, PeerIdInvalid, InputUserDeactivated):
            failed += 1
        except Exception:
            failed += 1

        if time.time() - last_update > 4:
            try:
                await status.edit_text(
                    f"📡 **Broadcasting...**\n\n"
                    f"📤 **Sent:** `{sent}`\n"
                    f"❌ **Failed:** `{failed}`\n"
                    f"👥 **Total:** `{total}`"
                )
                last_update = time.time()
            except Exception:
                pass

    await status.edit_text(
        f"🎉 **Broadcast Completed!**\n\n"
        f"📤 **Successfully Sent:** `{sent}`\n"
        f"❌ **Failed:** `{failed}`\n"
        f"👥 **Total Target:** `{total}`"
    )

# ==================== Callback Query Handler ====================

async def admin_callback_handler(client: Client, callback: CallbackQuery):
    data = callback.data
    me = await client.get_me()

    if data == "btn_start":
        mention = callback.from_user.mention
        text = START_TEXT.format(mention=mention)
        buttons = get_start_buttons(me.username)
        await callback.message.edit_text(text, reply_markup=buttons, disable_web_page_preview=True)
        await callback.answer()

    elif data == "btn_help":
        buttons = get_help_buttons()
        await callback.message.edit_text(HELP_TEXT, reply_markup=buttons, disable_web_page_preview=True)
        await callback.answer()

    elif data == "btn_stats":
        stats = await database.get_all_stats()
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
            [InlineKeyboardButton("⬅️ Back", callback_data="btn_start")]
        ])
        await callback.message.edit_text(text, reply_markup=buttons)
        await callback.answer()

    elif data == "btn_close":
        await callback.message.delete()
        await callback.answer("Closed")

def register_admin_handlers(client: Client):
    """Registers admin commands and callbacks."""
    client.on_message(filters.command("start"))(start_command)
    client.on_message(filters.command("help"))(help_command)
    client.on_message(filters.command("stats"))(stats_command)
    client.on_message(filters.command(["broadcast", "bc"]))(broadcast_command)
    client.on_callback_query(filters.regex(r"^btn_(start|help|stats|close)$"))(admin_callback_handler)
