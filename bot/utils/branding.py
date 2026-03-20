from __future__ import annotations

CHANNEL_NAME_PREFIX = "СвітлоБот ⚡️ "
CHANNEL_DESCRIPTION_BASE = (
    "⚡️ СвітлоБот — слідкує, щоб ви не слідкували.\n\n"
    "💬 Маєте ідеї або знайшли помилку?"
)

_TITLE_MAX = 128
_DESC_MAX = 255

# Effective input limits for users (accounting for prefix/base added by the bot)
MAX_USER_TITLE_LEN = _TITLE_MAX - len(CHANNEL_NAME_PREFIX)
MAX_USER_DESC_LEN = _DESC_MAX - len(CHANNEL_DESCRIPTION_BASE) - 2  # -2 for "\n\n"


def build_channel_title(user_title: str) -> str:
    return f"{CHANNEL_NAME_PREFIX}{user_title}"[:_TITLE_MAX]


def build_channel_description(user_desc: str | None) -> str | None:
    if not user_desc:
        return None
    return f"{CHANNEL_DESCRIPTION_BASE}\n\n{user_desc}"[:_DESC_MAX]


def get_channel_welcome_message(queue: str) -> str:
    return (
        "👋 Цей канал підключено до СвітлоБота — чат-бота для моніторингу світла.\n\n"
        "Тут публікуватимуться:\n"
        "• 📊 Графіки відключень\n"
        "• ⚡ Сповіщення про стан світла (якщо IP налаштований)\n\n"
        f"Черга: {queue}"
    )
