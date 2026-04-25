from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_setting, set_setting
from bot.keyboards.inline import get_button_emoji_mode_keyboard
from bot.keyboards.common import (
    BUTTON_EMOJI_MODE_SETTING_KEY,
    is_button_custom_emoji_enabled,
    set_button_custom_emoji_enabled,
)
from bot.utils.telegram import safe_edit_text

router = Router(name="admin_button_emoji")


def _admin_only(user_id: int) -> bool:
    return settings.is_admin(user_id)


async def _load_button_emoji_enabled(session: AsyncSession) -> bool:
    raw = await get_setting(session, BUTTON_EMOJI_MODE_SETTING_KEY)
    if raw is None:
        return is_button_custom_emoji_enabled()
    return raw == "true"


@router.callback_query(F.data == "admin_button_emoji")
async def admin_button_emoji(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    enabled = await _load_button_emoji_enabled(session)
    set_button_custom_emoji_enabled(enabled)
    mode_text = "Кастомні (Premium)" if enabled else "Звичайні"
    await safe_edit_text(
        callback.message,
        "😀 <b>Емодзі в кнопках</b>\n\n"
        "Тут можна перемкнути режим відображення емодзі у кнопках:\n"
        "• <b>Кастомні (Premium)</b> — Telegram icon_custom_emoji_id\n"
        "• <b>Звичайні</b> — емодзі тільки у тексті кнопок\n\n"
        f"Поточний режим: <b>{mode_text}</b>",
        reply_markup=get_button_emoji_mode_keyboard(enabled),
    )


@router.callback_query(F.data.startswith("admin_button_emoji_set_"))
async def admin_button_emoji_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return

    mode = callback.data.removeprefix("admin_button_emoji_set_")
    if mode not in ("custom", "regular"):
        await callback.answer("❌ Невідомий режим")
        return

    enabled = mode == "custom"
    current = await _load_button_emoji_enabled(session)
    if enabled == current:
        await callback.answer()
        return

    await set_setting(session, BUTTON_EMOJI_MODE_SETTING_KEY, "true" if enabled else "false")
    await session.commit()
    set_button_custom_emoji_enabled(enabled)

    await callback.answer("✅ Режим емодзі оновлено")
    await callback.message.edit_reply_markup(reply_markup=get_button_emoji_mode_keyboard(enabled))
