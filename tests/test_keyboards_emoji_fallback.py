from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.admin import get_button_emoji_mode_keyboard
from bot.keyboards.common import _btn, is_button_custom_emoji_enabled, set_button_custom_emoji_enabled
from bot.keyboards.help import get_help_keyboard
from bot.keyboards.ip import get_ip_management_keyboard
from bot.keyboards.main_menu import get_main_menu
from bot.keyboards.notifications import get_notification_main_keyboard
from bot.keyboards.settings import get_settings_keyboard


def _find_button_text(kb: InlineKeyboardMarkup, callback_data: str) -> str:
    for row in kb.inline_keyboard:
        for btn in row:
            if getattr(btn, "callback_data", None) == callback_data:
                return btn.text
    raise AssertionError(f"button not found: {callback_data}")


def test_regular_mode_has_text_fallback_on_all_core_screens() -> None:
    set_button_custom_emoji_enabled(False)

    assert _find_button_text(get_main_menu(), "menu_help").startswith("❓ ")
    assert _find_button_text(get_settings_keyboard(is_admin=True), "settings_alerts").startswith("🔔 ")
    assert _find_button_text(get_help_keyboard(support_url="https://example.com"), "help_support").startswith("💬 ")
    assert _find_button_text(get_notification_main_keyboard(), "notif_toggle_schedule").startswith("📈 ")
    assert _find_button_text(get_ip_management_keyboard(), "ip_ping_check").startswith("📶 ")
    assert _find_button_text(get_button_emoji_mode_keyboard(), "admin_button_emoji_set_custom").startswith("✨ ")


def test_regular_mode_does_not_duplicate_existing_leading_emoji() -> None:
    set_button_custom_emoji_enabled(False)

    btn = _btn("❓ Допомога", "menu_help", emoji_id="5443038326535759644")
    assert btn.text == "❓ Допомога"


def test_custom_mode_keeps_icon_custom_emoji_id_without_text_prefix() -> None:
    set_button_custom_emoji_enabled(True)

    btn = _btn("Допомога", "menu_help", emoji_id="5443038326535759644")
    assert is_button_custom_emoji_enabled() is True
    assert btn.text == "Допомога"
    assert getattr(btn, "icon_custom_emoji_id", None) == "5443038326535759644"
