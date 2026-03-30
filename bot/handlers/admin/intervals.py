from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_setting, set_setting
from bot.keyboards.inline import (
    get_admin_intervals_keyboard,
    get_ip_interval_keyboard,
    get_refresh_cooldown_keyboard,
    get_schedule_interval_keyboard,
)

router = Router(name="admin_intervals")


@router.callback_query(F.data == "admin_intervals")
async def admin_intervals(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    await callback.answer()
    sched = int(await get_setting(session, "schedule_check_interval") or "180")
    ip = int(await get_setting(session, "power_check_interval") or "10")
    await callback.message.edit_text(
        "⏱ Інтервали",
        reply_markup=get_admin_intervals_keyboard(schedule_interval=sched, ip_interval=ip),
    )


@router.callback_query(F.data == "admin_interval_schedule")
async def admin_interval_schedule(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    await callback.answer()
    current = int(await get_setting(session, "schedule_check_interval") or "180")
    await callback.message.edit_text(
        "⏱ Інтервал перевірки графіків",
        reply_markup=get_schedule_interval_keyboard(current_seconds=current),
    )


@router.callback_query(F.data.startswith("admin_schedule_"))
async def admin_schedule_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    minutes = int(callback.data.replace("admin_schedule_", ""))
    seconds = minutes * 60
    await set_setting(session, "schedule_check_interval", str(seconds))
    await callback.answer(f"✅ Інтервал: {minutes} хв")
    await callback.message.edit_reply_markup(
        reply_markup=get_schedule_interval_keyboard(current_seconds=seconds)
    )


@router.callback_query(F.data == "admin_interval_ip")
async def admin_interval_ip(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    await callback.answer()
    current = int(await get_setting(session, "power_check_interval") or "10")
    await callback.message.edit_text(
        "📡 Інтервал перевірки IP",
        reply_markup=get_ip_interval_keyboard(current_seconds=current),
    )


@router.callback_query(F.data.startswith("admin_ip_"))
async def admin_ip_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    seconds = int(callback.data.replace("admin_ip_", ""))
    await set_setting(session, "power_check_interval", str(seconds))
    label = "Динамічний" if seconds == 0 else f"{seconds} сек"
    await callback.answer(f"✅ Інтервал: {label}")
    await callback.message.edit_reply_markup(
        reply_markup=get_ip_interval_keyboard(current_seconds=seconds)
    )


@router.callback_query(F.data == "admin_refresh_cooldown")
async def admin_refresh_cooldown(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    await callback.answer()
    current = int(await get_setting(session, "refresh_cooldown") or "30")
    await callback.message.edit_text(
        "🔄 Cooldown кнопки «Перевірити»\n\nЧас очікування між натисканнями для одного юзера:",
        reply_markup=get_refresh_cooldown_keyboard(current_seconds=current),
    )


@router.callback_query(F.data.startswith("admin_cooldown_set_"))
async def admin_cooldown_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено. Тільки головний адмін може змінювати ці налаштування")
        return
    seconds = int(callback.data.replace("admin_cooldown_set_", ""))
    await set_setting(session, "refresh_cooldown", str(seconds))
    await callback.answer(f"✅ Cooldown: {seconds} сек")
    await callback.message.edit_reply_markup(
        reply_markup=get_refresh_cooldown_keyboard(current_seconds=seconds)
    )
