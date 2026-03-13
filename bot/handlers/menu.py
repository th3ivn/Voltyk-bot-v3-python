from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto, MessageEntity
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import get_schedule_check_time, get_user_by_telegram_id
from bot.formatter.messages import format_live_status_message, format_main_menu_message
from bot.formatter.schedule import format_schedule_message
from bot.formatter.timer import format_timer_popup
from bot.keyboards.inline import (
    get_error_keyboard,
    get_help_keyboard,
    get_main_menu,
    get_region_keyboard,
    get_schedule_view_keyboard,
    get_settings_keyboard,
    get_statistics_keyboard,
)
from bot.services.api import fetch_schedule_data, fetch_schedule_image, find_next_event, parse_schedule_for_queue
from bot.states.fsm import WizardSG
from bot.utils.html_to_entities import append_timestamp

logger = logging.getLogger(__name__)
router = Router(name="menu")

_MSG_NOT_MODIFIED = "message is not modified"


def _to_aiogram_entities(raw_entities: list[dict]) -> list[MessageEntity]:
    result = []
    for e in raw_entities:
        params = {
            "type": e["type"],
            "offset": e["offset"],
            "length": e["length"],
        }
        if "url" in e:
            params["url"] = e["url"]
        if "custom_emoji_id" in e:
            params["custom_emoji_id"] = e["custom_emoji_id"]
        if "unix_time" in e:
            params["unix_time"] = e["unix_time"]
        if "date_time_format" in e:
            params["date_time_format"] = e["date_time_format"]
        result.append(MessageEntity(**params))
    return result


async def _safe_edit_text(message, text: str, reply_markup=None, parse_mode="HTML") -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except Exception as e:
        if _MSG_NOT_MODIFIED in str(e):
            return True
        return False


async def _safe_delete(message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await _safe_edit_text(callback.message, "❌ Спочатку запустіть бота, натиснувши /start")
        return

    # Delete previous menu message if it exists and differs from the current one
    if user.last_menu_message_id and user.last_menu_message_id != callback.message.message_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, user.last_menu_message_id)
        except Exception:
            pass

    text = format_main_menu_message(user)
    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
    kb = get_main_menu(channel_paused=channel_paused, has_channel=has_channel)

    if callback.message.photo:
        await _safe_delete(callback.message)
        msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        if await _safe_edit_text(callback.message, text, reply_markup=kb):
            msg = callback.message
        else:
            msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    user.last_menu_message_id = msg.message_id


async def _send_schedule_photo(callback: CallbackQuery, user, session: AsyncSession, edit_photo: bool = False) -> None:
    """Send schedule as photo with live timestamp entities.

    edit_photo=True → try editMessageMedia first (no flicker), fallback to delete+send.
    edit_photo=False → always delete+send (initial show from menu).
    """
    data = await fetch_schedule_data(user.region)
    if data is None:
        await callback.message.answer(
            "😅 Щось пішло не так. Спробуйте ще раз!", reply_markup=get_error_keyboard()
        )
        return

    schedule_data = parse_schedule_for_queue(data, user.queue)
    next_event = find_next_event(schedule_data)
    html_text = format_schedule_message(user.region, user.queue, schedule_data, next_event)
    kb = get_schedule_view_keyboard()

    last_check = await get_schedule_check_time(session, user.region, user.queue)
    plain_text, raw_entities = append_timestamp(html_text, last_check)
    entities = _to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue)

    if image_bytes:
        photo = BufferedInputFile(image_bytes, filename="schedule.png")
        if edit_photo:
            # Try editMessageMedia first (no flicker)
            try:
                media = InputMediaPhoto(media=photo, caption=plain_text, caption_entities=entities, parse_mode=None)
                await callback.message.edit_media(media=media, reply_markup=kb)
                return
            except Exception as e:
                if _MSG_NOT_MODIFIED in str(e):
                    return
                logger.warning("edit_media failed, falling back to delete+send: %s", e)
        # Fallback: delete + send new
        await _safe_delete(callback.message)
        await callback.message.answer_photo(
            photo=photo, caption=plain_text, caption_entities=entities, reply_markup=kb, parse_mode=None
        )
    else:
        if edit_photo:
            # Try edit text
            try:
                await callback.message.edit_text(plain_text, entities=entities, reply_markup=kb, parse_mode=None)
                return
            except Exception as e:
                if _MSG_NOT_MODIFIED in str(e):
                    return
                logger.warning("edit_text failed, falling back to delete+send: %s", e)
        await _safe_delete(callback.message)
        await callback.message.answer(plain_text, entities=entities, reply_markup=kb, parse_mode=None)


@router.callback_query(F.data == "menu_schedule")
async def menu_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await _safe_edit_text(callback.message, "❌ Спочатку запустіть бота, натиснувши /start")
        return
    await _send_schedule_photo(callback, user, session, edit_photo=True)


@router.callback_query(F.data == "schedule_refresh")
async def schedule_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Користувача не знайдено")
        return
    await _send_schedule_photo(callback, user, session, edit_photo=True)
    await callback.answer("🔄 Оновлено")


@router.callback_query(F.data == "my_queues")
async def change_queue(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    await state.set_state(WizardSG.region)
    await state.update_data(mode="edit_from_schedule")

    if callback.message.photo:
        await _safe_delete(callback.message)
        await callback.message.answer("Оберіть свій регіон:", reply_markup=get_region_keyboard())
    else:
        await _safe_edit_text(callback.message, "Оберіть свій регіон:", reply_markup=get_region_keyboard())


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
    await _safe_edit_text(callback.message, "📊 Статистика", reply_markup=get_statistics_keyboard())


@router.callback_query(F.data.in_({"stats_week", "stats_device", "stats_settings"}))
async def stats_detail(callback: CallbackQuery) -> None:
    await callback.answer("⚠️ Ця функція в розробці", show_alert=True)


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    from bot.db.queries import get_setting

    support_url = await get_setting(session, "support_url")
    await _safe_edit_text(
        callback.message,
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
    await _safe_edit_text(callback.message, text, reply_markup=get_help_keyboard())


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

    if callback.message.photo:
        await _safe_delete(callback.message)
        await callback.message.answer(text, reply_markup=get_settings_keyboard(is_admin=is_admin), parse_mode="HTML")
    else:
        await _safe_edit_text(callback.message, text, reply_markup=get_settings_keyboard(is_admin=is_admin))


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
