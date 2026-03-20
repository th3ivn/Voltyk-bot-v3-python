from __future__ import annotations

CHANNEL_NAME_PREFIX = "Вольтик ⚡️ "
CHANNEL_DESCRIPTION_BASE = "⚡️ Вольтик — слідкує, щоб ви не слідкували."

_TITLE_MAX = 128
_DESC_MAX = 255

# Effective input limits for users (accounting for prefix/base added by the bot)
MAX_USER_TITLE_LEN = _TITLE_MAX - len(CHANNEL_NAME_PREFIX)
MAX_USER_DESC_LEN = _DESC_MAX - len(CHANNEL_DESCRIPTION_BASE) - 2  # -2 for "\n\n"


def build_channel_title(user_title: str) -> str:
    return f"{CHANNEL_NAME_PREFIX}{user_title}"[:_TITLE_MAX]


def build_channel_description(user_desc: str | None, bot_username: str | None = None) -> str | None:
    if not user_desc:
        return None
    suffix = f"\n@{bot_username}" if bot_username else ""
    return f"{user_desc}\n\n{CHANNEL_DESCRIPTION_BASE}{suffix}"[:_DESC_MAX]


def get_channel_welcome_message(
    queue: str,
    bot_username: str | None = None,
    region: str | None = None,
    has_ip: bool = False,
) -> str:
    if bot_username:
        bot_link = f'<a href="https://t.me/{bot_username}">Вольтика</a>'
    else:
        bot_link = "Вольтика"
    location = f"Регіон: {region}\nЧерга: {queue}" if region else f"Черга: {queue}"
    ip_line = "• ⚡ Сповіщення про стан світла\n" if has_ip else ""
    return (
        f"👋 Цей канал підключено до {bot_link} — чат-бота для моніторингу світла.\n\n"
        "Тут публікуватимуться:\n"
        "• 📊 Графіки відключень\n"
        f"{ip_line}\n"
        f"{location}"
    )
