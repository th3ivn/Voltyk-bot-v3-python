from __future__ import annotations

import sys

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.config import settings
from bot.keyboards.inline import get_restart_confirm_keyboard

router = Router(name="admin_database")


@router.callback_query(F.data == "admin_clear_db")
async def admin_clear_db(callback: CallbackQuery) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Тільки для власника")
        return
    await callback.answer("⚠️ Ця функція вимкнена з безпеки", show_alert=True)


@router.callback_query(F.data == "admin_restart")
async def admin_restart(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔄 Перезапуск бота?\n\nЦе зупинить бота на кілька секунд.",
        reply_markup=get_restart_confirm_keyboard(),
    )


@router.callback_query(F.data == "admin_restart_confirm")
async def admin_restart_confirm(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer("🔄 Перезапуск...")
    await callback.message.edit_text("🔄 Перезапуск бота...")
    sys.exit(0)
