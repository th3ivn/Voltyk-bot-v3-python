from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.keyboards.inline import get_maintenance_keyboard
from bot.middlewares.maintenance import (
    get_maintenance_message,
    is_maintenance_mode,
    persist_maintenance_mode,
)
from bot.states.fsm import MaintenanceSG
from bot.utils.telegram import safe_edit_text

router = Router(name="admin_maintenance")


@router.callback_query(F.data == "admin_maintenance")
async def admin_maintenance(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    enabled = is_maintenance_mode()
    msg = get_maintenance_message()
    status = "🟢 Увімкнено" if enabled else "🔴 Вимкнено"
    await safe_edit_text(callback.message,
        f"🔧 Тех. роботи\n\nСтатус: {status}\nПовідомлення: {msg}",
        reply_markup=get_maintenance_keyboard(enabled=enabled),
    )


@router.callback_query(F.data == "maintenance_toggle")
async def maintenance_toggle(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    new_enabled = not is_maintenance_mode()
    await persist_maintenance_mode(new_enabled)
    status = "🟢 Увімкнено" if new_enabled else "🔴 Вимкнено"
    msg = get_maintenance_message()
    await callback.answer(f"Тех. роботи: {status}")
    await safe_edit_text(callback.message,
        f"🔧 Тех. роботи\n\nСтатус: {status}\nПовідомлення: {msg}",
        reply_markup=get_maintenance_keyboard(enabled=new_enabled),
    )


@router.callback_query(F.data == "maintenance_edit_message")
async def maintenance_edit_message(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.set_state(MaintenanceSG.waiting_for_message)
    await safe_edit_text(callback.message, "✏️ Введіть нове повідомлення для тех. робіт:")


@router.message(MaintenanceSG.waiting_for_message)
async def maintenance_message_input(message: Message, state: FSMContext) -> None:
    if not settings.is_admin(message.from_user.id):
        await state.clear()
        return
    if not message.text:
        return
    await persist_maintenance_mode(is_maintenance_mode(), message=message.text.strip())
    await state.clear()
    await message.answer(
        f"✅ Повідомлення оновлено: {message.text.strip()}",
        reply_markup=get_maintenance_keyboard(enabled=is_maintenance_mode()),
    )
