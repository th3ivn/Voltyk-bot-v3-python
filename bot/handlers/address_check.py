"""Address check handler.

Allows anyone to check the DTEK emergency outage status and scheduled queue (черга)
for any address, without setting up persistent monitoring.

Input format (single message after region selection):
  - Regions needing city (kyiv-region, dnipro, odesa): "Місто, Вулиця, Будинок"
  - Regions without city (kyiv): "Вулиця, Будинок"

Example: "Нижча Дубечня, Деснянська, 1"
"""
from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
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


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _address_prompt(region: str) -> str:
    if region in _REGIONS_NEEDING_CITY:
        return (
            "Введіть адресу одним повідомленням:\n"
            "<b>Населений пункт, Вулиця, Будинок</b>\n\n"
            "Приклад: <code>Нижча Дубечня, Деснянська, 1</code>"
        )
    return (
        "Введіть адресу одним повідомленням:\n"
        "<b>Вулиця, Будинок</b>\n\n"
        "Приклад: <code>Деснянська, 1</code>"
    )


def _parse_address(text: str, region: str) -> tuple[str | None, str, str] | None:
    """
    Parse address from single message.
    Returns (city, street, house) or None if format is wrong.
    """
    parts = [_clean(p) for p in text.split(",")]
    if region in _REGIONS_NEEDING_CITY:
        if len(parts) != 3 or not all(parts):
            return None
        city, street, house = parts
        return city, street, house
    else:
        if len(parts) != 2 or not all(parts):
            return None
        street, house = parts
        return None, street, house


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
        # Playwright errors are huge — truncate to avoid MESSAGE_TOO_LONG
        short_err = exc_info.split("\n")[0][:200]
        return (
            "🔍 Перевірка адреси\n\n"
            f"📍 {region_name}: {addr}\n\n"
            f"⚠️ Помилка з'єднання з ДТЕК:\n<code>{html.escape(short_err)}</code>"
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
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-sync",
            ],
        )
        try:
            response = await _fetch_region_data(browser, region, street, city, house)
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

    # Send debug screenshot if autocomplete failed
    if response and response.get("_debug_screenshot"):
        chat_id = target.chat.id if isinstance(target, Message) else target.message.chat.id
        photo = BufferedInputFile(response["_debug_screenshot"], filename="dtek_debug.png")
        bot = target.bot if isinstance(target, Message) else target.message.bot
        await bot.send_photo(chat_id, photo, caption="🔍 Debug: скріншот сторінки ДТЕК у момент помилки")


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
    await state.set_state(AddressCheckSG.waiting_for_address)
    await callback.message.edit_text(
        _address_prompt(region),
        parse_mode="HTML",
        reply_markup=get_address_check_cancel_keyboard(),
    )


# ─── Address input (single message) ───────────────────────────────────────


@router.message(AddressCheckSG.waiting_for_address)
async def address_check_address(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть адресу текстом.")
        return

    data = await state.get_data()
    region = data.get("region")
    if not region:
        await message.reply("❌ Щось пішло не так. Спробуйте знову.")
        await state.clear()
        return

    parsed = _parse_address(message.text, region)
    if parsed is None:
        await message.reply(
            f"❌ Невірний формат. {_address_prompt(region)}",
            parse_mode="HTML",
        )
        return

    city, street, house = parsed
    await state.clear()
    await _fetch_and_show(message, region, city, street, house)
