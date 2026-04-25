from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_schedule_check_time, get_user_by_telegram_id
from bot.formatter.schedule import format_schedule_message
from bot.keyboards.inline import get_test_publication_keyboard
from bot.services.api import fetch_schedule_data, fetch_schedule_image, parse_schedule_for_queue
from bot.states.fsm import ChannelConversationSG
from bot.utils.html_to_entities import append_timestamp, to_aiogram_entities
from bot.utils.logger import get_logger
from bot.utils.telegram import safe_edit_text

logger = get_logger(__name__)
router = Router(name="channel_test")


@router.callback_query(F.data == "channel_test")
async def channel_test(callback: CallbackQuery) -> None:
    await callback.answer()
    await safe_edit_text(callback.message,
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

    # Channel format: same as format_schedule_message with unified live timestamp and without keyboard
    html_text = format_schedule_message(user.region, user.queue, schedule_data)
    last_check = await get_schedule_check_time(session, user.region, user.queue)
    plain_text, raw_entities = append_timestamp(html_text, last_check)
    entities = to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue, schedule_data)

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
        logger.warning("test_schedule failed for user %s: %s", callback.from_user.id, e)
        await callback.answer("❌ Помилка публікації. Спробуйте пізніше.", show_alert=True)


@router.callback_query(F.data == "test_power_on")
async def test_power_on(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.channel_config or not user.channel_config.channel_id:
        await callback.answer("❌ Канал не підключено")
        return
    try:
        text = user.channel_config.power_on_text or "🟢 <b>Світло з'явилось!</b>"
        await callback.bot.send_message(
            user.channel_config.channel_id, text, parse_mode="HTML"
        )
        await callback.answer("✅ Тестове повідомлення опубліковано!")
    except Exception as e:
        logger.warning("test_power_on failed for user %s: %s", callback.from_user.id, e)
        await callback.answer("❌ Помилка. Спробуйте пізніше.", show_alert=True)


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
        logger.warning("test_power_off failed for user %s: %s", callback.from_user.id, e)
        await callback.answer("❌ Помилка. Спробуйте пізніше.", show_alert=True)


@router.callback_query(F.data == "test_custom")
async def test_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ChannelConversationSG.waiting_for_custom_test)
    await safe_edit_text(callback.message,
        "✏️ Своє повідомлення\n\nВведіть текст для публікації в канал:"
    )
