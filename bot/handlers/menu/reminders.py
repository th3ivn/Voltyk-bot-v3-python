from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import format_main_menu_message
from bot.keyboards.inline import get_main_menu

from .schedule import _send_schedule_photo

router = Router(name="menu_reminders")


@router.callback_query(F.data == "reminder_dismiss")
async def reminder_dismiss(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    text = format_main_menu_message(user)
    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
    kb = get_main_menu(channel_paused=channel_paused, has_channel=has_channel)
    msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    user.last_menu_message_id = msg.message_id


@router.callback_query(F.data == "reminder_show_schedule")
async def reminder_show_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Спочатку запустіть бота /start", show_alert=True)
        return
    await _send_schedule_photo(callback, user, session, edit_photo=False)
