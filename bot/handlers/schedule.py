from __future__ import annotations

import logging
import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message, MessageEntity
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.schedule import format_schedule_message
from bot.formatter.timer import format_next_event_message, format_timer_message
from bot.keyboards.inline import get_main_menu, get_schedule_view_keyboard
from bot.services.api import fetch_schedule_data, fetch_schedule_image, find_next_event, parse_schedule_for_queue
from bot.utils.html_to_entities import append_timestamp

logger = logging.getLogger(__name__)
router = Router(name="schedule")


def _to_aiogram_entities(raw: list[dict]) -> list[MessageEntity]:
    result = []
    for e in raw:
        params = {"type": e["type"], "offset": e["offset"], "length": e["length"]}
        for key in ("url", "custom_emoji_id", "unix_time", "date_time_format"):
            if key in e:
                params[key] = e[key]
        result.append(MessageEntity(**params))
    return result


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
    html_text = format_schedule_message(user.region, user.queue, schedule_data, next_event)
    kb = get_schedule_view_keyboard()

    now_unix = int(time.time())
    plain_text, raw_entities = append_timestamp(html_text, now_unix)
    entities = _to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue)
    if image_bytes:
        photo = BufferedInputFile(image_bytes, filename="schedule.png")
        await message.answer_photo(
            photo=photo, caption=plain_text, caption_entities=entities, reply_markup=kb
        )
    else:
        await message.answer(plain_text, entities=entities, reply_markup=kb)


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
