from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.common import _btn


def get_format_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Графік відключень", "format_schedule_settings")],
        [_btn("⚡ Фактичний стан", "format_power_settings")],
        [_btn("← Назад", "settings_channel"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_format_schedule_keyboard(delete_old: bool = False, picture_only: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📝 Налаштувати текст графіка", "format_schedule_text")],
        [_btn("Видаляти старий графік", "format_toggle_delete", style="success" if delete_old else None)],
        [_btn("Без тексту (тільки картинка)", "format_toggle_piconly", style="success" if picture_only else None)],
        [_btn("← Назад", "format_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_format_power_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn('🔴 Повідомлення "Світло зникло"', "format_power_off")],
        [_btn('🟢 Повідомлення "Світло є"', "format_power_on")],
        [_btn("🔄 Скинути все до стандартних", "format_reset_all_power")],
        [_btn("← Назад", "format_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_test_publication_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Графік відключень", "test_schedule")],
        [_btn("⚡ Фактичний стан (світло є)", "test_power_on")],
        [_btn("📴 Фактичний стан (світла немає)", "test_power_off")],
        [_btn("✏️ Своє повідомлення", "test_custom")],
        [_btn("← Назад", "settings_channel"), _btn("⤴ Меню", "back_to_main")],
    ])
