from __future__ import annotations

import time
from datetime import timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaPhoto
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.models import User
from bot.db.queries import get_power_history_week, get_schedule_check_time, get_setting, get_user_by_telegram_id
from bot.formatter.messages import format_live_status_message, format_main_menu_message
from bot.formatter.schedule import format_schedule_message
from bot.formatter.timer import format_timer_popup
from bot.keyboards.inline import (
    get_error_keyboard,
    get_faq_keyboard,
    get_help_keyboard,
    get_instruction_section_keyboard,
    get_instructions_keyboard,
    get_main_menu,
    get_region_keyboard,
    get_schedule_view_keyboard,
    get_settings_keyboard,
    get_statistics_keyboard,
    get_support_keyboard,
)
from bot.services.api import (
    calculate_schedule_hash,
    fetch_schedule_data,
    fetch_schedule_image,
    find_next_event,
    parse_schedule_for_queue,
)
from bot.states.fsm import WizardSG
from bot.utils.html_to_entities import append_timestamp, to_aiogram_entities
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="menu")

_MSG_NOT_MODIFIED = "message is not modified"

# Per-user cooldown: user_id → timestamp of last "Перевірити" press
_user_last_check: dict[int, float] = {}
_DEFAULT_COOLDOWN_S = 30
_LAST_CHECK_CLEANUP_INTERVAL = 300  # clean up stale entries every 5 minutes
_USER_LAST_CHECK_MAX_SIZE = 10_000  # cap to prevent unbounded growth
_last_check_cleanup_at: float = 0.0


async def _safe_edit_text(message, text: str, reply_markup=None, parse_mode="HTML") -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except Exception as e:
        if _MSG_NOT_MODIFIED in str(e):
            return True
        logger.warning("_safe_edit_text failed: %s", e)
        return False


async def _safe_delete(message) -> None:
    try:
        await message.delete()
    except Exception as e:
        logger.debug("Could not delete message: %s", e)


async def _safe_edit_or_resend(message, text: str, reply_markup=None, parse_mode: str = "HTML"):
    """Edit a text message in-place, or delete-and-resend when the current message contains a photo.
    Returns the new/original message object on success, or None on unexpected error.
    """
    try:
        if message.photo:
            await _safe_delete(message)
            return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            if not await _safe_edit_text(message, text, reply_markup=reply_markup, parse_mode=parse_mode):
                return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return message
    except Exception as e:
        logger.error("_safe_edit_or_resend failed: %s", e)
        return None


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
        except Exception as e:
            logger.debug("Could not delete old menu message %s: %s", user.last_menu_message_id, e)

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
    html_text = format_schedule_message(user.region, user.queue, schedule_data)
    kb = get_schedule_view_keyboard()

    last_check = await get_schedule_check_time(session, user.region, user.queue)
    plain_text, raw_entities = append_timestamp(html_text, last_check)
    entities = to_aiogram_entities(raw_entities)

    image_bytes = await fetch_schedule_image(user.region, user.queue, schedule_data)

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


@router.callback_query(F.data == "schedule_check")
async def schedule_check(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Користувача не знайдено")
        return

    # --- Cooldown check ---
    global _last_check_cleanup_at
    try:
        cooldown_s = int(await get_setting(session, "refresh_cooldown") or _DEFAULT_COOLDOWN_S)
    except (ValueError, TypeError):
        cooldown_s = _DEFAULT_COOLDOWN_S
    now = time.monotonic()

    # Periodically evict entries older than cooldown_s to prevent unbounded growth
    if now - _last_check_cleanup_at > _LAST_CHECK_CLEANUP_INTERVAL:
        cutoff = now - cooldown_s
        stale = [uid for uid, t in _user_last_check.items() if t <= cutoff]
        for uid in stale:
            del _user_last_check[uid]
        _last_check_cleanup_at = now

    last = _user_last_check.get(callback.from_user.id, 0.0)
    elapsed = now - last
    if elapsed < cooldown_s:
        remaining = int(cooldown_s - elapsed) + 1
        await callback.answer(f"⏳ Зачекай ще {remaining} сек", show_alert=False)
        return

    # Mark cooldown BEFORE first await so concurrent taps from the same user
    # cannot both slip through the check above (asyncio cooperative scheduling
    # means nothing preempts us between here and the next await point).
    # On API failure we clear it so the user can retry immediately.
    # When the dict is at its size cap, batch-evict stale entries first.
    if len(_user_last_check) >= _USER_LAST_CHECK_MAX_SIZE:
        cutoff = now - cooldown_s
        stale_uids = [uid for uid, t in _user_last_check.items() if t <= cutoff]
        for uid in stale_uids:
            del _user_last_check[uid]
        if stale_uids:
            logger.debug(
                "_user_last_check: batch-evicted %d stale entries at cap", len(stale_uids)
            )
        # If still at cap after TTL eviction, evict 10% of the oldest entries
        if len(_user_last_check) >= _USER_LAST_CHECK_MAX_SIZE:
            evict_count = max(1, _USER_LAST_CHECK_MAX_SIZE // 10)
            oldest_uids = list(_user_last_check.keys())[:evict_count]
            for uid in oldest_uids:
                del _user_last_check[uid]
            logger.debug(
                "_user_last_check: force-evicted %d oldest entries (10%% of cap)", evict_count
            )
    _user_last_check[callback.from_user.id] = now

    # --- Get old hash from cached data (before force refresh) ---
    old_data = await fetch_schedule_data(user.region)
    old_events = parse_schedule_for_queue(old_data, user.queue).get("events", []) if old_data else []
    old_hash = calculate_schedule_hash(old_events) if old_events else None

    # --- Force refresh ---
    new_data = await fetch_schedule_data(user.region, force_refresh=True)
    if new_data is None:
        # Transient API failure — clear cooldown so the user can retry immediately
        _user_last_check.pop(callback.from_user.id, None)
        await callback.answer("❌ Не вдалось отримати дані", show_alert=False)
        return

    # --- Compare hashes ---
    new_events = parse_schedule_for_queue(new_data, user.queue).get("events", [])
    new_hash = calculate_schedule_hash(new_events) if new_events else None

    if old_hash != new_hash:
        await _send_schedule_photo(callback, user, session, edit_photo=True)
        await callback.answer("💡 Знайдено зміни — оновлено", show_alert=False)
    else:
        await _send_schedule_photo(callback, user, session, edit_photo=True)
        await callback.answer("✅ Без змін — дані актуальні", show_alert=False)


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
        await callback.message.answer("Оберіть свій регіон:", reply_markup=get_region_keyboard(current_region=user.region))
    else:
        await _safe_edit_text(callback.message, "Оберіть свій регіон:", reply_markup=get_region_keyboard(current_region=user.region))


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
    await _safe_edit_or_resend(callback.message, "📊 Статистика", reply_markup=get_statistics_keyboard())


@router.callback_query(F.data == "stats_week")
async def stats_week(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    history = await get_power_history_week(session, user.id)
    off_events = [h for h in history if h.event_type == "off"]
    total_outages = len(off_events)
    total_seconds = sum(h.duration_seconds or 0 for h in off_events)
    total_hours = total_seconds // 3600
    total_minutes = (total_seconds % 3600) // 60

    if total_outages == 0:
        text = "⚡ Відключення за тиждень\n\nЗа останні 7 днів відключень не зафіксовано."
    else:
        text = (
            f"⚡ Відключення за тиждень\n\n"
            f"📊 Кількість відключень: {total_outages}\n"
            f"⏱ Загальний час без світла: {total_hours}г {total_minutes}хв"
        )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_statistics_keyboard())


@router.callback_query(F.data == "stats_device")
async def stats_device(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    if not user.router_ip:
        text = (
            "📡 Статус пристрою\n\n"
            "IP-адресу роутера не налаштовано.\n\n"
            "Щоб відстежувати фактичний стан живлення — вкажіть IP у Налаштуваннях."
        )
    else:
        pt = user.power_tracking
        state = pt.power_state if pt else None
        changed_at = pt.power_changed_at if pt else None

        if state == "on":
            state_text = "🟢 Світло є"
        elif state == "off":
            state_text = "🔴 Світла немає"
        else:
            state_text = "⏳ Статус невідомий"

        since_text = ""
        if changed_at:
            kyiv = app_settings.timezone
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=timezone.utc)
            since_text = f"\nЗ {changed_at.astimezone(kyiv).strftime('%d.%m %H:%M')}"

        text = (
            f"📡 Статус пристрою\n\n"
            f"🌐 IP: {user.router_ip}\n"
            f"{state_text}{since_text}"
        )

    await _safe_edit_or_resend(callback.message, text, reply_markup=get_statistics_keyboard())


@router.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    faq_url = app_settings.FAQ_CHANNEL_URL or None
    support_url = app_settings.SUPPORT_CHANNEL_URL or None
    msg = await _safe_edit_or_resend(
        callback.message,
        "❓ Допомога\n\nТут ви можете дізнатися як користуватися\nботом або звернутися за підтримкою.",
        reply_markup=get_help_keyboard(faq_url=faq_url, support_url=support_url),
    )
    if user and msg:
        user.last_menu_message_id = msg.message_id


@router.callback_query(F.data == "help_instructions")
async def help_instructions(callback: CallbackQuery) -> None:
    await callback.answer()
    await _safe_edit_or_resend(
        callback.message,
        "📖 Інструкція\n\nОберіть розділ який вас цікавить:",
        reply_markup=get_instructions_keyboard(),
    )


@router.callback_query(F.data == "help_faq")
async def help_faq(callback: CallbackQuery) -> None:
    await callback.answer()
    faq_url = app_settings.FAQ_CHANNEL_URL or None
    text = (
        '<tg-emoji emoji-id="5319180751143476261">❓</tg-emoji> FAQ\n\n'
        "Тут ви знайдете відповіді на найпоширеніші\n"
        "питання про роботу бота."
    )
    await _safe_edit_or_resend(
        callback.message,
        text,
        reply_markup=get_faq_keyboard(faq_url=faq_url),
    )


@router.callback_query(F.data == "help_support")
async def help_support(callback: CallbackQuery) -> None:
    await callback.answer()
    support_url = app_settings.SUPPORT_CHANNEL_URL or None
    text = (
        '<tg-emoji emoji-id="5310296757320586255">💬</tg-emoji> Служба підтримки\n\n'
        "Натисніть кнопку нижче щоб написати\n"
        "адміністратору напряму в Telegram.\n"
        "Відповідь надійде найближчим часом."
    )
    await _safe_edit_or_resend(
        callback.message,
        text,
        reply_markup=get_support_keyboard(support_url=support_url),
    )


@router.callback_query(F.data == "instr_region")
async def instr_region(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5319069545850247853">📍</tg-emoji> Регіон і черга\n\n'
        "Для отримання графіку відключень потрібно\n"
        "обрати свій регіон та чергу.\n\n"
        "Як знайти свою чергу — введіть свою адресу\n"
        "на сайті свого обленерго:\n\n"
        '• Київ — <a href="https://www.dtek-kem.com.ua/ua/shutdowns">dtek-kem.com.ua</a>\n'
        '• Київська обл. — <a href="https://www.dtek-krem.com.ua/ua/shutdowns">dtek-krem.com.ua</a>\n'
        '• Дніпропетровська обл. — <a href="https://www.dtek-dnem.com.ua/ua/shutdowns">dtek-dnem.com.ua</a>\n'
        '• Одеська обл. — <a href="https://www.dtek-oem.com.ua/ua/shutdowns">dtek-oem.com.ua</a>\n\n'
        "Як налаштувати в боті:\n"
        "1. Перейдіть в Налаштування → Регіон\n"
        "2. Оберіть свою область\n"
        "3. Оберіть свою чергу (наприклад 3.1)"
    )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_notif")
async def instr_notif(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5262598817626234330">🔔</tg-emoji> Сповіщення\n\n'
        "Бот автоматично надсилає сповіщення про:\n"
        "• Зміни в графіку відключень\n"
        "• Появу нового графіку на завтра\n"
        "• Щоденний графік о 06:00\n"
        "• Фактичне зникнення та появу світла (з IP)\n\n"
        "Куди надходять сповіщення:\n"
        "• В особистий чат з ботом\n"
        "• В підключений канал (якщо налаштовано)\n\n"
        "Важливо: бот і канал мають окремі\n"
        "налаштування сповіщень — ви можете\n"
        "увімкнути або вимкнути їх незалежно\n"
        "один від одного.\n\n"
        "Як налаштувати:\n"
        "1. Перейдіть в Налаштування → Сповіщення\n"
        "2. Налаштуйте окремо для бота і каналу"
    )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_channel")
async def instr_channel(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5312374181462055424">📺</tg-emoji> Канал\n\n'
        "Ви можете підключити свій Telegram канал —\n"
        "бот автоматично публікуватиме в ньому\n"
        "графіки відключень та сповіщення.\n\n"
        "Що публікується в каналі:\n"
        "• Графік відключень (фото + текст)\n"
        "• Сповіщення про зміни графіку\n"
        "• Сповіщення про зникнення та появу світла\n\n"
        "Як підключити:\n"
        "1. Перейдіть в Налаштування → Канал\n"
        "2. Натисніть кнопку Підключити канал\n"
        "3. Перейдіть у свій канал і додайте бота\n"
        "   як адміністратора\n"
        "4. Бот автоматично виявить канал і\n"
        "   запитає підтвердження підключення\n\n"
        "Канал має окремі налаштування сповіщень —\n"
        "незалежно від особистого чату з ботом."
    )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_ip")
async def instr_ip(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5312283536177273995">📡</tg-emoji> IP моніторинг\n\n'
        "Бот може визначати фактичний статус світла\n"
        "у вас вдома — пінгуючи ваш роутер.\n\n"
        "Важливо: роутер має вимикатись при\n"
        "відключенні світла. Якщо він підключений\n"
        "до безперебійника — моніторинг не працюватиме\n"
        "коректно.\n\n"
        "Що потрібно:\n"
        "• Статична (біла) IP-адреса роутера\n"
        "  (~30–50 грн/місяць у провайдера)\n"
        "• або DDNS — якщо немає статичного IP\n\n"
        "Що отримуєте:\n"
        "• Сповіщення коли світло зникло\n"
        "• Сповіщення коли світло з'явилося\n"
        "• Визначення позапланових відключень\n\n"
        "Як підключити:\n"
        "1. Перейдіть в Налаштування → IP\n"
        "2. Введіть IP-адресу або DDNS вашого роутера\n"
        "3. Бот автоматично перевірить з'єднання\n\n"
        "Підтримувані формати:\n"
        "• 89.267.32.1\n"
        "• 89.267.32.1:80\n"
        "• myhome.ddns.net"
    )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_schedule")
async def instr_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5264999721524562037">📊</tg-emoji> Графік відключень\n\n'
        "Бот показує актуальний графік відключень\n"
        "для вашого регіону та черги.\n\n"
        "Що показує графік:\n"
        "• Планові відключення на сьогодні\n"
        "• Планові відключення на завтра\n"
        "• Загальний час без світла за день\n\n"
        "Щоденне повідомлення о 06:00:\n"
        "Кожного ранку бот надсилає актуальний\n"
        "графік на поточний день.\n\n"
        "Як переглянути графік:\n"
        "1. Натисніть кнопку Графік в головному меню\n"
        "2. Дочекайтесь щоденного повідомлення о 06:00\n"
        "3. Увімкніть сповіщення — і бот сам\n"
        "   повідомить коли графік зміниться\n\n"
        "Порівняння графіків:\n"
        "Ви можете порівнювати графік за вчора\n"
        "та сьогодні — бот зберігає історію\n"
        "по кожному календарному дню."
    )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


@router.callback_query(F.data == "instr_bot_settings")
async def instr_bot_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        '<tg-emoji emoji-id="5312280340721604022">⚙️</tg-emoji> Налаштування бота\n\n'
        "В налаштуваннях ви можете керувати\n"
        "всіма параметрами бота.\n\n"
        "Що можна налаштувати:\n"
        "• Регіон і черга — змінити свій регіон\n"
        "• Сповіщення — увімкнути або вимкнути\n"
        "• Канал — підключити свій Telegram канал\n"
        "• IP моніторинг — налаштувати відстеження\n"
        "  фактичного стану світла\n\n"
        "Додаткові можливості:\n"
        "• Тимчасово зупинити / відновити канал —\n"
        "  керуйте публікаціями в канал в будь-який\n"
        "  момент прямо з головного меню або\n"
        "  налаштувань каналу\n"
        "• Видалити мої дані — повністю видалити\n"
        "  всі ваші дані з бота\n\n"
        "Як відкрити налаштування:\n"
        "Натисніть кнопку Налаштування\n"
        "в головному меню."
    )
    await _safe_edit_or_resend(callback.message, text, reply_markup=get_instruction_section_keyboard())


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
        if not await _safe_edit_text(callback.message, text, reply_markup=get_settings_keyboard(is_admin=is_admin)):
            await callback.message.answer(text, reply_markup=get_settings_keyboard(is_admin=is_admin), parse_mode="HTML")


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
    await session.commit()


@router.callback_query(F.data == "reminder_show_schedule")
async def reminder_show_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("❌ Спочатку запустіть бота /start", show_alert=True)
        return
    await _send_schedule_photo(callback, user, session, edit_photo=False)
