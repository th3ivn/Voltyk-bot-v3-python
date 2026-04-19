from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import build_channel_notification_message
from bot.keyboards.inline import get_channel_notification_keyboard
from bot.utils.telegram import safe_edit_text

router = Router(name="channel_notifications")


@router.callback_query(F.data == "channel_notifications")
async def channel_notifications(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config:
        return
    cc = user.channel_config
    text = build_channel_notification_message(cc)
    await safe_edit_text(callback.message,
        text,
        reply_markup=get_channel_notification_keyboard(
            schedule=cc.ch_notify_schedule,
            remind_off=cc.ch_notify_remind_off,
            fact_off=cc.ch_notify_fact_off,
            remind_on=cc.ch_notify_remind_on,
            fact_on=cc.ch_notify_fact_on,
            remind_15m=cc.ch_remind_15m,
            remind_30m=cc.ch_remind_30m,
            remind_1h=cc.ch_remind_1h,
        ),
    )
