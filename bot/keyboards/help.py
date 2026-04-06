from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.common import (
    E_BOT_SETTINGS,
    E_CHANNEL_SECTION,
    E_DISCUSS,
    E_FAQ,
    E_INSTR_HELP,
    E_INSTRUCTION,
    E_IP_SECTION,
    E_NEWS,
    E_NOTIF_SECTION,
    E_SCHEDULE_SEC,
    E_SUPPORT,
    _btn,
    _url_btn_with_emoji,
)


def get_help_keyboard(faq_url: str | None = None, support_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("Інструкція", "help_instructions", E_INSTR_HELP)],
    ]
    row2: list[InlineKeyboardButton] = []
    if faq_url:
        row2.append(_btn("FAQ", "help_faq", E_FAQ, style="primary"))
    if support_url:
        row2.append(_btn("Підтримка", "help_support", E_SUPPORT, style="primary"))
    if row2:
        rows.append(row2)
    rows.append([
        _url_btn_with_emoji("Новини ↗", "https://t.me/Voltyk_news", E_NEWS),
        _url_btn_with_emoji("Обговорення ↗", "https://t.me/voltyk_chat", E_DISCUSS),
    ])
    rows.append([_btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_faq_keyboard(faq_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if faq_url:
        rows.append([_url_btn_with_emoji("Перейти в FAQ ↗", faq_url, E_FAQ)])
    rows.append([_btn("← Назад", "menu_help"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_support_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Написати адміністратору ↗", support_url, E_SUPPORT)])
    rows.append([_btn("← Назад", "menu_help"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_instructions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Регіон і черга", "instr_region", E_INSTRUCTION),
            _btn("Сповіщення", "instr_notif", E_NOTIF_SECTION),
        ],
        [
            _btn("Канал", "instr_channel", E_CHANNEL_SECTION),
            _btn("IP моніторинг", "instr_ip", E_IP_SECTION),
        ],
        [
            _btn("Графік відключень", "instr_schedule", E_SCHEDULE_SEC),
            _btn("Налаштування бота", "instr_bot_settings", E_BOT_SETTINGS),
        ],
        [_btn("← Назад", "menu_help"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_instruction_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("← Назад", "help_instructions"), _btn("⤴ Меню", "back_to_main")],
    ])
