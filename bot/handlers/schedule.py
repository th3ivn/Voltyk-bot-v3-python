from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.db.queries import get_schedule_check_time, get_user_by_telegram_id
from bot.formatter.schedule import format_schedule_message
from bot.formatter.timer import format_next_event_message, format_timer_message
from bot.keyboards.inline import get_main_menu, get_schedule_view_keyboard
from bot.services.api import fetch_schedule_data, fetch_schedule_image, find_next_event, parse_schedule_for_queue
from bot.utils.html_to_entities import append_timestamp, to_aiogram_entities
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="schedule")


async def _get_user_and_data(
    message: Message,
    session: AsyncSession,
) -> tuple[User, list] | None:
    """Fetch the registered user and their schedule data.

    Sends an appropriate error reply and returns None if either lookup fails.
    """
    if not message.from_user:
        return None
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("❌ Спочатку запустіть бота, натиснувши /start")
        return None

    data = await fetch_schedule_data(user.region)
    if data is None:
        await message.answer("🔄 Не вдалося завантажити. Спробуйте пізніше.")
        return None

    return user, data


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, session: AsyncSession) -> None:
    result = await _get_user_and_data(message, session)
    if result is None:
        return
    user, data = result

    schedule_data = parse_schedule_for_queue(data, user.queue)
    html_text = format_schedule_message(user.region, user.queue, schedule_data)
    kb = get_schedule_view_keyboard()

    now_unix = await get_schedule_check_time(session, user.region, user.queue)
    plain_text, raw_entities = append_timestamp(html_text, now_unix)
    entities = to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue, schedule_data)
    if image_bytes:
        photo = BufferedInputFile(image_bytes, filename="schedule.png")
        await message.answer_photo(
            photo=photo, caption=plain_text, caption_entities=entities, reply_markup=kb, parse_mode=None
        )
    else:
        await message.answer(plain_text, entities=entities, reply_markup=kb, parse_mode=None)


@router.message(Command("next"))
async def cmd_next(message: Message, session: AsyncSession) -> None:
    result = await _get_user_and_data(message, session)
    if result is None:
        return
    user, data = result

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_next_event_message(next_event)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("timer"))
async def cmd_timer(message: Message, session: AsyncSession) -> None:
    if not message.from_user:
        return
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
