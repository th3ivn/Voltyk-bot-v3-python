from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id

router = Router(name="channel_settings")


@router.callback_query(F.data == "channel_info")
async def channel_info(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        await callback.answer("❌ Канал не підключено")
        return
    cc = user.channel_config
    text = (
        f"📺 Інформація про канал\n\n"
        f"ID: {cc.channel_id}\n"
        f"Назва: {cc.channel_title or '-'}\n"
        f"Статус: {cc.channel_status}"
    )
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data == "channel_disable")
async def channel_disable(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "⚠️ Точно вимкнути публікації?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✓ Так, вимкнути", callback_data="channel_disable_confirm")],
                [InlineKeyboardButton(text="✕ Скасувати", callback_data="settings_channel")],
            ]
        ),
    )


@router.callback_query(F.data == "channel_disable_confirm")
async def channel_disable_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_id = None
        user.channel_config.channel_title = None
        user.channel_config.channel_status = "disconnected"
    await callback.answer("✅ Публікації вимкнено")
    await callback.message.edit_text("✅ Публікації вимкнено")
