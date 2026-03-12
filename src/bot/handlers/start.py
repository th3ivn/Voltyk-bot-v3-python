from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.bot.constants import REGIONS, get_queues_for_region
from src.bot.keyboards.inline import (
    get_confirm_keyboard,
    get_main_menu,
    get_queue_keyboard,
    get_region_keyboard,
    get_restoration_keyboard,
    get_wizard_in_progress_keyboard,
    get_wizard_notify_target_keyboard,
)
from src.bot.states.wizard import WizardStates

router = Router(name="start")


# ──────────────────── /start command ────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start command — new user wizard or main menu for existing users."""
    _ = message.from_user.id  # type: ignore[union-attr]  # will be used in PR-2 for DB lookup

    # Check if user is in wizard — ask to resume/restart
    current_state = await state.get_state()
    if current_state and current_state.startswith("WizardStates:"):
        await message.answer(
            "⚠️ Спочатку завершіть налаштування!\n\n" "Оберіть дію:",
            reply_markup=get_wizard_in_progress_keyboard(),
        )
        return

    # TODO: PR-2 — look up user in DB
    # For now, always start wizard for new users
    user = None  # placeholder

    if user is not None:
        # Existing user flow
        if not user.get("is_active", True):
            # Deactivated user
            await message.answer(
                "👋 З поверненням!\n\n"
                "Ваш профіль було деактивовано.\n\n"
                "Оберіть опцію:",
                reply_markup=get_restoration_keyboard(),
            )
            return

        # Active user — show main menu
        region_name = REGIONS.get(user["region"], REGIONS["kyiv"]).name
        queue = user["queue"]
        channel_id = user.get("channel_id")
        has_notifications = user.get("bot_notifications", False) or user.get(
            "channel_notifications", False
        )
        channel_paused = user.get("channel_paused", False)

        bot_status = "active"
        if not channel_id:
            bot_status = "no_channel"

        text = (
            "🏠 <b>Головне меню</b>\n\n"
            f"📍 Регіон: {region_name} • {queue}\n"
            f"📺 Канал: {(channel_id + ' ✅') if channel_id else 'не підключено'}\n"
            f"🔔 Сповіщення: {'увімкнено ✅' if has_notifications else 'вимкнено'}\n"
        )

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_main_menu(bot_status, channel_paused),
        )
        return

    # New user — start wizard step 1 (region)
    await state.set_state(WizardStates.region)
    await state.update_data(mode="new")

    await message.answer(
        '<tg-emoji emoji-id="5472055112702629499">👋</tg-emoji> Вітаю! Я СвітлоБот ⚡\n\n'
        "Слідкую за відключеннями світла і одразу\n"
        "повідомлю, як тільки щось зміниться.\n\n"
        "Налаштування займе ~1 хвилину.\n\n"
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        parse_mode="HTML",
        reply_markup=get_region_keyboard(),
    )


# ──────────────────── Wizard Resume / Restart ────────────────────


@router.callback_query(F.data == "wizard_resume")
async def wizard_resume(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    current_state = await state.get_state()
    data = await state.get_data()

    if current_state == WizardStates.queue.state and data.get("region"):
        region_name = REGIONS[data["region"]].name
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✅ Регіон: {region_name}\n\n" "⚡ Крок 2 із 3 — Оберіть свою чергу:",
            reply_markup=get_queue_keyboard(data["region"], 1),
        )
        return

    if current_state == WizardStates.notify_target.state and data.get("queue"):
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✅ Черга: {data['queue']}\n\n"
            "📬 Крок 3 із 3 — Куди надсилати сповіщення?\n\n"
            "📱 <b>У цьому боті</b>\n"
            "Сповіщення приходитимуть прямо в цей чат\n\n"
            "📺 <b>У Telegram-каналі</b>\n"
            "Бот публікуватиме у ваш канал\n"
            "(потрібно додати бота як адміністратора)",
            parse_mode="HTML",
            reply_markup=get_wizard_notify_target_keyboard(),
        )
        return

    # Fallback — region selection
    await state.set_state(WizardStates.region)
    await callback.message.edit_text(  # type: ignore[union-attr]
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        reply_markup=get_region_keyboard(),
    )


@router.callback_query(F.data == "wizard_restart")
async def wizard_restart(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(WizardStates.region)
    await state.update_data(mode="new")

    try:
        await callback.message.delete()  # type: ignore[union-attr]
    except Exception:
        pass

    await callback.message.answer(  # type: ignore[union-attr]
        '<tg-emoji emoji-id="5472055112702629499">👋</tg-emoji> Вітаю! Я СвітлоБот ⚡\n\n'
        "Слідкую за відключеннями світла і одразу\n"
        "повідомлю, як тільки щось зміниться.\n\n"
        "Налаштування займе ~1 хвилину.\n\n"
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        parse_mode="HTML",
        reply_markup=get_region_keyboard(),
    )


# ──────────────────── Step 1: Region ────────────────────


@router.callback_query(F.data.startswith("region_"), WizardStates.region)
async def on_region_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    region = callback.data.replace("region_", "")  # type: ignore[union-attr]

    if region == "request_start":
        # TODO: PR-2+ region request flow
        await callback.answer("Ця функція ще в розробці", show_alert=True)
        return

    if region not in REGIONS:
        await callback.answer("Невідомий регіон", show_alert=True)
        return

    await state.set_state(WizardStates.queue)
    await state.update_data(region=region)

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Регіон: {REGIONS[region].name}\n\n" "⚡ Крок 2 із 3 — Оберіть свою чергу:",
        reply_markup=get_queue_keyboard(region, 1),
    )


# ──────────────────── Queue pagination (Kyiv) ────────────────────


@router.callback_query(F.data.startswith("queue_page_"), WizardStates.queue)
async def on_queue_page(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    region = data.get("region", "kyiv")

    page_str = callback.data.replace("queue_page_", "")  # type: ignore[union-attr]
    page = int(page_str) if page_str.isdigit() else 1

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Регіон: {REGIONS[region].name}\n\n" "⚡ Крок 2 із 3 — Оберіть свою чергу:",
        reply_markup=get_queue_keyboard(region, page),
    )


# ──────────────────── Step 2: Queue ────────────────────


@router.callback_query(F.data.startswith("queue_"), WizardStates.queue)
async def on_queue_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    queue = callback.data.replace("queue_", "")  # type: ignore[union-attr]

    # Skip pagination callbacks (already handled above)
    if queue.startswith("page_"):
        return

    data = await state.get_data()
    region = data.get("region")

    # Validate queue belongs to region
    valid_queues = get_queues_for_region(region) if region else []
    if queue not in valid_queues:
        await callback.answer("Невідома черга", show_alert=True)
        return

    mode = data.get("mode", "new")

    if mode == "new":
        # New user → step 3: notify target
        await state.set_state(WizardStates.notify_target)
        await state.update_data(queue=queue)

        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✅ Черга: {queue}\n\n"
            "📬 Крок 3 із 3 — Куди надсилати сповіщення?\n\n"
            "📱 <b>У цьому боті</b>\n"
            "Сповіщення приходитимуть прямо в цей чат\n\n"
            "📺 <b>У Telegram-каналі</b>\n"
            "Бот публікуватиме у ваш канал\n"
            "(потрібно додати бота як адміністратора)",
            parse_mode="HTML",
            reply_markup=get_wizard_notify_target_keyboard(),
        )
    else:
        # Edit mode → confirmation
        await state.set_state(WizardStates.confirm)
        await state.update_data(queue=queue)
        region_name = REGIONS[region].name if region and region in REGIONS else region

        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✅ Налаштування:\n\n"
            f"📍 Регіон: {region_name}\n"
            f"⚡️ Черга: {queue}\n\n"
            "Підтвердіть налаштування:",
            reply_markup=get_confirm_keyboard(),
        )


# ──────────────────── Step 3: Notify Target ────────────────────


@router.callback_query(F.data == "wizard_notify_bot", WizardStates.notify_target)
async def on_notify_bot(callback: CallbackQuery, state: FSMContext) -> None:
    """User chose to receive notifications in the bot chat."""
    await callback.answer()
    data = await state.get_data()
    region = data.get("region", "")
    queue = data.get("queue", "")
    region_name = REGIONS[region].name if region in REGIONS else region

    # TODO: PR-2 — save user to DB with bot_notifications=True
    logger.info(
        "New user registered: user_id={}, region={}, queue={}, mode=bot",
        callback.from_user.id,
        region,
        queue,
    )

    await state.clear()

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Налаштування збережено!\n\n"
        f"📍 Регіон: {region_name}\n"
        f"⚡️ Черга: {queue}\n\n"
        "Тепер ви будете отримувати сповіщення про зміни графіка.",
        reply_markup=get_main_menu("no_channel", False),
    )


@router.callback_query(F.data == "wizard_notify_channel", WizardStates.notify_target)
async def on_notify_channel(callback: CallbackQuery, state: FSMContext) -> None:
    """User chose to receive notifications in a channel."""
    await callback.answer()
    # TODO: PR-2+ — channel setup flow
    await state.set_state(WizardStates.channel_setup)

    await callback.message.edit_text(  # type: ignore[union-attr]
        "📺 <b>Підключення каналу</b>\n\n"
        "Ця функція буде доступна у наступному оновленні.\n\n"
        "Поки що сповіщення будуть приходити у цей чат.",
        parse_mode="HTML",
        reply_markup=get_wizard_notify_target_keyboard(),
    )


# ──────────────────── Back navigation ────────────────────


@router.callback_query(F.data == "back_to_region")
async def back_to_region(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WizardStates.region)

    await callback.message.edit_text(  # type: ignore[union-attr]
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        reply_markup=get_region_keyboard(),
    )


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()

    # TODO: PR-2 — fetch user from DB to show proper main menu
    await callback.message.edit_text(  # type: ignore[union-attr]
        "🏠 <b>Головне меню</b>\n\n"
        "📍 Використайте /start для повного меню",
        parse_mode="HTML",
    )
