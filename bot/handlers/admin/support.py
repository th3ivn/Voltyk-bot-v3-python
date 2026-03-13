from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_setting, set_setting
from bot.keyboards.inline import get_admin_support_keyboard
from bot.states.fsm import AdminSupportUrlSG

router = Router(name="admin_support")


@router.callback_query(F.data == "admin_support")
async def admin_support(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    mode = await get_setting(session, "support_mode") or "bot"
    url = await get_setting(session, "support_url")
    await callback.message.edit_text(
        "📞 Підтримка",
        reply_markup=get_admin_support_keyboard(current_mode=mode, support_url=url),
    )


@router.callback_query(F.data == "admin_support_channel")
async def admin_support_channel(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await set_setting(session, "support_mode", "channel")
    url = await get_setting(session, "support_url")
    await callback.answer("✅ Режим: канал")
    await callback.message.edit_reply_markup(
        reply_markup=get_admin_support_keyboard(current_mode="channel", support_url=url)
    )


@router.callback_query(F.data == "admin_support_bot")
async def admin_support_bot(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await set_setting(session, "support_mode", "bot")
    await callback.answer("✅ Режим: бот")
    await callback.message.edit_reply_markup(
        reply_markup=get_admin_support_keyboard(current_mode="bot")
    )


@router.callback_query(F.data == "admin_support_edit_url")
async def admin_support_edit_url(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.set_state(AdminSupportUrlSG.waiting_for_url)
    await callback.message.edit_text("✏️ Введіть URL підтримки (наприклад https://t.me/support):")


@router.message(AdminSupportUrlSG.waiting_for_url)
async def admin_support_url_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    url = message.text.strip()
    await set_setting(session, "support_url", url)
    await state.clear()
    await message.answer(f"✅ URL збережено: {url}")
