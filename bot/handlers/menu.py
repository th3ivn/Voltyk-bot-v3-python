from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import get_user_by_telegram_id
from bot.formatter.messages import format_live_status_message, format_main_menu_message
from bot.formatter.schedule import format_schedule_message
from bot.formatter.timer import format_timer_popup
from bot.keyboards.inline import (
    get_error_keyboard,
    get_help_keyboard,
    get_main_menu,
    get_schedule_view_keyboard,
    get_settings_keyboard,
    get_statistics_keyboard,
)
from bot.services.api import fetch_schedule_data, fetch_schedule_image, find_next_event, parse_schedule_for_queue

logger = logging.getLogger(__name__)
router = Router(name="menu")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return

    text = format_main_menu_message(user)
    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
    kb = get_main_menu(channel_paused=channel_paused, has_channel=has_channel)
    try:
        await callback.message.delete()
    except Exception:
        pass
    msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    user.last_menu_message_id = msg.message_id


async def _send_schedule(callback: CallbackQuery, user, edit: bool = False) -> None:
    """Fetch and send schedule as photo with caption (like the old bot)."""
    data = await fetch_schedule_data(user.region)
    if data is None:
        if edit:
            try:
                await callback.message.edit_text(
                    "😅 Щось пішло не так. Спробуйте ще раз!", reply_markup=get_error_keyboard()
                )
            except Exception:
                await callback.message.answer(
                    "😅 Щось пішло не так. Спробуйте ще раз!", reply_markup=get_error_keyboard()
                )
        else:
            await callback.message.answer(
                "😅 Щось пішло не так. Спробуйте ще раз!", reply_markup=get_error_keyboard()
            )
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    text = format_schedule_message(user.region, user.queue, schedule_data, next_event)
    kb = get_schedule_view_keyboard()

    image_bytes = await fetch_schedule_image(user.region, user.queue)

    if image_bytes:
        photo = BufferedInputFile(image_bytes, filename="schedule.png")
        if edit and callback.message.photo:
            try:
                media = InputMediaPhoto(media=photo, caption=text, parse_mode="HTML")
                await callback.message.edit_media(media=media, reply_markup=kb)
                return
            except Exception as e:
                logger.warning("Failed to edit media: %s", e)

        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        if edit and not callback.message.photo:
            try:
                await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception as e:
                logger.warning("Failed to edit text: %s", e)

        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "menu_schedule")
async def menu_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    await _send_schedule(callback, user, edit=False)


@router.callback_query(F.data == "schedule_refresh")
async def schedule_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Користувача не знайдено")
        return
    await callback.answer("🔄 Оновлюю...")
    await _send_schedule(callback, user, edit=True)


@router.callback_query(F.data == "my_queues")
async def change_queue(callback: CallbackQuery, session: AsyncSession) -> None:
    from bot.keyboards.inline import get_region_keyboard

    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Оберіть свій регіон:", reply_markup=get_region_keyboard())


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


@router.callback_query(F.data == "menu_stats")
async def menu_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("📊 Статистика", reply_markup=get_statistics_keyboard())


@router.callback_query(F.data.in_({"stats_week", "stats_device", "stats_settings"}))
async def stats_detail(callback: CallbackQuery) -> None:
    await callback.answer("⚠️ Ця функція в розробці", show_alert=True)


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    from bot.db.queries import get_setting

    support_url = await get_setting(session, "support_url")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "❓ Допомога\n\nℹ️ Тут ви можете дізнатися як\nкористуватися ботом.",
        reply_markup=get_help_keyboard(support_url=support_url),
    )


@router.callback_query(F.data == "help_howto")
async def help_howto(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        "📖 Як користуватися ботом:\n\n"
        "1. Оберіть регіон і чергу\n"
        "2. Увімкніть сповіщення\n"
        "3. (Опціонально) Підключіть канал\n"
        "4. (Опціонально) Налаштуйте IP моніторинг\n\n"
        "Бот автоматично сповістить про:\n"
        "• Зміни в графіку\n"
        "• Фактичні відключення (з IP)"
    )
    from bot.keyboards.inline import get_help_keyboard

    try:
        await callback.message.edit_text(text, reply_markup=get_help_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_help_keyboard())


@router.callback_query(F.data == "help_faq")
async def help_faq(callback: CallbackQuery) -> None:
    text = (
        "❓ Чому не приходять сповіщення?\n"
        "→ Перевірте налаштування\n\n"
        "❓ Як працює IP моніторинг?\n"
        "→ Бот пінгує роутер для визначення наявності світла"
    )
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    is_admin = app_settings.is_admin(callback.from_user.id)
    text = format_live_status_message(user)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        text, reply_markup=get_settings_keyboard(is_admin=is_admin), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("timer_"))
async def timer_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id_str = callback.data.replace("timer_", "")
    from sqlalchemy import select

    from bot.db.models import User

    result = await session.execute(select(User).where(User.id == int(user_id_str)))
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
