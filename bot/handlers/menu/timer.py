from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.db.queries import get_user_by_telegram_id
from bot.formatter.timer import format_timer_popup
from bot.services.api import fetch_schedule_data, find_next_event, parse_schedule_for_queue

router = Router(name="menu_timer")


@router.callback_query(F.data == "menu_timer")
async def menu_timer(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Спочатку запустіть бота")
        return

    data = await fetch_schedule_data(user.region)
    if data is None:
        await callback.answer("⚠️ Дані тимчасово недоступні")
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_timer_popup(next_event, schedule_data)
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith("timer_"))
async def timer_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id_str = callback.data.replace("timer_", "")
    try:
        user_pk = int(user_id_str)
    except ValueError:
        await callback.answer()
        return
    result = await session.execute(select(User).where(User.id == user_pk))
    user = result.scalars().first()
    if not user:
        await callback.answer("❌ Користувач не знайдений")
        return

    data = await fetch_schedule_data(user.region)
    if not data:
        await callback.answer("⚠️ Дані тимчасово недоступні")
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_timer_popup(next_event, schedule_data)
    await callback.answer(text, show_alert=True)
