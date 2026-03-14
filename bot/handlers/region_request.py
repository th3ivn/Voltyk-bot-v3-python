from __future__ import annotations

from bot.utils.logger import get_logger

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import add_ticket_message, create_ticket
from bot.keyboards.inline import get_broadcast_cancel_keyboard, get_region_request_confirm_keyboard
from bot.states.fsm import RegionRequestSG

logger = get_logger(__name__)
router = Router(name="region_request")


@router.callback_query(F.data == "region_request_start")
async def region_request_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(RegionRequestSG.waiting_for_text)
    await callback.message.edit_text(
        "🏙 Запит на новий регіон\n\n"
        "Введіть назву міста або регіону, який ви хочете додати.\n\n"
        "Приклад: Житомир, Вінниця, Черкаси\n\n"
        "⏱ У вас є 5 хвилин на введення.",
        reply_markup=get_broadcast_cancel_keyboard(),
    )


@router.message(RegionRequestSG.waiting_for_text)
async def region_request_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply("❌ Будь ласка, введіть текст з назвою регіону.")
        return

    text = message.text.strip()
    if len(text) < 2:
        await message.reply("❌ Назва регіону занадто коротка. Спробуйте ще раз.")
        return
    if len(text) > 100:
        await message.reply("❌ Назва регіону занадто довга. Спробуйте ще раз.")
        return

    await state.update_data(region_name=text)
    await state.set_state(RegionRequestSG.confirming)
    await message.answer(
        f'📋 Ви хочете додати регіон: "{text}"\n\nНадіслати запит?',
        reply_markup=get_region_request_confirm_keyboard(),
    )


@router.callback_query(RegionRequestSG.confirming, F.data == "region_request_confirm")
async def region_request_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    data = await state.get_data()
    region_name = data.get("region_name", "")

    ticket = await create_ticket(
        session, callback.from_user.id, "region_request", subject=region_name
    )
    await add_ticket_message(
        session,
        ticket.id,
        sender_type="user",
        sender_id=callback.from_user.id,
        content=f"Запит на додавання регіону: {region_name}",
    )
    await state.clear()

    await callback.message.edit_text(
        f"✅ Дякуємо за запит!\n\n"
        f'Ваш запит #{ticket.id} на додавання регіону "{region_name}" прийнято.\n\n'
        "Ми розглянемо його найближчим часом."
    )

    for admin_id in settings.all_admin_ids:
        try:
            await callback.bot.send_message(
                admin_id,
                f"🏙 Запит на регіон #{ticket.id}\n"
                f"Від: {callback.from_user.id}\n"
                f"Регіон: {region_name}",
            )
        except Exception:
            pass


@router.callback_query(F.data == "region_request_cancel")
async def region_request_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Запит скасовано.")
