from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import get_user_by_telegram_id
from bot.keyboards.inline import get_ip_cancel_keyboard, get_ip_monitoring_keyboard
from bot.states.fsm import IpSetupSG
from bot.utils.helpers import is_valid_ip_or_domain

router = Router(name="settings_ip")


@router.callback_query(F.data == "settings_ip")
async def settings_ip(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        return
    has_ip = bool(user.router_ip)
    ip_text = f"\n📡 Поточна IP: {user.router_ip}" if has_ip else ""
    await callback.message.edit_text(
        f"🌐 IP моніторинг{ip_text}",
        reply_markup=get_ip_monitoring_keyboard(has_ip=has_ip),
    )


@router.callback_query(F.data == "ip_instruction")
async def ip_instruction(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        "ℹ️ Налаштування моніторингу через IP\n\n"
        "Бот може пінгувати ваш роутер, щоб визначити,\n"
        "чи є у вас світло.\n\n"
        "Для цього потрібно:\n"
        "1. Знати IP-адресу роутера (зовнішню)\n"
        "2. Роутер має відповідати на ICMP ping\n\n"
        "Підтримуються формати:\n"
        "• 203.0.113.1\n"
        "• 203.0.113.1:8080\n"
        "• router.example.com\n"
        "• router.example.com:8080"
    )
    from bot.keyboards.inline import get_ip_monitoring_keyboard

    await callback.message.edit_text(text, reply_markup=get_ip_monitoring_keyboard())


@router.callback_query(F.data == "ip_setup")
async def ip_setup(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.router_ip:
        await callback.message.edit_text(
            f"⚠️ У вас вже додана IP-адреса: {user.router_ip}\n\nВведіть нову або скасуйте:",
            reply_markup=get_ip_cancel_keyboard(),
        )
    else:
        await callback.message.edit_text(
            "🌐 Налаштування IP\n\n"
            "Введіть IP-адресу або домен вашого роутера.\n\n"
            "Приклади:\n• 203.0.113.1\n• router.example.com\n\n"
            "⏰ Час очікування введення: 5 хвилин",
            reply_markup=get_ip_cancel_keyboard(),
        )
    await state.set_state(IpSetupSG.waiting_for_ip)


@router.message(IpSetupSG.waiting_for_ip)
async def ip_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        await message.reply("❌ Введіть IP-адресу або домен.")
        return

    result = is_valid_ip_or_domain(message.text)
    if not result["valid"]:
        await message.reply(f"❌ {result['error']}")
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user:
        user.router_ip = result["address"]

    await state.clear()
    await message.answer(
        f"✅ IP-адресу збережено: {result['address']}",
        reply_markup=get_ip_monitoring_keyboard(has_ip=True),
    )


@router.callback_query(F.data == "ip_cancel")
async def ip_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "❌ Налаштування IP скасовано.",
        reply_markup=get_ip_monitoring_keyboard(),
    )


@router.callback_query(F.data == "ip_show")
async def ip_show(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.router_ip:
        text = f"📡 Поточна IP: {user.router_ip}"
        if user.power_tracking and user.power_tracking.power_state:
            state = "🟢 Онлайн" if user.power_tracking.power_state == "on" else "🔴 Офлайн"
            text += f"\nСтатус: {state}"
        await callback.answer(text, show_alert=True)
    else:
        await callback.answer("📡 IP не налаштовано")


@router.callback_query(F.data == "ip_delete")
async def ip_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user:
        user.router_ip = None
    await callback.answer()
    await callback.message.edit_text(
        "✅ IP-адресу видалено.",
        reply_markup=get_ip_monitoring_keyboard(has_ip=False),
    )
