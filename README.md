# 🤖 REQBOT - Telegram Join Request Acceptor & Channel Manager

A high-performance, modern Telegram bot built with **Pyrogram** that automatically accepts join requests, sends personalized welcome DMs to each accepted user, and provides powerful administrative bulk commands (`/acceptall`, `/kickall`, `/banall`, `/unbanall`).

---

## ✨ Features

- ⚡ **Instant Auto-Acceptance**: Accepts join requests in real time when users request to join any channel or group.
- 💌 **Automatic Welcome DM**: Sends a personalized private message (DM) to each user immediately after their request is approved.
- ⏩ **/acceptall (`/approveall`)**: Approves all pending join requests waiting in the chat from before, sending each accepted user their welcome DM!
- 👢 **/kickall**: Safely removes all regular group members without permanently banning them (Admins & Bots are protected!).
- ⛔ **/banall**: Safely bans all regular group members (Admins & Bots are protected!).
- 🔓 **/unbanall**: Unbans all banned users in bulk from the channel or group.
- 🛑 **/cancel**: Aborts any running bulk operation at any time.
- 📝 **Customizable Welcome Messages**:
  - Dynamic placeholders: `{name}`, `{mention}`, `{username}`, `{chat_title}`, `{chat_id}`, `{user_id}`.
  - Per-chat custom templates via `/setmsg`, `/getmsg`, `/resetmsg`, and `/previewmsg`.
- ⚙️ **/toggleauto**: Easily toggle auto-approval ON or OFF per chat.
- 🛡️ **FloodWait & Error Protection**: Gracefully handles Telegram rate limits, closed DMs, and restricted users.
- 📊 **Stats & Broadcast**: Track approved users and broadcast updates to your community.
- 💾 **Dual Database Engine**: Zero-configuration local SQLite (`reqbot.db`) out-of-the-box, with optional MongoDB cloud support.

---

## 📋 Commands List

| Command | Location | Description |
| :--- | :--- | :--- |
| `/start` | Private | Welcome screen, bot information, and quick setup buttons |
| `/help` | Any | Full help manual and permission requirements |
| `/acceptall` | Group / Channel / DM | Accepts all existing pending join requests and sends them DMs |
| `/kickall` | Group / DM | Kicks all regular members (protected against bots/admins) |
| `/banall` | Group / DM | Bans all regular members (protected against bots/admins) |
| `/unbanall` | Group / Channel / DM | Unbans all banned users in the chat |
| `/cancel` | Group / Channel / DM | Cancels any ongoing bulk operation |
| `/toggleauto` | Group / DM | Toggles automatic acceptance ON/OFF for that chat |
| `/setmsg <text>` | Private (Owner) | Sets the single global welcome DM message for all chats |
| `/getmsg` | Private (Owner) | Displays the current global welcome DM template |
| `/previewmsg` | Private / Any | Live test-preview of how the DM looks to users |
| `/resetmsg` | Private (Owner) | Resets global DM template back to default (.env) |
| `/stats` | Private | View real-time bot statistics and counters |
| `/broadcast <msg>` | Private (Owner) | Broadcast a message to all bot users |

> 💡 **Channel Tip**: Since channels do not allow regular chat commands, you can run commands like `/acceptall` in private chat with the bot by specifying the chat ID or username (e.g., `/acceptall -1001234567890`).

---

## 🛠️ Step-by-Step Setup Guide

### 1. Obtain Your Telegram Credentials

1. **API_ID & API_HASH**:
   - Go to [https://my.telegram.org](https://my.telegram.org) and log in with your phone number.
   - Click on **API development tools**.
   - Create a new app (any title/short name) and copy your **`api_id`** and **`api_hash`**.

2. **BOT_TOKEN**:
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Send `/newbot`, choose a name and username ending in `bot`.
   - Copy the **`HTTP API token`**.

3. **OWNER_ID**:
   - Message [@userinfobot](https://t.me/userinfobot) or [@MissRose_bot](https://t.me/MissRose_bot) (`/id`) to get your numeric Telegram User ID.

---

### 2. Configure Environment

Open the `.env` file in the `REQBOT` folder and fill in your values:

```env
API_ID=12345678
API_HASH=your_api_hash_here
BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRstuVWXyz
OWNER_ID=987654321

# Optional: MongoDB URI (leave empty to use local SQLite)
MONGO_URI=

# Optional: Log Channel ID (e.g. -1001234567890)
LOG_CHANNEL=
```

---

### 3. Install Dependencies & Run

Open a terminal or command prompt inside the `REQBOT` folder:

```bash
# Install requirements (if not already installed)
pip install -r requirements.txt

# Start REQBOT
python bot.py
```

---

## 📢 How to Setup Join Requests in Telegram

For the bot to receive and accept join requests:

1. **Add the Bot as Admin**:
   - Add the bot to your **Channel** or **Group**.
   - Promote it to **Administrator**.
   - Ensure the following permissions are granted:
     - ✅ **Invite Users via Link** (or "Add Members") — *Required for join requests*
     - ✅ **Ban Users** — *Required for /kickall, /banall, /unbanall*

2. **Create an Approval Invite Link**:
   - Go to your Channel or Group Settings ➔ **Invite Links**.
   - Click **Create a New Link**.
   - Enable **"Request Admin Approval"** (or "Require Admin Approval").
   - Share this link! Whenever a user clicks it, REQBOT will instantly accept them and send them a private DM! 🚀

---

## 📝 Setting the Single Global Welcome DM (Bot Owner)

There is a **single global welcome message** configured by the **Bot Owner**. Every time a join request is accepted in **any group or channel** (either automatically or via `/acceptall`), this exact message is formatted and sent directly in DM to the user.

### Setting via Telegram Command:
In private chat with the bot, the Bot Owner can run:

```text
/setmsg 👋 Welcome {mention}!
🎉 Your request to join **{chat_title}** has been approved!
Welcome to our community! 🚀
```

- `/getmsg` — View current active global template.
- `/previewmsg` — Test how the message looks with real formatting.
- `/resetmsg` — Revert back to the default message in `.env`.

### Supported Dynamic Placeholders:
- `{name}` — User's first name
- `{mention}` — Clickable user mention link
- `{username}` — User's username (or name if no username)
- `{chat_title}` — Name of the channel or group joined
- `{chat_id}` — ID of the channel or group
- `{user_id}` — Telegram ID of the user
