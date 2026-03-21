from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_admin_router, upsert_admin_router
from bot.keyboards.inline import get_admin_router_keyboard
from bot.states.fsm import AdminRouterIpSG
from bot.utils.helpers import is_valid_ip_or_domain

router = Router(name="admin_router")


@router.callback_query(F.data.in_({"admin_router", "admin_router_refresh"}))
async def admin_router_view(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    ar = await get_admin_router(session, callback.from_user.id)
    has_ip = bool(ar and ar.router_ip)
    notif = ar.notifications_on if ar else True
    ip_text = f"\n📡 IP: {ar.router_ip}" if has_ip else "\n📡 IP: не налаштовано"
    state_text = ""
    if ar and ar.last_state:
        state_text = f"\n🔌 Стан: {ar.last_state}"
    await callback.message.edit_text(
        f"📡 Роутер{ip_text}{state_text}",
        reply_markup=get_admin_router_keyboard(has_ip=has_ip, notifications_on=notif),
    )


@router.callback_query(F.data == "admin_router_set_ip")
async def admin_router_set_ip(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.set_state(AdminRouterIpSG.waiting_for_ip)
    await callback.message.edit_text(
        "✏️ Введіть IP-адресу роутера:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_router")]]
        ),
    )


@router.message(AdminRouterIpSG.waiting_for_ip)
async def admin_router_ip_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    result = is_valid_ip_or_domain(message.text)
    if not result["valid"]:
        await message.reply(f"❌ {result['error']}")
        return

    await upsert_admin_router(
        session,
        message.from_user.id,
        router_ip=result["host"],
        router_port=result.get("port") or 80,
    )
    await state.clear()
    await message.answer(f"✅ IP збережено: {result['address']}")


@router.callback_query(F.data == "admin_router_toggle_notify")
async def admin_router_toggle_notify(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    ar = await get_admin_router(session, callback.from_user.id)
    if ar:
        ar.notifications_on = not ar.notifications_on
        await callback.answer(f"{'✅ Увімкнено' if ar.notifications_on else '❌ Вимкнено'}")
    else:
        await callback.answer()


@router.callback_query(F.data == "admin_router_stats")
async def admin_router_stats(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer("⚠️ Статистика роутера в розробці", show_alert=True)
