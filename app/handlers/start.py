"""Handlers for the /start command and the full registration wizard FSM.

Flow:
    1. /start → check user in DB
       - Blocked user           → "Ви заблоковані" + blocked keyboard
       - New user               → welcome message + region keyboard (FSM: choosing_region)
       - Registered user        → main menu
       - User without region    → region selection (FSM: choosing_region)
    2. region_{code}            → queue keyboard (FSM: choosing_queue)
    3. queue_{queue}            → confirmation screen (FSM: confirming)
    4. confirm_setup            → save to DB + main menu (FSM: cleared)
    5. back_to_region           → region keyboard (FSM: choosing_region)
    6. back_to_main             → main menu
    7. queue_page_{n}           → paginated queue keyboard (stays in choosing_queue)
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.regions import REGIONS
from app.keyboards.inline import (
    get_blocked_keyboard,
    get_confirm_keyboard,
    get_main_menu,
    get_queue_keyboard,
    get_region_keyboard,
)
from app.services.user_service import get_or_create_user, update_user_region
from app.states.registration import RegistrationFSM

logger = logging.getLogger(__name__)
router = Router(name="start")

# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

_WELCOME_TEXT = (
    "👋 Вітаю! Я — Voltyk Bot.\n\n"
    "Я допоможу тобі слідкувати за графіками відключень електроенергії "
    "у твоєму регіоні.\n\n"
    "Для початку обери свій регіон:"
)

_CHOOSE_REGION_TEXT = "📍 Оберіть свій регіон:"

_CHOOSE_QUEUE_TEXT = "⚡ Оберіть свою чергу:"

_CONFIRM_TEXT = (
    "✅ Твої налаштування:\n\n"
    "📍 Регіон: {region_name}\n"
    "⚡ Черга: {queue}\n\n"
    "Підтверди або зміни:"
)

_MAIN_MENU_TEXT = "⚡ Головне меню\n\nОбери дію:"

_BLOCKED_TEXT = "🚫 Ви заблоковані."


# ---------------------------------------------------------------------------
# /start command handler
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Handle the /start command.

    Creates or updates the user record, then routes to the appropriate screen.
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    user = await get_or_create_user(session, tg_user)

    if user.is_blocked:
        await message.answer(_BLOCKED_TEXT, reply_markup=get_blocked_keyboard())
        return

    if user.region_id and user.queue:
        # Fully registered — show main menu
        await state.clear()
        await message.answer(_MAIN_MENU_TEXT, reply_markup=get_main_menu())
    else:
        # New user or incomplete registration — start wizard
        await state.set_state(RegistrationFSM.choosing_region)
        await message.answer(_WELCOME_TEXT, reply_markup=get_region_keyboard())


# ---------------------------------------------------------------------------
# Region selection
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("region_"))
async def cb_region_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Handle region button press."""
    await callback.answer()

    region_code = callback.data.removeprefix("region_")  # type: ignore[union-attr]
    if region_code not in REGIONS:
        logger.warning("Unknown region_code=%r from callback", region_code)
        return

    await state.update_data(region_code=region_code)
    await state.set_state(RegistrationFSM.choosing_queue)

    assert callback.message is not None
    await callback.message.edit_text(
        _CHOOSE_QUEUE_TEXT,
        reply_markup=get_queue_keyboard(region=region_code, page=1),
    )


# ---------------------------------------------------------------------------
# Queue selection
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("queue_page_"))
async def cb_queue_page(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle queue pagination button for Kyiv."""
    await callback.answer()

    try:
        page = int(callback.data.removeprefix("queue_page_"))  # type: ignore[union-attr]
    except ValueError:
        logger.warning("Invalid queue_page callback data: %r", callback.data)
        return

    fsm_data = await state.get_data()
    region_code = fsm_data.get("region_code", "kyiv")

    assert callback.message is not None
    await callback.message.edit_text(
        _CHOOSE_QUEUE_TEXT,
        reply_markup=get_queue_keyboard(region=region_code, page=page),
    )


@router.callback_query(F.data.startswith("queue_") & ~F.data.startswith("queue_page_"))
async def cb_queue_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle queue button press."""
    await callback.answer()

    queue_str = callback.data.removeprefix("queue_")  # type: ignore[union-attr]
    await state.update_data(queue=queue_str)
    await state.set_state(RegistrationFSM.confirming)

    fsm_data = await state.get_data()
    region_code = fsm_data.get("region_code", "")
    region_name = REGIONS.get(region_code, {}).get("name", region_code)

    text = _CONFIRM_TEXT.format(region_name=region_name, queue=queue_str)

    assert callback.message is not None
    await callback.message.edit_text(text, reply_markup=get_confirm_keyboard())


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "confirm_setup")
async def cb_confirm_setup(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Save the chosen region+queue to the DB and show the main menu."""
    await callback.answer()

    fsm_data = await state.get_data()
    region_code: str = fsm_data.get("region_code", "")
    queue_str: str = fsm_data.get("queue", "")

    if not region_code or not queue_str:
        logger.warning("confirm_setup called with incomplete FSM data: %r", fsm_data)
        return

    assert callback.from_user is not None
    await update_user_region(session, callback.from_user.id, region_code, queue_str)
    await state.clear()

    assert callback.message is not None
    await callback.message.edit_text(_MAIN_MENU_TEXT, reply_markup=get_main_menu())


# ---------------------------------------------------------------------------
# Navigation callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "back_to_region")
async def cb_back_to_region(callback: CallbackQuery, state: FSMContext) -> None:
    """Go back to the region selection screen."""
    await callback.answer()
    await state.set_state(RegistrationFSM.choosing_region)

    assert callback.message is not None
    await callback.message.edit_text(
        _CHOOSE_REGION_TEXT, reply_markup=get_region_keyboard()
    )


@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Go to the main menu, clearing FSM state."""
    await callback.answer()
    await state.clear()

    assert callback.message is not None
    await callback.message.edit_text(_MAIN_MENU_TEXT, reply_markup=get_main_menu())


@router.callback_query(F.data == "suggest_region")
async def cb_suggest_region(callback: CallbackQuery) -> None:
    """Acknowledge the 'suggest a region' button."""
    await callback.answer(
        "Напиши нам у підтримку — ми розглянемо додавання нового регіону! 🙏",
        show_alert=True,
    )


@router.callback_query(F.data == "contact_admin")
async def cb_contact_admin(callback: CallbackQuery) -> None:
    """Acknowledge the 'contact admin' button for blocked users."""
    await callback.answer(
        "Зверніться до адміністратора бота для розблокування.",
        show_alert=True,
    )
