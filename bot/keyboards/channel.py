from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.common import _btn, _url_btn


def get_channel_pending_confirm_keyboard(channel_id: str) -> InlineKeyboardMarkup:
    """Для підтвердження каналу зі сторінки підключення (channel_confirm_)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Так, підключити", f"channel_confirm_{channel_id}", style="success"),
        _btn("Ні", "settings_channel", style="danger"),
    ]])


def get_channel_connect_confirm_keyboard(channel_id: str) -> InlineKeyboardMarkup:
    """Для підтвердження нового каналу (connect_channel_)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Так, підключити", f"connect_channel_{channel_id}", style="success"),
        _btn("Ні", "cancel_channel_connect", style="danger"),
    ]])


def get_channel_replace_confirm_keyboard(channel_id: str) -> InlineKeyboardMarkup:
    """Для підтвердження заміни каналу (replace_channel_)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Так, замінити", f"replace_channel_{channel_id}", style="success"),
        _btn("Залишити", "keep_current_channel", style="danger"),
    ]])


def get_channel_menu_keyboard(
    channel_id: str | None = None, is_public: bool = False,
    channel_username: str | None = None, channel_status: str = "active",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not channel_id:
        rows.append([_btn("✚ Підключити канал", "channel_connect")])
    else:
        if is_public and channel_username:
            rows.append([_url_btn("📺 Відкрити канал", f"https://t.me/{channel_username}")])
        rows.append([_btn("ℹ️ Інфо", "channel_info"), _btn("✏️ Назва", "channel_edit_title")])
        rows.append([_btn("📝 Опис", "channel_edit_description"), _btn("📋 Формат", "channel_format")])
        rows.append([
            _btn("🧪 Тест", "channel_test"),
            _btn("⚙️ Перепідключити", "channel_reconnect") if channel_status == "blocked"
            else _btn("🔴 Вимкнути", "channel_disable"),
        ])
        rows.append([_btn("🔔 Сповіщення", "channel_notifications")])
    rows.append([_btn("← Назад", "back_to_settings"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
