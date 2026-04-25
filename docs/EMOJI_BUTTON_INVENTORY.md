# Emoji inventory for bot keyboard buttons

This document lists the button text emoji currently used across keyboard screens,
plus Telegram custom emoji constants (`E_*`) used for `icon_custom_emoji_id`.

## Text emoji in button captions (by keyboard module)

- `bot/keyboards/admin.py`:
  `📊 👥 📢 ⚙️ 📡 🔧 ← ⤴ 📈 💻 ⏱ ⏸ ⏸️ 🔄 🖼 😀 🗑 ✨ 🙂 ✅ 👁 💡 ⚡ 🚫 🟢 🔴 ✏️ 📋 🏷 📜 ❌ 🎯 🔐 📝`
- `bot/keyboards/channel.py`:
  `✚ 📺 ℹ️ ✏️ 📝 📋 🧪 ⚙️ 🔴 🔔 ← ⤴`
- `bot/keyboards/common.py`:
  `← ⤴ 🔄`
- `bot/keyboards/format.py`:
  `📊 ⚡ ← ⤴ 📝 🔴 🟢 🔄 📴 ✏️`
- `bot/keyboards/help.py`:
  `← ⤴`
- `bot/keyboards/ip.py`:
  `← ⤴`
- `bot/keyboards/main_menu.py`:
  `👀 🔄 🆕 ⚡ 📡 ⚙️ ⤴`
- `bot/keyboards/notifications.py`:
  `← ✓ 📍 ⤴ 🔴 🟢 📊 ⏰ ⚡ 📡 📱 📺 📱📺`
- `bot/keyboards/schedule.py`:
  `⤴`
- `bot/keyboards/settings.py`:
  `🗑 ⤴ ⌨️ 💬 ← ✓ ✕`
- `bot/keyboards/wizard.py`:
  `← ✓ 🔄 ⤴ 📱 📺`

## Custom button emoji constants (`icon_custom_emoji_id`)

Defined in `bot/keyboards/common.py` as `E_*` constants:

`E_SCHEDULE, E_HELP, E_STATS, E_TIMER, E_SETTINGS, E_RESUME, E_PAUSE_CHANNEL, E_REGION, E_REFRESH, E_IP, E_CHANNEL, E_ALERTS, E_ADMIN, E_DELETE_DATA, E_SCHEDULE_CHANGES, E_BOT_NOTIF, E_FACT, E_CONFIRM_CHANGE, E_CANCEL, E_WELCOME, E_CHECK, E_WARN, E_QUEUE, E_BELL, E_HOURGLASS, E_IP_SETTINGS, E_IP_ADDR, E_ONLINE, E_OFFLINE, E_CHANGE_IP, E_DELETE_IP, E_PING_CHECK, E_PING_LOADING, E_SUCCESS, E_ERROR_PING, E_PING_FAIL, E_SUPPORT, E_REPLY, E_INSTRUCTION, E_INSTR_HELP, E_FAQ, E_NOTIF_SECTION, E_CHANNEL_SECTION, E_IP_SECTION, E_SCHEDULE_SEC, E_BOT_SETTINGS, E_NEWS, E_DISCUSS`.

## Admin toggle related buttons

The admin switch UI introduced for custom-vs-regular mode uses:
- `😀 Емодзі кнопок`
- `✨ Кастомні (Premium)`
- `🙂 Звичайні`


## Fallback behavior (regular mode)

When `button_custom_emoji_enabled=false`, button helpers now prefix plain labels
with a standard emoji based on the `E_*` id mapping in `bot/keyboards/common.py`
so menus (including main menu) always show visible emoji even without premium custom icons.
