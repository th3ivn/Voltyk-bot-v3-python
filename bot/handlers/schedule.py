from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.schedule import format_schedule_message
from bot.formatter.timer import format_next_event_message, format_timer_message
from bot.keyboards.inline import get_main_menu, get_schedule_view_keyboard
from bot.services.api import fetch_schedule_data, fetch_schedule_image, find_next_event, parse_schedule_for_queue

logger = logging.getLogger(__name__)
router = Router(name="schedule")


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("❌ Спочатку запустіть бота, натиснувши /start")
        return

    data = await fetch_schedule_data(user.region)
    if data is None:
        await message.answer("🔄 Не вдалося завантажити. Спробуйте пізніше.")
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_schedule_message(user.region, user.queue, schedule_data, next_event)
    kb = get_schedule_view_keyboard()

    image_bytes = await fetch_schedule_image(user.region, user.queue)
    if image_bytes:
        photo = BufferedInputFile(image_bytes, filename="schedule.png")
        await message.answer_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("next"))
async def cmd_next(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("❌ Спочатку запустіть бота, натиснувши /start")
        return

    data = await fetch_schedule_data(user.region)
    if data is None:
        await message.answer("🔄 Не вдалося завантажити. Спробуйте пізніше.")
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_next_event_message(next_event)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("timer"))
async def cmd_timer(message: Message, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer(
            "❌ Спочатку запустіть бота, натиснувши /start\n\nОберіть наступну дію:",
            reply_markup=get_main_menu(has_channel=False),
        )
        return

    data = await fetch_schedule_data(user.region)
    if data is None:
        await message.answer("🔄 Не вдалося завантажити. Спробуйте пізніше.")
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_timer_message(next_event)
    await message.answer(text, parse_mode="HTML")
