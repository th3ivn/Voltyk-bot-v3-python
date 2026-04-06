from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import format_live_status_message
from bot.keyboards.inline import get_settings_keyboard
from bot.utils.telegram import safe_delete, safe_edit_text

router = Router(name="menu_settings")


@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    is_admin = app_settings.is_admin(callback.from_user.id)
    text = format_live_status_message(user)

    if callback.message.photo:
        await safe_delete(callback.message)
        await callback.message.answer(text, reply_markup=get_settings_keyboard(is_admin=is_admin), parse_mode="HTML")
    else:
        if not await safe_edit_text(callback.message, text, reply_markup=get_settings_keyboard(is_admin=is_admin)):
            await callback.message.answer(text, reply_markup=get_settings_keyboard(is_admin=is_admin), parse_mode="HTML")
