from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.keyboards.inline import get_channel_menu_keyboard

router = Router(name="settings_channel")


@router.callback_query(F.data == "settings_channel")
async def settings_channel(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    cc = user.channel_config
    channel_id = cc.channel_id if cc else None
    channel_status = cc.channel_status if cc else "active"
    channel_title = cc.channel_title if cc else None

    status_text = ""
    if channel_id:
        status_text = f"\n📺 Канал: {channel_title or channel_id}"
        if channel_status == "blocked":
            status_text += " (заблоковано)"
        elif channel_status == "active":
            status_text += " ✅"

    await callback.message.edit_text(
        f"📺 Налаштування каналу{status_text}",
        reply_markup=get_channel_menu_keyboard(
            channel_id=channel_id,
            channel_status=channel_status,
        ),
    )


@router.callback_query(F.data == "channel_reconnect")
async def channel_reconnect(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer("✅ Канал розблоковано!")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.channel_config:
        user.channel_config.channel_status = "active"
        user.channel_config.channel_guard_warnings = 0
