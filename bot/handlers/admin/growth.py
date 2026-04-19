from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import count_active_users, get_setting, set_setting
from bot.keyboards.inline import (
    get_growth_keyboard,
    get_growth_registration_keyboard,
    get_growth_stage_keyboard,
)
from bot.utils.telegram import safe_edit_text

router = Router(name="admin_growth")


@router.callback_query(F.data == "admin_growth")
async def admin_growth(callback: CallbackQuery) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await safe_edit_text(callback.message, "📈 Ріст / Growth", reply_markup=get_growth_keyboard())


@router.callback_query(F.data == "growth_metrics")
async def growth_metrics(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    active = await count_active_users(session)
    stage = await get_setting(session, "growth_stage") or "0"
    text = f"📊 Метрики росту\n\n👥 Активних: {active}\n🎯 Етап: {stage}"
    await callback.answer(text, show_alert=True)


@router.callback_query(F.data == "growth_stage")
async def growth_stage(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    current = int(await get_setting(session, "growth_stage") or "0")
    await safe_edit_text(callback.message,
        "🎯 Етап росту",
        reply_markup=get_growth_stage_keyboard(current_stage=current),
    )


@router.callback_query(F.data.startswith("growth_stage_"))
async def growth_stage_set(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    stage = callback.data.replace("growth_stage_", "")
    try:
        stage_int = int(stage)
    except (ValueError, TypeError):
        await callback.answer()
        return
    await set_setting(session, "growth_stage", stage)
    await callback.answer(f"✅ Етап встановлено: {stage}")
    await callback.message.edit_reply_markup(
        reply_markup=get_growth_stage_keyboard(current_stage=stage_int)
    )


@router.callback_query(F.data == "growth_registration")
async def growth_registration(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    enabled = (await get_setting(session, "registration_enabled") or "true") != "false"
    await safe_edit_text(callback.message,
        "🔐 Реєстрація",
        reply_markup=get_growth_registration_keyboard(enabled=enabled),
    )


@router.callback_query(F.data == "growth_reg_toggle")
async def growth_reg_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    current = (await get_setting(session, "registration_enabled") or "true") != "false"
    new_val = "false" if current else "true"
    await set_setting(session, "registration_enabled", new_val)
    enabled = new_val != "false"
    await callback.answer("✅ Збережено")
    await callback.message.edit_reply_markup(
        reply_markup=get_growth_registration_keyboard(enabled=enabled)
    )


@router.callback_query(F.data == "growth_reg_status")
async def growth_reg_status(callback: CallbackQuery, session: AsyncSession) -> None:
    enabled = (await get_setting(session, "registration_enabled") or "true") != "false"
    await callback.answer(f"{'🟢 Увімкнена' if enabled else '🔴 Вимкнена'}")


@router.callback_query(F.data == "growth_events")
async def growth_events(callback: CallbackQuery) -> None:
    await callback.answer("⚠️ Ця функція в розробці", show_alert=True)
