from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import get_active_users_paginated
from bot.keyboards.inline import get_broadcast_cancel_keyboard
from bot.states.fsm import BroadcastSG
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="admin_broadcast")

BROADCAST_HEADER = '📢 <b>Повідомлення від адміністрації:</b>\n\n'


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    await state.set_state(BroadcastSG.waiting_for_text)
    await callback.message.edit_text(
        "📢 Розсилка\n\nВведіть текст повідомлення:",
        reply_markup=get_broadcast_cancel_keyboard(),
    )


@router.message(BroadcastSG.waiting_for_text)
async def broadcast_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Введіть текст повідомлення")
        return
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastSG.preview)

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Відправити", callback_data="broadcast_confirm_send")],
            [InlineKeyboardButton(text="✏️ Редагувати текст", callback_data="broadcast_edit_text")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="broadcast_cancel")],
        ]
    )
    preview = BROADCAST_HEADER + message.text
    await message.answer(f"👁 Попередній перегляд:\n\n{preview}", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "broadcast_edit_text")
async def broadcast_edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(BroadcastSG.waiting_for_text)
    await callback.message.edit_text(
        "✏️ Введіть новий текст:", reply_markup=get_broadcast_cancel_keyboard()
    )


@router.callback_query(F.data == "broadcast_confirm_send")
async def broadcast_confirm_send(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("📤 Розсилка розпочата...")

    sent = 0
    failed = 0
    full_text = BROADCAST_HEADER + text
    offset = 0
    batch_size = 500

    while True:
        batch = await get_active_users_paginated(session, limit=batch_size, offset=offset)
        if not batch:
            break
        for user in batch:
            try:
                await callback.bot.send_message(
                    int(user.telegram_id), full_text, parse_mode="HTML"
                )
                sent += 1
            except Exception as e:
                logger.warning("Broadcast failed for user %s: %s", user.telegram_id, e)
                failed += 1
        offset += len(batch)

    await callback.message.answer(
        f"✅ Розсилка завершена\n\n📤 Надіслано: {sent}\n❌ Помилок: {failed}"
    )


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Розсилку скасовано.")
