"""Address check handler.

Allows anyone to check the DTEK emergency outage status and scheduled queue (черга)
for any address, without setting up persistent monitoring.
"""
from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from playwright.async_api import async_playwright

from bot.constants.regions import REGIONS
from bot.keyboards.inline import (
    get_address_check_cancel_keyboard,
    get_address_check_region_keyboard,
    get_address_check_result_keyboard,
)
from bot.services.emergency_monitor import (
    _extract_queue,
    _fetch_region_data,
    _find_outage_for_house,
)
from bot.states.fsm import AddressCheckSG
from bot.utils.logger import get_logger

router = Router(name="address_check")
logger = get_logger(__name__)

_REGIONS_NEEDING_CITY = {"kyiv-region", "dnipro", "odesa"}
_MAX_CITY_LEN = 64
_MAX_STREET_LEN = 128
_MAX_HOUSE_LEN = 16


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _format_result(region: str, city: str | None, street: str, house: str, response: dict | None) -> str:
    region_name = REGIONS[region].name if region in REGIONS else region
    parts = []
    if city:
        parts.append(city)
    parts.append(street)
    parts.append(f"буд. {house}")
    addr = ", ".join(parts)

    if response is None:
        return (
            "🔍 Перевірка адреси\n\n"
            f"📍 {region_name}: {addr}\n\n"
            "⚠️ Таймаут або мережева помилка.\n"
            "Перевір з'єднання бота з інтернетом."
        )

    exc_info = response.get("_exception")
    if exc_info:
        if "No AJAX response" in exc_info or "street not found" in exc_info.lower():
            return (
                "🔍 Перевірка адреси\n\n"
                f"📍 {region_name}: {addr}\n\n"
                "⚠️ Адресу не знайдено в базі ДТЕК.\n\n"
                "Перевір правильність назви — вулиця та місто мають збігатися з назвами на сайті ДТЕК "
                "(наприклад: <b>с. Нижча Дубечня</b>, <b>вул. Деснянська</b>)"
            )
        return (
            "🔍 Перевірка адреси\n\n"
            f"📍 {region_name}: {addr}\n\n"
            f"⚠️ Помилка з'єднання з ДТЕК:\n<code>{html.escape(exc_info)}</code>"
        )

    error_status = response.get("_error")
    if error_status:
        body = response.get("_body", "")
        detail = f"\n<code>{html.escape(body[:120])}</code>" if body else ""
        return (
            "🔍 Перевірка адреси\n\n"
            f"📍 {region_name}: {addr}\n\n"
            f"⚠️ ДТЕК HTTP {error_status}{detail}\n\n"
            "Переконайся, що введено точну назву як на сайті ДТЕК\n"
            "(наприклад: <b>с. Нижча Дубечня</b>, <b>вул. Деснянська</b>)"
        )

    queue = _extract_queue(response, house)
    outage = _find_outage_for_house(response, house)

    lines = [
        "🔍 Перевірка адреси\n",
        f"📍 {region_name}: {addr}",
        f"🔢 Черга: <b>{queue}</b>" if queue else "🔢 Черга: не визначено",
        "",
    ]
    if outage:
        start = outage.get("start_date", "—")
        end = outage.get("end_date", "—")
        sub_type = outage.get("sub_type", "Аварійне відключення")
        lines += [f"🚨 {sub_type}", f"⏰ {start} – {end}"]
    else:
        lines.append("✅ Аварійних відключень не виявлено")

    return "\n".join(lines)


async def _fetch_and_show(
    target: Message | CallbackQuery,
    region: str,
    city: str | None,
    street: str,
    house: str,
) -> None:
    # Show "loading" immediately — Playwright/Chromium takes 5-15 s
    loading_msg: Message | None = None
    if isinstance(target, Message):
        loading_msg = await target.answer("⏳ Перевіряємо адресу, зачекайте...")
    else:
        try:
            await target.message.edit_text("⏳ Перевіряємо адресу, зачекайте...")
        except Exception:
            pass

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            response = await _fetch_region_data(browser, region, street, city)
        except Exception as e:
            logger.error("address_check fetch error: %s", e)
            response = None
        finally:
            await browser.close()

    text = _format_result(region, city, street, house, response)
    keyboard = get_address_check_result_keyboard()

    if loading_msg:
        await loading_msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await target.message.edit_text(text, reply_markup=keyboard)


# ─── Entry ────────────────────────────────────────────────────────────────


@router.callback_query(F.data == "address_check_start")
async def address_check_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(AddressCheckSG.waiting_for_region)
    try:
        await callback.message.edit_text(
            "🔍 Перевірка адреси\n\nОберіть регіон:",
            reply_markup=get_address_check_region_keyboard(),
        )
    except Exception:
        await callback.message.answer(
            "🔍 Перевірка адреси\n\nОберіть регіон:",
            reply_markup=get_address_check_region_keyboard(),
        )


# ─── Cancel (any step) ────────────────────────────────────────────────────


@router.callback_query(F.data == "ac_cancel")
async def address_check_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "🔍 Перевірку скасовано.",
        reply_markup=get_address_check_result_keyboard(),
    )


# ─── Region selection ─────────────────────────────────────────────────────


@router.callback_query(AddressCheckSG.waiting_for_region, F.data.startswith("ac_region_"))
async def address_check_region(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    region = callback.data.removeprefix("ac_region_")
    if region not in REGIONS:
        return
    await state.update_data(region=region)

    if region in _REGIONS_NEEDING_CITY:
        await state.set_state(AddressCheckSG.waiting_for_city)
        await callback.message.edit_text(
            "🏙 Введіть назву міста або населеного пункту:",
            reply_markup=get_address_check_cancel_keyboard(),
        )
    else:
        await state.update_data(city=None)
        await state.set_state(AddressCheckSG.waiting_for_street)
        await callback.message.edit_text(
            "🏠 Введіть назву вулиці:",
            reply_markup=get_address_check_cancel_keyboard(),
        )


# ─── City input ───────────────────────────────────────────────────────────


@router.message(AddressCheckSG.waiting_for_city)
async def address_check_city(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть назву міста.")
        return
    city = _clean(message.text)
    if len(city) < 2 or len(city) > _MAX_CITY_LEN:
        await message.reply(f"❌ Від 2 до {_MAX_CITY_LEN} символів.")
        return
    await state.update_data(city=city)
    await state.set_state(AddressCheckSG.waiting_for_street)
    await message.answer("🏠 Введіть назву вулиці:", reply_markup=get_address_check_cancel_keyboard())


# ─── Street input ─────────────────────────────────────────────────────────


@router.message(AddressCheckSG.waiting_for_street)
async def address_check_street(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть назву вулиці.")
        return
    street = _clean(message.text)
    if len(street) < 2 or len(street) > _MAX_STREET_LEN:
        await message.reply(f"❌ Від 2 до {_MAX_STREET_LEN} символів.")
        return
    await state.update_data(street=street)
    await state.set_state(AddressCheckSG.waiting_for_house)
    await message.answer("🔢 Введіть номер будинку:", reply_markup=get_address_check_cancel_keyboard())


# ─── House input → fetch + show result ───────────────────────────────────


@router.message(AddressCheckSG.waiting_for_house)
async def address_check_house(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть номер будинку.")
        return
    house = _clean(message.text)
    if len(house) < 1 or len(house) > _MAX_HOUSE_LEN:
        await message.reply(f"❌ Від 1 до {_MAX_HOUSE_LEN} символів.")
        return

    data = await state.get_data()
    await state.clear()

    region = data.get("region")
    city = data.get("city")
    street = data.get("street")

    if not region or not street:
        await message.reply("❌ Щось пішло не так. Спробуйте знову.")
        return

    await _fetch_and_show(message, region, city, street, house)
