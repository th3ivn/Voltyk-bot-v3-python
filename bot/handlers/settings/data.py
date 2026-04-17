from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.queries import deactivate_user, delete_user_data
from bot.keyboards.inline import (
    get_deactivate_confirm_keyboard,
    get_delete_data_confirm_keyboard,
    get_delete_data_final_keyboard,
)
from bot.utils.metrics import USER_DEACTIVATIONS_TOTAL, USER_DELETIONS_TOTAL

router = Router(name="settings_data")


@router.callback_query(F.data == "settings_delete_data")
async def settings_delete_data(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "⚠️ Увага\n\nВидалити всі дані:\n"
        "• Профіль та налаштування\n"
        "• Канал та його налаштування\n"
        "• Історію та статистику\n"
        "• Сповіщення\n\n"
        "Цю дію неможливо скасувати.",
        reply_markup=get_delete_data_confirm_keyboard(),
    )


@router.callback_query(F.data == "delete_data_step2")
async def delete_data_step2(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "❗ Підтвердження\n\nВидалити всі дані? Цю дію неможливо скасувати.",
        reply_markup=get_delete_data_final_keyboard(),
    )


@router.callback_query(F.data == "confirm_delete_data")
async def confirm_delete_data(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await delete_user_data(session, callback.from_user.id)
    USER_DELETIONS_TOTAL.inc()
    await callback.message.edit_text(
        "Добре, домовились 🙂 Я видалив усі дані та відключив канал.\n\n"
        "Якщо захочете повернутися — /start"
    )


@router.callback_query(F.data == "settings_deactivate")
async def settings_deactivate(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "❗️ Ви впевнені, що хочете деактивувати бота?",
        reply_markup=get_deactivate_confirm_keyboard(),
    )


@router.callback_query(F.data == "confirm_deactivate")
async def confirm_deactivate(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await deactivate_user(session, callback.from_user.id)
    USER_DEACTIVATIONS_TOTAL.inc()
    await callback.message.edit_text(
        "✅ Бот деактивовано. Використайте /start для повторної активації."
    )
