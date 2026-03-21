"""Emergency outage address setup handler.

Allows users to configure their home address for DTEK emergency outage monitoring.
- Kyiv region: street + house only
- Other regions: city + street + house
"""
from __future__ import annotations

import re

import aiohttp
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings as app_settings
from bot.db.queries import (
    delete_user_emergency_config,
    get_user_by_telegram_id,
    upsert_user_emergency_config,
)
from bot.formatter.messages import format_live_status_message
from bot.keyboards.inline import (
    get_emergency_cancel_keyboard,
    get_emergency_change_confirm_keyboard,
    get_emergency_delete_confirm_keyboard,
    get_emergency_management_keyboard,
    get_emergency_no_address_keyboard,
    get_emergency_saved_keyboard,
    get_settings_keyboard,
)
from bot.services.emergency_monitor import _fetch_region_data, _find_outage_for_house
from bot.states.fsm import EmergencySetupSG
from bot.utils.logger import get_logger

router = Router(name="settings_emergency")
logger = get_logger(__name__)

# Regions that require a city field
_REGIONS_NEEDING_CITY = {"kyiv-region", "dnipro", "odesa"}

_MAX_CITY_LEN = 64
_MAX_STREET_LEN = 128
_MAX_HOUSE_LEN = 16


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


async def _safe_edit(message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, parse_mode="HTML", **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.warning("_safe_edit TelegramBadRequest: %s", e)
        try:
            await message.edit_text(text, **kwargs)
        except Exception as e2:
            logger.error("_safe_edit fallback failed: %s", e2)
    except Exception as e:
        logger.warning("_safe_edit failed: %s", e)
        try:
            await message.edit_text(text, **kwargs)
        except Exception as e2:
            logger.error("_safe_edit fallback failed: %s", e2)


async def _show_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    is_admin = app_settings.is_admin(callback.from_user.id)
    text = format_live_status_message(user)
    await _safe_edit(callback.message, text, reply_markup=get_settings_keyboard(is_admin=is_admin))


def _format_address(cfg) -> str:
    parts = []
    if cfg.city:
        parts.append(cfg.city)
    if cfg.street:
        parts.append(cfg.street)
    if cfg.house:
        parts.append(f"буд. {cfg.house}")
    return ", ".join(parts)


def _format_outage_status(state) -> str:
    if state is None or state.status == "none":
        return "✅ Аварій не виявлено"
    return (
        f"🚨 Аварійне відключення\n"
        f"  {state.start_date} – {state.end_date}"
    )


async def _show_management_screen(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.emergency_config:
        await _show_no_address_screen(callback)
        return
    cfg = user.emergency_config
    state = user.emergency_state
    addr = _format_address(cfg)
    outage_status = _format_outage_status(state)
    text = (
        "🚨 Моніторинг аварійних відключень\n\n"
        f"📍 Адреса: {addr}\n\n"
        f"{outage_status}"
    )
    await _safe_edit(callback.message, text, reply_markup=get_emergency_management_keyboard())


async def _show_no_address_screen(callback: CallbackQuery) -> None:
    text = (
        "🚨 Моніторинг аварійних відключень\n\n"
        "Адреса не налаштована.\n\n"
        "Бот перевіряє сайт ДТЕК і сповіщає вас про аварійні відключення "
        "за вашою адресою.\n\n"
        "<i>Вкажіть адресу, щоб увімкнути моніторинг.</i>"
    )
    await _safe_edit(callback.message, text, reply_markup=get_emergency_no_address_keyboard())


async def _start_address_input(callback: CallbackQuery, state: FSMContext, region: str) -> None:
    if region in _REGIONS_NEEDING_CITY:
        await _safe_edit(
            callback.message,
            "🏙 Введіть назву вашого міста:",
            reply_markup=get_emergency_cancel_keyboard(),
        )
        await state.set_state(EmergencySetupSG.waiting_for_city)
    else:
        # Kyiv — skip city step
        await state.update_data(city=None)
        await _safe_edit(
            callback.message,
            "🏠 Введіть назву вашої вулиці:",
            reply_markup=get_emergency_cancel_keyboard(),
        )
        await state.set_state(EmergencySetupSG.waiting_for_street)


# ─── Entry point ──────────────────────────────────────────────────────────


@router.callback_query(F.data == "settings_emergency")
async def settings_emergency(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    await state.clear()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    try:
        if user.emergency_config and user.emergency_config.street:
            await _show_management_screen(callback, session)
        else:
            await _show_no_address_screen(callback)
    except Exception as e:
        logger.error("settings_emergency error for user %s: %s", callback.from_user.id, e)
        await callback.message.edit_text("❌ Виникла помилка. Спробуйте ще раз.")


# ─── Setup (new address) ──────────────────────────────────────────────────


@router.callback_query(F.data == "emergency_setup")
async def emergency_setup(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.message.edit_text("❌ Спочатку запустіть бота, натиснувши /start")
        return
    await _start_address_input(callback, state, user.region)


# ─── Check now ────────────────────────────────────────────────────────────


@router.callback_query(F.data == "emergency_check_now")
async def emergency_check_now(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer("Перевіряю ДТЕК...")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.emergency_config:
        await callback.message.edit_text("❌ Адреса не налаштована.")
        return

    cfg = user.emergency_config
    addr = _format_address(cfg)

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as http_session:
        try:
            response = await _fetch_region_data(
                http_session,
                user.region,
                cfg.street or "",
                cfg.city,
            )
        except Exception as e:
            logger.error("emergency_check_now fetch error: %s", e)
            response = None

    if response is None:
        text = (
            "🚨 Моніторинг аварійних відключень\n\n"
            f"📍 {addr}\n\n"
            "⚠️ Не вдалося отримати дані від ДТЕК.\n"
            "Сайт тимчасово недоступний або змінив формат відповіді."
        )
    else:
        outage = _find_outage_for_house(response, cfg.house or "")
        if outage:
            start = outage.get("start_date", "—")
            end = outage.get("end_date", "—")
            sub_type = outage.get("sub_type", "Аварійне відключення")
            text = (
                "🚨 Моніторинг аварійних відключень\n\n"
                f"📍 {addr}\n\n"
                f"🚨 {sub_type}\n"
                f"⏰ {start} – {end}"
            )
        else:
            text = (
                "🚨 Моніторинг аварійних відключень\n\n"
                f"📍 {addr}\n\n"
                "✅ Аварійних відключень не виявлено"
            )

    await _safe_edit(callback.message, text, reply_markup=get_emergency_management_keyboard())


# ─── Change confirm ───────────────────────────────────────────────────────


@router.callback_query(F.data == "emergency_change")
async def emergency_change(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.emergency_config:
        await callback.message.edit_text("❌ Адреса не налаштована.")
        return
    addr = _format_address(user.emergency_config)
    text = f"Зміна адреси\n\nПоточна адреса: {addr}\n\nВи впевнені що хочете змінити адресу?"
    await _safe_edit(callback.message, text, reply_markup=get_emergency_change_confirm_keyboard())


@router.callback_query(F.data == "emergency_change_confirm")
async def emergency_change_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    await _start_address_input(callback, state, user.region)


# ─── Delete confirm ───────────────────────────────────────────────────────


@router.callback_query(F.data == "emergency_delete_confirm")
async def emergency_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user or not user.emergency_config:
        await callback.message.edit_text("❌ Адреса не налаштована.")
        return
    addr = _format_address(user.emergency_config)
    text = f"Видалення адреси\n\nВи впевнені що хочете видалити адресу\n{addr}?\n\nМоніторинг аварій буде вимкнено."
    await _safe_edit(callback.message, text, reply_markup=get_emergency_delete_confirm_keyboard())


@router.callback_query(F.data == "emergency_delete_execute")
async def emergency_delete_execute(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user:
        try:
            await delete_user_emergency_config(session, user.id)
        except Exception as e:
            logger.error("emergency_delete_execute error: %s", e)
    text = "✅ Адресу видалено\n\nМоніторинг аварійних відключень вимкнено."
    await _safe_edit(callback.message, text, reply_markup=get_emergency_saved_keyboard())


# ─── Navigation ───────────────────────────────────────────────────────────


@router.callback_query(F.data == "emergency_cancel_to_settings")
async def emergency_cancel_to_settings(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    await state.clear()
    await _show_settings(callback, session)


@router.callback_query(F.data == "emergency_cancel_to_management")
async def emergency_cancel_to_management(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await callback.answer()
    await state.clear()
    await _show_management_screen(callback, session)


# ─── FSM: city input ─────────────────────────────────────────────────────


@router.message(EmergencySetupSG.waiting_for_city)
async def emergency_city_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть назву міста.")
        return
    city = _clean(message.text)
    if len(city) < 2 or len(city) > _MAX_CITY_LEN:
        await message.reply(f"❌ Назва міста має бути від 2 до {_MAX_CITY_LEN} символів.")
        return
    await state.update_data(city=city)
    await message.answer(
        "🏠 Введіть назву вашої вулиці:",
        reply_markup=get_emergency_cancel_keyboard(),
    )
    await state.set_state(EmergencySetupSG.waiting_for_street)


# ─── FSM: street input ────────────────────────────────────────────────────


@router.message(EmergencySetupSG.waiting_for_street)
async def emergency_street_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть назву вулиці.")
        return
    street = _clean(message.text)
    if len(street) < 2 or len(street) > _MAX_STREET_LEN:
        await message.reply(f"❌ Назва вулиці має бути від 2 до {_MAX_STREET_LEN} символів.")
        return
    await state.update_data(street=street)
    await message.answer(
        "🏠 Введіть номер будинку:",
        reply_markup=get_emergency_cancel_keyboard(),
    )
    await state.set_state(EmergencySetupSG.waiting_for_house)


# ─── FSM: house input ─────────────────────────────────────────────────────


@router.message(EmergencySetupSG.waiting_for_house)
async def emergency_house_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        await message.reply("❌ Введіть номер будинку.")
        return
    house = _clean(message.text)
    if len(house) < 1 or len(house) > _MAX_HOUSE_LEN:
        await message.reply(f"❌ Номер будинку має бути від 1 до {_MAX_HOUSE_LEN} символів.")
        return

    data = await state.get_data()
    city = data.get("city")
    street = data.get("street")

    if not street:
        await message.reply("❌ Виникла помилка. Почніть налаштування знову.")
        await state.clear()
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.reply("❌ Спочатку запустіть бота, натиснувши /start")
        await state.clear()
        return

    try:
        await upsert_user_emergency_config(session, user.id, city=city, street=street, house=house)
    except Exception as e:
        logger.error("emergency_house_input upsert error: %s", e)
        await message.reply("❌ Помилка збереження. Спробуйте ще раз.")
        return

    await state.clear()

    parts = []
    if city:
        parts.append(city)
    parts.append(street)
    parts.append(f"буд. {house}")
    addr = ", ".join(parts)

    text = (
        "✅ Адресу збережено\n\n"
        f"📍 {addr}\n\n"
        "Бот буде сповіщати вас про аварійні відключення за цією адресою."
    )
    await message.answer(text, reply_markup=get_emergency_saved_keyboard(), parse_mode="HTML")
