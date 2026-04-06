from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Ticket, TicketMessage
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "create_ticket",
    "add_ticket_message",
    "get_open_tickets",
    "get_all_tickets",
    "get_ticket_by_id",
    "close_ticket",
    "reopen_ticket",
    "count_open_tickets",
]


async def create_ticket(
    session: AsyncSession,
    telegram_id: int | str,
    ticket_type: str,
    subject: str | None = None,
) -> Ticket:
    ticket = Ticket(telegram_id=str(telegram_id), type=ticket_type, subject=subject)
    session.add(ticket)
    await session.flush()
    return ticket


async def add_ticket_message(
    session: AsyncSession,
    ticket_id: int,
    sender_type: str,
    sender_id: int | str,
    content: str | None = None,
    file_id: str | None = None,
    message_type: str = "text",
) -> TicketMessage:
    msg = TicketMessage(
        ticket_id=ticket_id,
        sender_type=sender_type,
        sender_id=str(sender_id),
        message_type=message_type,
        content=content,
        file_id=file_id,
    )
    session.add(msg)
    await session.flush()
    return msg


async def get_open_tickets(session: AsyncSession) -> list[Ticket]:
    result = await session.execute(
        select(Ticket).where(Ticket.status == "open").order_by(Ticket.created_at.desc())
    )
    return list(result.scalars().all())


async def get_all_tickets(session: AsyncSession) -> list[Ticket]:
    result = await session.execute(select(Ticket).order_by(Ticket.created_at.desc()))
    return list(result.scalars().all())


async def get_ticket_by_id(session: AsyncSession, ticket_id: int) -> Ticket | None:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    return result.scalars().first()


async def close_ticket(session: AsyncSession, ticket_id: int, closed_by: str) -> None:
    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(status="closed", closed_at=datetime.now(timezone.utc).replace(tzinfo=None), closed_by=closed_by)
    )


async def reopen_ticket(session: AsyncSession, ticket_id: int) -> None:
    await session.execute(
        update(Ticket).where(Ticket.id == ticket_id).values(status="open", closed_at=None, closed_by=None)
    )


async def count_open_tickets(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(Ticket.id)).where(Ticket.status == "open"))
    return result.scalar() or 0
