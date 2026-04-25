from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.common import (
    E_ADMIN,
    E_CHANNEL_SECTION,
    E_DELETE_DATA,
    E_IP_SECTION,
    E_NOTIF_SECTION,
    _btn,
)


def get_settings_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("🌍 Регіон", "settings_region"),
            _btn("IP", "settings_ip", E_IP_SECTION),
        ],
        [
            _btn("Канал", "settings_channel", E_CHANNEL_SECTION),
            _btn("Сповіщення", "settings_alerts", E_NOTIF_SECTION),
        ],
        [_btn("🧹 Очищення повідомлень", "settings_cleanup")],
    ]
    if is_admin:
        rows.append([_btn("Адмін-панель", "settings_admin", E_ADMIN)])
    rows.append([_btn("Видалити мої дані", "settings_delete_data", E_DELETE_DATA)])
    rows.append([_btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_cleanup_keyboard(auto_delete_commands: bool = False, auto_delete_bot_messages: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⌨️ Видаляти команди", "cleanup_toggle_commands", style="success" if auto_delete_commands else None)],
        [_btn("💬 Видаляти старі відповіді", "cleanup_toggle_messages", style="success" if auto_delete_bot_messages else None)],
        [_btn("← Назад", "back_to_settings"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_delete_data_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Скасувати", "back_to_settings"), _btn("Продовжити", "delete_data_step2")],
    ])


def get_delete_data_final_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Ні", "back_to_settings"), _btn("Так, видалити", "confirm_delete_data", E_DELETE_DATA)],
    ])


def get_deactivate_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✓ Так, деактивувати", "confirm_deactivate")],
        [_btn("✕ Скасувати", "back_to_settings")],
    ])
