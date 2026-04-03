from __future__ import annotations

import os
import platform
import sys
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import (
    count_active_users,
    count_total_users,
    get_recent_users,
)
from bot.keyboards.inline import (
    get_admin_analytics_keyboard,
    get_admin_keyboard,
    get_admin_settings_menu_keyboard,
    get_users_menu_keyboard,
)

router = Router(name="admin_panel")

_start_time = datetime.now(timezone.utc)


def _admin_only(user_id: int) -> bool:
    return settings.is_admin(user_id)


@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession) -> None:
    if not _admin_only(message.from_user.id):
        await message.answer("❌ Доступ заборонено")
        return
    await message.answer(
        "🔧 Адмін-панель",
        reply_markup=get_admin_keyboard(),
    )


@router.callback_query(F.data == "settings_admin")
async def settings_admin(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔧 Адмін-панель",
        reply_markup=get_admin_keyboard(),
    )


@router.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔧 Адмін-панель",
        reply_markup=get_admin_keyboard(),
    )


@router.callback_query(F.data == "admin_analytics")
async def admin_analytics(callback: CallbackQuery) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text("📊 Аналітика", reply_markup=get_admin_analytics_keyboard())


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    total = await count_total_users(session)
    active = await count_active_users(session)
    text = (
        f"📊 Загальна статистика\n\n"
        f"👥 Всього користувачів: {total}\n"
        f"✅ Активних: {active}\n"
        f"❌ Неактивних: {total - active}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_analytics_keyboard())


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text("👥 Користувачі", reply_markup=get_users_menu_keyboard())


@router.callback_query(F.data == "admin_users_stats")
async def admin_users_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    total = await count_total_users(session)
    active = await count_active_users(session)
    text = f"📊 Користувачі\n\nВсього: {total}\nАктивних: {active}"
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith("admin_users_list_"))
async def admin_users_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    users = await get_recent_users(session, limit=20)
    lines = ["📋 Останні користувачі:\n"]
    for u in users:
        status = "✅" if u.is_active else "❌"
        lines.append(f"{status} {u.telegram_id} (@{u.username or '-'}) - {u.region}/{u.queue}")
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=get_users_menu_keyboard()
    )


@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ Налаштування", reply_markup=get_admin_settings_menu_keyboard()
    )


@router.callback_query(F.data == "admin_system")
async def admin_system(callback: CallbackQuery) -> None:
    if not _admin_only(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    uptime = datetime.now(timezone.utc) - _start_time
    hours = int(uptime.total_seconds() // 3600)
    minutes = int((uptime.total_seconds() % 3600) // 60)
    text = (
        f"💻 Система\n\n"
        f"🐍 Python: {sys.version.split()[0]}\n"
        f"💻 Platform: {platform.system()} {platform.release()}\n"
        f"⏱ Uptime: {hours}h {minutes}m\n"
        f"🏗 Railway: {os.getenv('RAILWAY_ENVIRONMENT', 'N/A')}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_settings_menu_keyboard())
