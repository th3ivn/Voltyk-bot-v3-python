from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.queries import (
    add_ticket_message,
    close_ticket,
    get_all_tickets,
    get_ticket_by_id,
    reopen_ticket,
    resolve_admin_ticket_reminder,
)
from bot.keyboards.inline import get_admin_ticket_keyboard, get_admin_tickets_list_keyboard
from bot.states.fsm import AdminTicketReplySG

router = Router(name="admin_tickets")


@router.callback_query(F.data == "admin_tickets")
async def admin_tickets(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    await callback.answer()
    tickets = await get_all_tickets(session)
    if not tickets:
        await callback.message.edit_text("📩 Немає звернень")
        return
    await callback.message.edit_text(
        "📩 Звернення",
        reply_markup=get_admin_tickets_list_keyboard(tickets, page=1),
    )


@router.callback_query(F.data.startswith("admin_tickets_page_"))
async def admin_tickets_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    page = int(callback.data.replace("admin_tickets_page_", ""))
    await callback.answer()
    tickets = await get_all_tickets(session)
    await callback.message.edit_text(
        "📩 Звернення",
        reply_markup=get_admin_tickets_list_keyboard(tickets, page=page),
    )


@router.callback_query(F.data.startswith("admin_ticket_view_"))
async def admin_ticket_view(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    ticket_id = int(callback.data.replace("admin_ticket_view_", ""))
    await callback.answer()
    ticket = await get_ticket_by_id(session, ticket_id)
    if not ticket:
        await callback.message.edit_text("❌ Звернення не знайдено")
        return

    lines = [
        f"📩 Звернення #{ticket.id}",
        f"Від: {ticket.telegram_id}",
        f"Тип: {ticket.type}",
        f"Статус: {ticket.status}",
        f"Створено: {ticket.created_at.strftime('%d.%m.%Y %H:%M') if ticket.created_at else '-'}",
        "",
    ]
    for msg in ticket.messages:
        sender = "👤 Користувач" if msg.sender_type == "user" else "🔧 Адмін"
        lines.append(f"{sender}: {msg.content or '(медіа)'}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=get_admin_ticket_keyboard(ticket.id, ticket.status),
    )


@router.callback_query(F.data.startswith("admin_ticket_reply_"))
async def admin_ticket_reply(callback: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    ticket_id = int(callback.data.replace("admin_ticket_reply_", ""))
    await callback.answer()
    await state.set_state(AdminTicketReplySG.waiting_for_reply)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.edit_text(f"💬 Введіть відповідь на звернення #{ticket_id}:")


@router.message(AdminTicketReplySG.waiting_for_reply)
async def admin_ticket_reply_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.text:
        return
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    if not ticket_id:
        await state.clear()
        return

    ticket = await get_ticket_by_id(session, ticket_id)
    if not ticket:
        await state.clear()
        await message.answer("❌ Звернення не знайдено")
        return

    await add_ticket_message(
        session, ticket_id, "admin", message.from_user.id, content=message.text.strip()
    )
    await resolve_admin_ticket_reminder(session, ticket_id)
    await state.clear()

    try:
        await message.bot.send_message(
            int(ticket.telegram_id),
            f"💬 Відповідь на звернення #{ticket_id}:\n\n{message.text.strip()}",
        )
    except Exception:
        pass

    await message.answer(f"✅ Відповідь надіслано на звернення #{ticket_id}")


@router.callback_query(F.data.startswith("admin_ticket_close_"))
async def admin_ticket_close(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    ticket_id = int(callback.data.replace("admin_ticket_close_", ""))
    await close_ticket(session, ticket_id, str(callback.from_user.id))
    await callback.answer("✅ Звернення закрито")

    ticket = await get_ticket_by_id(session, ticket_id)
    if ticket:
        try:
            await callback.bot.send_message(
                int(ticket.telegram_id),
                f"✅ Ваше звернення #{ticket_id} закрито.",
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("admin_ticket_reopen_"))
async def admin_ticket_reopen(callback: CallbackQuery, session: AsyncSession) -> None:
    if not settings.is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ заборонено")
        return
    ticket_id = int(callback.data.replace("admin_ticket_reopen_", ""))
    await reopen_ticket(session, ticket_id)
    await callback.answer("🔄 Звернення відкрито знову")
