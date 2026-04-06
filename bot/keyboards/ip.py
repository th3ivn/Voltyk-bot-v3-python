from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.common import (
    E_CHANGE_IP,
    E_DELETE_IP,
    E_PING_CHECK,
    E_SUPPORT,
    _btn,
    _url_btn_with_emoji,
)


def get_ip_monitoring_keyboard_no_ip() -> InlineKeyboardMarkup:
    """Екран 1А — IP не підключено: кнопка Скасувати (червона)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Скасувати", "ip_cancel_to_settings", style="danger")],
    ])


def get_ip_management_keyboard() -> InlineKeyboardMarkup:
    """Екран 1Б — IP підключено: кнопки керування."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Змінити IP", "ip_change", E_CHANGE_IP),
            _btn("Видалити IP", "ip_delete_confirm", E_DELETE_IP),
        ],
        [_btn("Перевірити пінг", "ip_ping_check", E_PING_CHECK)],
        [
            _btn("← Назад", "back_to_settings"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_change_confirm_keyboard() -> InlineKeyboardMarkup:
    """Екран 2 — Підтвердження зміни IP."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Так", "ip_change_confirm", style="primary"),
            _btn("Скасувати", "ip_cancel_to_management", style="danger"),
        ],
    ])


def get_ip_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    """Екран 3 — Підтвердження видалення IP."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Видалити", "ip_delete_execute", style="danger"),
            _btn("Скасувати", "ip_cancel_to_management", style="primary"),
        ],
    ])


def get_ip_deleted_keyboard() -> InlineKeyboardMarkup:
    """Екран 4 — Після видалення IP."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "back_to_settings"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_saved_keyboard() -> InlineKeyboardMarkup:
    """Екран 5 — Після збереження IP (legacy, backward compatibility)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "back_to_settings"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_saved_success_keyboard() -> InlineKeyboardMarkup:
    """Екран 5 — Після збереження IP, пінг успішний."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "settings_ip"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_saved_fail_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    """Екран 5 — Після збереження IP, пінг не пройшов."""
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Підтримка", support_url, E_SUPPORT)])
    rows.append([
        _btn("← Назад", "settings_ip"),
        _btn("⤴ Меню", "back_to_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_ip_ping_result_keyboard() -> InlineKeyboardMarkup:
    """Екран 6 — Після перевірки пінгу (успіх)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "settings_ip"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_ping_fail_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    """Екран 6 — Після перевірки пінгу (невдача)."""
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Підтримка", support_url, E_SUPPORT)])
    rows.append([
        _btn("← Назад", "settings_ip"),
        _btn("⤴ Меню", "back_to_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_ip_ping_error_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    """Щоденне повідомлення про помилку пінгу — кнопка Підтримка."""
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Підтримка", support_url, E_SUPPORT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
