from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.common import (
    E_ALERTS,
    E_BOT_SETTINGS,
    E_CHANNEL,
    E_HELP,
    E_PAUSE_CHANNEL,
    E_RESUME,
    E_SCHEDULE_SEC,
    _btn,
)


def get_main_menu(channel_paused: bool = False, has_channel: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("👀 Графік", "menu_schedule", E_SCHEDULE_SEC),
            _btn("Допомога", "menu_help", E_HELP),
        ],
        [
            _btn("Сповіщення", "settings_alerts", E_ALERTS),
            _btn("Канал", "settings_channel", E_CHANNEL),
        ],
        [_btn("Налаштування", "menu_settings", E_BOT_SETTINGS)],
    ]
    if has_channel:
        if channel_paused:
            rows.append([_btn("Відновити роботу каналу", "channel_resume", E_RESUME)])
        else:
            rows.append([_btn("Тимчасово зупинити канал", "channel_pause", E_PAUSE_CHANNEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_restoration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Відновити налаштування", "restore_profile")],
        [_btn("🆕 Почати заново", "create_new_profile")],
    ])


def get_statistics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⚡ Відключення за тиждень", "stats_week")],
        [_btn("📡 Статус пристрою", "stats_device")],
        [_btn("⚙️ Мої налаштування", "stats_settings")],
        [_btn("⤴ Меню", "back_to_main")],
    ])
