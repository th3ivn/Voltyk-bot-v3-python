from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants.regions import REGION_QUEUES, REGIONS, STANDARD_QUEUES
from bot.db.queries import create_or_update_user, get_setting, get_user_by_telegram_id
from bot.formatter.messages import format_main_menu_message
from bot.keyboards.inline import (
    get_confirm_keyboard,
    get_main_menu,
    get_queue_keyboard,
    get_region_keyboard,
    get_restoration_keyboard,
    get_wizard_bot_notification_keyboard,
    get_wizard_notify_target_keyboard,
)
from bot.states.fsm import WizardSG
from bot.utils.logger import get_logger
from bot.utils.metrics import USER_REGISTRATIONS_TOTAL
from bot.utils.telegram import safe_edit_text

logger = get_logger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    user = await get_user_by_telegram_id(session, message.from_user.id)

    if user and not user.is_active:
        await message.answer(
            "👋 З поверненням!\n\nВаш профіль було деактивовано.\n\nОберіть опцію:",
            reply_markup=get_restoration_keyboard(),
        )
        return

    if user and user.is_active:
        # Delete previous menu message to avoid clutter
        if user.last_menu_message_id:
            try:
                await message.bot.delete_message(message.chat.id, user.last_menu_message_id)
            except Exception as e:
                logger.debug("Could not delete previous menu message %s: %s", user.last_menu_message_id, e)

        text = format_main_menu_message(user)
        has_channel = bool(user.channel_config and user.channel_config.channel_id)
        channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
        msg = await message.answer(
            text,
            reply_markup=get_main_menu(channel_paused=channel_paused, has_channel=has_channel),
            parse_mode="HTML",
        )
        user.last_menu_message_id = msg.message_id
        return

    reg_enabled = await get_setting(session, "registration_enabled")
    if reg_enabled == "false":
        await message.answer(
            "⚠️ Реєстрація тимчасово обмежена\n\n"
            "На даний момент реєстрація нових користувачів тимчасово зупинена.\n\n"
            "Спробуйте пізніше або зв'яжіться з підтримкою."
        )
        return

    await state.set_state(WizardSG.region)
    await state.update_data(mode="new")
    await message.answer(
        "👋 Вітаю! Я Вольтик ⚡\n\n"
        "Слідкую за відключеннями світла і одразу\n"
        "повідомлю, як тільки щось зміниться.\n\n"
        "Налаштування займе ~1 хвилину.\n\n"
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        reply_markup=get_region_keyboard(),
    )


@router.callback_query(F.data == "restore_profile")
async def restore_profile(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user:
        user.is_active = True
        text = format_main_menu_message(user)
        has_channel = bool(user.channel_config and user.channel_config.channel_id)
        channel_paused = bool(user.channel_config and user.channel_config.channel_paused)
        await safe_edit_text(callback.message,
            text,
            reply_markup=get_main_menu(channel_paused=channel_paused, has_channel=has_channel),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "create_new_profile")
async def create_new_profile(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await state.set_state(WizardSG.region)
    await state.update_data(mode="new")
    await safe_edit_text(callback.message,
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        reply_markup=get_region_keyboard(),
    )


@router.callback_query(WizardSG.region, F.data.startswith("region_"))
async def wizard_region(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    region_code = callback.data.replace("region_", "")
    if region_code == "request_start":
        return
    if region_code not in REGIONS:
        await callback.answer("❌ Невідомий регіон")
        return
    await callback.answer()
    region = REGIONS[region_code]
    data = await state.get_data()
    await state.update_data(region=region_code)
    await state.set_state(WizardSG.queue)
    current_queue: str | None = None
    if data.get("mode") in ("edit", "edit_from_schedule"):
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if user and user.region == region_code:
            current_queue = user.queue
    await safe_edit_text(callback.message,
        f"✅ Регіон: {region.name}\n\n⚡ Крок 2 із 3 — Оберіть свою чергу:",
        reply_markup=get_queue_keyboard(region_code, current_queue=current_queue),
    )


@router.callback_query(WizardSG.queue, F.data.startswith("queue_page_"))
async def wizard_queue_page(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    from bot.utils.helpers import safe_parse_callback_int
    page = safe_parse_callback_int(callback.data, "queue_page_")
    if page is None:
        return
    data = await state.get_data()
    region_code = data.get("region", "kyiv")
    region = REGIONS.get(region_code)
    await safe_edit_text(callback.message,
        f"✅ Регіон: {region.name if region else region_code}\n\n⚡ Крок 2 із 3 — Оберіть свою чергу:",
        reply_markup=get_queue_keyboard(region_code, page),
    )


@router.callback_query(WizardSG.queue, F.data.startswith("queue_"))
async def wizard_queue(callback: CallbackQuery, state: FSMContext) -> None:
    queue = callback.data.replace("queue_", "")
    if queue.startswith("page_"):
        return
    data = await state.get_data()
    region_code = data.get("region", "kyiv")
    allowed = REGION_QUEUES.get(region_code, STANDARD_QUEUES)
    if queue not in allowed:
        await callback.answer("❌ Невідома черга", show_alert=True)
        return
    await callback.answer()
    await state.update_data(queue=queue)
    mode = data.get("mode", "new")

    if mode == "new":
        await state.set_state(WizardSG.notify_target)
        await safe_edit_text(callback.message,
            f"✅ Черга: {queue}\n\n"
            "📬 Крок 3 із 3 — Куди надсилати сповіщення?\n\n"
            "📱 У цьому боті\n"
            "Сповіщення приходитимуть прямо в цей чат\n\n"
            "📺 У Telegram-каналі\n"
            "Бот публікуватиме у ваш канал\n"
            "(потрібно додати бота як адміністратора)",
            reply_markup=get_wizard_notify_target_keyboard(),
        )
    else:
        await state.set_state(WizardSG.confirm)
        region_code = data.get("region", "")
        region = REGIONS.get(region_code)
        await safe_edit_text(callback.message,
            f"✅ Налаштування:\n\n"
            f"📍 Регіон: {region.name if region else region_code}\n"
            f"⚡️ Черга: {queue}\n\n"
            "Підтвердіть налаштування:",
            reply_markup=get_confirm_keyboard(),
        )


@router.callback_query(F.data == "back_to_region")
async def back_to_region(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WizardSG.region)
    await safe_edit_text(callback.message,
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        reply_markup=get_region_keyboard(),
    )


@router.callback_query(WizardSG.notify_target, F.data == "wizard_notify_bot")
async def wizard_notify_bot(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    data = await state.get_data()

    user = await create_or_update_user(
        session,
        callback.from_user.id,
        callback.from_user.username,
        data["region"],
        data["queue"],
    )

    if data.get("mode") == "new" and not data.get("_registration_counted"):
        USER_REGISTRATIONS_TOTAL.inc()
        await state.update_data(_registration_counted=True)

    await state.set_state(WizardSG.bot_notifications)
    ns = user.notification_settings
    if not ns:
        await safe_edit_text(callback.message, "❌ Помилка. Спробуйте /start")
        await state.clear()
        return
    await safe_edit_text(callback.message,
        "🔔 Налаштуйте сповіщення в боті:",
        reply_markup=get_wizard_bot_notification_keyboard(
            schedule_changes=ns.notify_schedule_changes,
            remind_off=ns.notify_remind_off,
            fact_off=ns.notify_fact_off,
            remind_on=ns.notify_remind_on,
            fact_on=ns.notify_fact_on,
            remind_15m=ns.remind_15m,
            remind_30m=ns.remind_30m,
            remind_1h=ns.remind_1h,
        ),
    )


@router.callback_query(WizardSG.bot_notifications, F.data == "wizard_notif_toggle_schedule")
async def wizard_toggle_schedule(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.notification_settings:
        ns = user.notification_settings
        ns.notify_schedule_changes = not ns.notify_schedule_changes
        await callback.message.edit_reply_markup(
            reply_markup=get_wizard_bot_notification_keyboard(
                schedule_changes=ns.notify_schedule_changes,
                remind_off=ns.notify_remind_off,
                fact_off=ns.notify_fact_off,
                remind_on=ns.notify_remind_on,
                fact_on=ns.notify_fact_on,
                remind_15m=ns.remind_15m,
                remind_30m=ns.remind_30m,
                remind_1h=ns.remind_1h,
            )
        )
    await callback.answer()


@router.callback_query(WizardSG.bot_notifications, F.data.startswith("wizard_notif_time_"))
async def wizard_toggle_time(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    from bot.utils.helpers import safe_parse_callback_int
    minutes = safe_parse_callback_int(callback.data, "wizard_notif_time_")
    if minutes is None:
        await callback.answer()
        return
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.notification_settings:
        ns = user.notification_settings
        if minutes == 15:
            ns.remind_15m = not ns.remind_15m
        elif minutes == 30:
            ns.remind_30m = not ns.remind_30m
        elif minutes == 60:
            ns.remind_1h = not ns.remind_1h
        await callback.message.edit_reply_markup(
            reply_markup=get_wizard_bot_notification_keyboard(
                schedule_changes=ns.notify_schedule_changes,
                remind_off=ns.notify_remind_off,
                fact_off=ns.notify_fact_off,
                remind_on=ns.notify_remind_on,
                fact_on=ns.notify_fact_on,
                remind_15m=ns.remind_15m,
                remind_30m=ns.remind_30m,
                remind_1h=ns.remind_1h,
            )
        )
    await callback.answer()


@router.callback_query(WizardSG.bot_notifications, F.data == "wizard_notif_toggle_fact")
async def wizard_toggle_fact(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.notification_settings:
        ns = user.notification_settings
        new_val = not ns.notify_fact_off
        ns.notify_fact_off = new_val
        ns.notify_fact_on = new_val
        await callback.message.edit_reply_markup(
            reply_markup=get_wizard_bot_notification_keyboard(
                schedule_changes=ns.notify_schedule_changes,
                remind_off=ns.notify_remind_off,
                fact_off=ns.notify_fact_off,
                remind_on=ns.notify_remind_on,
                fact_on=ns.notify_fact_on,
                remind_15m=ns.remind_15m,
                remind_30m=ns.remind_30m,
                remind_1h=ns.remind_1h,
            )
        )
    await callback.answer()


@router.callback_query(WizardSG.bot_notifications, F.data == "wizard_notify_back")
async def wizard_notify_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    queue = data.get("queue", "")
    await state.set_state(WizardSG.notify_target)
    await safe_edit_text(callback.message,
        f"✅ Черга: {queue}\n\n"
        "📬 Крок 3 із 3 — Куди надсилати сповіщення?\n\n"
        "📱 У цьому боті\nСповіщення приходитимуть прямо в цей чат\n\n"
        "📺 У Telegram-каналі\nБот публікуватиме у ваш канал\n"
        "(потрібно додати бота як адміністратора)",
        reply_markup=get_wizard_notify_target_keyboard(),
    )


@router.callback_query(WizardSG.bot_notifications, F.data == "wizard_bot_done")
async def wizard_bot_done(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await state.clear()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return

    region = REGIONS.get(user.region)
    region_name = region.name if region else user.region
    text = (
        f"✅ Готово!\n\n"
        f"📍 Регіон: {region_name}\n"
        f"⚡ Черга: {user.queue}\n"
        f"🔔 Сповіщення: увімкнено ✅\n\n"
        "Я одразу повідомлю вас про наступне\n"
        "відключення або появу світла.\n\n"
        "⤵ Меню — перейти в головне меню\n"
        "📢 Новини бота — канал з оновленнями"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⤵ Меню", callback_data="back_to_main")],
            [InlineKeyboardButton(text="📢 Новини бота", url="https://t.me/Voltyk_news")],
        ]
    )
    await safe_edit_text(callback.message, text, reply_markup=kb)


@router.callback_query(WizardSG.notify_target, F.data == "wizard_notify_channel")
async def wizard_notify_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    data = await state.get_data()
    await create_or_update_user(
        session,
        callback.from_user.id,
        callback.from_user.username,
        data["region"],
        data["queue"],
    )

    if data.get("mode") == "new" and not data.get("_registration_counted"):
        USER_REGISTRATIONS_TOTAL.inc()
        await state.update_data(_registration_counted=True)

    await state.set_state(WizardSG.channel_setup)

    bot_me = await callback.bot.get_me()
    await safe_edit_text(callback.message,
        "📺 Підключення каналу\n\n"
        "Щоб бот міг публікувати графіки у ваш канал:\n\n"
        "1️⃣ Відкрийте ваш канал у Telegram\n"
        "2️⃣ Перейдіть у Налаштування каналу → Адміністратори\n"
        "3️⃣ Натисніть \"Додати адміністратора\"\n"
        f"4️⃣ Знайдіть бота: @{bot_me.username}\n"
        "5️⃣ Надайте права на публікацію повідомлень\n\n"
        "Після цього натисніть кнопку \"✅ Перевірити\" нижче.\n\n"
        f"💡 Порада: скопіюйте @{bot_me.username} і вставте у пошук",
        reply_markup=get_wizard_notify_target_keyboard(),
    )


@router.callback_query(WizardSG.confirm, F.data == "confirm_setup")
async def wizard_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    data = await state.get_data()
    region_code = data.get("region", "")
    queue = data.get("queue", "")
    mode = data.get("mode", "new")

    user = await create_or_update_user(
        session, callback.from_user.id, callback.from_user.username, region_code, queue
    )
    await state.clear()

    region = REGIONS.get(region_code)
    region_name = region.name if region else region_code

    if mode == "edit_from_schedule":
        await safe_edit_text(callback.message,
            f"✅ Налаштування оновлено!\n\n📍 Регіон: {region_name}\n⚡ Черга: {queue}",
        )
        from bot.handlers.menu import _send_schedule_photo

        await _send_schedule_photo(callback, user, session, edit_photo=False)
        return
    else:
        await safe_edit_text(callback.message,
            f"✅ Налаштування оновлено!\n\n📍 Регіон: {region_name}\n⚡ Черга: {queue}",
            reply_markup=get_main_menu(
                has_channel=bool(user.channel_config and user.channel_config.channel_id),
                channel_paused=bool(user.channel_config and user.channel_config.channel_paused),
            ),
        )
