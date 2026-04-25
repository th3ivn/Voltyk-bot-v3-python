from __future__ import annotations

from bot.keyboards.common import set_button_custom_emoji_enabled
from bot.keyboards.help import get_help_keyboard, get_instructions_keyboard


def _all_button_texts(kb) -> list[str]:
    return [btn.text for row in kb.inline_keyboard for btn in row]


def test_get_help_keyboard_shows_text_emoji_when_custom_disabled():
    set_button_custom_emoji_enabled(False)
    kb = get_help_keyboard(faq_url="https://faq.example.com", support_url="https://support.example.com")
    texts = _all_button_texts(kb)
    assert "📘 Інструкція" in texts
    assert "❓ FAQ" in texts
    assert "💬 Підтримка" in texts
    assert "📰 Новини ↗" in texts
    assert "💬 Обговорення ↗" in texts


def test_get_instructions_keyboard_shows_text_emoji_when_custom_disabled():
    set_button_custom_emoji_enabled(False)
    kb = get_instructions_keyboard()
    texts = _all_button_texts(kb)
    assert "📍 Регіон і черга" in texts
    assert "🔔 Сповіщення" in texts
    assert "📺 Канал" in texts
    assert "📡 IP моніторинг" in texts
    assert "📊 Графік відключень" in texts
    assert "⚙️ Налаштування бота" in texts
