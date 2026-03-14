from __future__ import annotations

from bot.utils.logger import get_logger

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import add_ticket_message, create_ticket
from bot.keyboards.inline import get_feedback_confirm_keyboard, get_feedback_type_keyboard
from bot.states.fsm import FeedbackSG

logger = get_logger(__name__)
router = Router(name="feedback")

FEEDBACK_TYPES = {
    "bug": {"emoji": "🐛", "label": "Баг"},
    "idea": {"emoji": "💡", "label": "Ідея"},
    "other": {"emoji": "💬", "label": "Інше"},
}


@router.callback_query(F.data == "feedback_start")
async def feedback_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(FeedbackSG.choosing_type)
    await callback.message.edit_text(
        "💬 Підтримка\n\nОберіть тип вашого звернення:",
        reply_markup=get_feedback_type_keyboard(),
    )


@router.callback_query(FeedbackSG.choosing_type, F.data.startswith("feedback_type_"))
async def feedback_type(callback: CallbackQuery, state: FSMContext) -> None:
    fb_type = callback.data.replace("feedback_type_", "")
    info = FEEDBACK_TYPES.get(fb_type, FEEDBACK_TYPES["other"])
    await callback.answer()
    await state.update_data(feedback_type=fb_type)
    await state.set_state(FeedbackSG.waiting_for_message)

    from bot.keyboards.inline import get_broadcast_cancel_keyboard

    await callback.message.edit_text(
        f"{info['emoji']} {info['label']}\n\n"
        "Надішліть ваше повідомлення (текст, фото або відео).\n\n"
        "⏱ У вас є 5 хвилин на введення.",
        reply_markup=get_broadcast_cancel_keyboard(),
    )


@router.message(FeedbackSG.waiting_for_message)
async def feedback_message(message: Message, state: FSMContext) -> None:
    content = None
    file_id = None
    msg_type = "text"

    if message.text:
        content = message.text
    elif message.photo:
        file_id = message.photo[-1].file_id
        content = message.caption
        msg_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        content = message.caption
        msg_type = "video"
    else:
        await message.reply("❌ Підтримуються тільки текст, фото та відео. Спробуйте ще раз.")
        return

    await state.update_data(content=content, file_id=file_id, msg_type=msg_type)
    await state.set_state(FeedbackSG.confirming)

    preview = content or "(медіа без тексту)"
    await message.answer(
        f"📋 Перегляд:\n\n{preview}\n\nНадіслати?",
        reply_markup=get_feedback_confirm_keyboard(),
    )


@router.callback_query(FeedbackSG.confirming, F.data == "feedback_confirm")
async def feedback_confirm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await callback.answer()
    data = await state.get_data()

    ticket = await create_ticket(
        session,
        callback.from_user.id,
        data.get("feedback_type", "other"),
        subject=data.get("feedback_type", "feedback"),
    )
    await add_ticket_message(
        session,
        ticket.id,
        sender_type="user",
        sender_id=callback.from_user.id,
        content=data.get("content"),
        file_id=data.get("file_id"),
        message_type=data.get("msg_type", "text"),
    )
    await state.clear()

    await callback.message.edit_text(
        f"✅ Дякуємо за звернення!\n\n"
        f"Ваше звернення #{ticket.id} прийнято.\n"
        "Ми розглянемо його найближчим часом."
    )

    for admin_id in settings.all_admin_ids:
        try:
            await callback.bot.send_message(
                admin_id,
                f"📩 Нове звернення #{ticket.id}\n"
                f"Від: {callback.from_user.id} (@{callback.from_user.username or '-'})\n"
                f"Тип: {data.get('feedback_type', 'other')}",
            )
        except Exception:
            pass


@router.callback_query(F.data == "feedback_cancel")
async def feedback_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("❌ Звернення скасовано.")
