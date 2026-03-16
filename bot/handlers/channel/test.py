from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.formatter.schedule import format_schedule_message
from bot.keyboards.inline import get_test_publication_keyboard
from bot.services.api import fetch_schedule_data, fetch_schedule_image, find_next_event, parse_schedule_for_queue
from bot.states.fsm import ChannelConversationSG
from bot.utils.html_to_entities import html_to_entities, to_aiogram_entities
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="channel_test")


@router.callback_query(F.data == "channel_test")
async def channel_test(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "🧪 Тест публікації\n\nЩо опублікувати в канал?",
        reply_markup=get_test_publication_keyboard(),
    )


@router.callback_query(F.data == "test_schedule")
async def test_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config or not user.channel_config.channel_id:
        await callback.answer("❌ Канал не підключено")
        return

    data = await fetch_schedule_data(user.region)
    if not data:
        await callback.answer("❌ Дані недоступні")
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)

    # Channel format: same as format_schedule_message but without timestamp and without keyboard
    html_text = format_schedule_message(user.region, user.queue, schedule_data, next_event)
    plain_text, raw_entities = html_to_entities(html_text)
    entities = to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue)

    try:
        if image_bytes:
            photo = BufferedInputFile(image_bytes, filename="schedule.png")
            await callback.bot.send_photo(
                user.channel_config.channel_id,
                photo=photo,
                caption=plain_text,
                caption_entities=entities,
                parse_mode=None,
            )
        else:
            await callback.bot.send_message(
                user.channel_config.channel_id,
                plain_text,
                entities=entities,
                parse_mode=None,
            )
        await callback.answer("✅ Графік опубліковано в канал!")
    except Exception as e:
        await callback.answer(f"❌ Помилка публікації: {e}")


@router.callback_query(F.data == "test_power_on")
async def test_power_on(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config or not user.channel_config.channel_id:
        await callback.answer("❌ Канал не підключено")
        return
    try:
        text = user.channel_config.power_on_text or '<tg-emoji emoji-id="5309771882252243514">🟢</tg-emoji> <b>Світло з\'явилось!</b>'
        await callback.bot.send_message(
            user.channel_config.channel_id, text, parse_mode="HTML"
        )
        await callback.answer("✅ Тестове повідомлення опубліковано!")
    except Exception as e:
        await callback.answer(f"❌ Помилка: {e}")


@router.callback_query(F.data == "test_power_off")
async def test_power_off(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config or not user.channel_config.channel_id:
        await callback.answer("❌ Канал не підключено")
        return
    try:
        text = user.channel_config.power_off_text or "🔴 <b>Світло зникло!</b>"
        await callback.bot.send_message(
            user.channel_config.channel_id, text, parse_mode="HTML"
        )
        await callback.answer("✅ Тестове повідомлення опубліковано!")
    except Exception as e:
        await callback.answer(f"❌ Помилка: {e}")


@router.callback_query(F.data == "test_custom")
async def test_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_custom_test)
    await callback.message.edit_text(
        "✏️ Своє повідомлення\n\nВведіть текст для публікації в канал:"
    )
