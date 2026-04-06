from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import AdminTicketReminder, SentReminder
from bot.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "check_reminder_sent",
    "check_reminders_sent_batch",
    "mark_reminder_sent",
    "cleanup_old_reminders",
    "get_active_reminder_anchors",
    "create_admin_ticket_reminder",
    "get_pending_admin_reminders",
    "resolve_admin_ticket_reminder",
]


async def check_reminder_sent(
    session: AsyncSession,
    telegram_id: str,
    period_key: str,
    reminder_type: str,
) -> bool:
    """Return True if this reminder was already sent for the given event anchor."""
    result = await session.execute(
        select(SentReminder.id).where(
            SentReminder.telegram_id == telegram_id,
            SentReminder.period_key == period_key,
            SentReminder.reminder_type == reminder_type,
        ).limit(1)
    )
    return result.scalar() is not None


async def check_reminders_sent_batch(
    session: AsyncSession,
    checks: list[tuple[str, str, str]],
) -> set[tuple[str, str]]:
    """Return the set of (telegram_id, reminder_type) pairs already recorded in
    sent_reminders for the given (telegram_id, period_key, reminder_type) tuples.

    Replaces N individual ``check_reminder_sent`` calls with a single row-value IN
    query, eliminating the N+1 pattern in the reminder checker loop.
    """
    if not checks:
        return set()
    result = await session.execute(
        select(SentReminder.telegram_id, SentReminder.reminder_type).where(
            tuple_(
                SentReminder.telegram_id,
                SentReminder.period_key,
                SentReminder.reminder_type,
            ).in_(checks)
        )
    )
    return {(row.telegram_id, row.reminder_type) for row in result}


async def mark_reminder_sent(
    session: AsyncSession,
    telegram_id: str,
    region: str,
    queue: str,
    period_key: str,
    reminder_type: str,
) -> None:
    """Record that a reminder was sent.  Uses INSERT … ON CONFLICT DO NOTHING for idempotency."""
    stmt = pg_insert(SentReminder).values(
        telegram_id=telegram_id,
        region=region,
        queue=queue,
        period_key=period_key,
        reminder_type=reminder_type,
    ).on_conflict_do_nothing(constraint="uq_sent_reminder")
    await session.execute(stmt)


async def cleanup_old_reminders(session: AsyncSession, older_than_hours: int = 48) -> int:
    """Delete sent-reminder rows older than *older_than_hours*.

    Returns the number of deleted rows.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=older_than_hours)
    result = await session.execute(
        delete(SentReminder).where(SentReminder.created_at < cutoff)
    )
    return result.rowcount  # type: ignore[attr-defined]


async def get_active_reminder_anchors(
    session: AsyncSession,
    within_hours: int = 48,
) -> list[tuple[str, str]]:
    """Return the latest ``(telegram_id, period_key)`` per user for recent reminders.

    Uses ``DISTINCT ON`` (PostgreSQL-specific) so deduplication happens at the
    database level rather than in Python.  Used to reconstruct pending-cleanup
    state after a bot restart: callers should check whether each ``period_key``
    represents a past event and, if so, delete the reminder message from Telegram.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=within_hours)
    result = await session.execute(
        select(SentReminder.telegram_id, SentReminder.period_key)
        .where(SentReminder.created_at > cutoff)
        .distinct(SentReminder.telegram_id)
        .order_by(SentReminder.telegram_id, SentReminder.created_at.desc())
    )
    return [(row.telegram_id, row.period_key) for row in result]


async def create_admin_ticket_reminder(
    session: AsyncSession, ticket_id: int, admin_telegram_id: str
) -> AdminTicketReminder:
    """Create an admin reminder for a support ticket."""
    reminder = AdminTicketReminder(
        ticket_id=ticket_id,
        admin_telegram_id=admin_telegram_id,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def get_pending_admin_reminders(
    session: AsyncSession,
) -> list[AdminTicketReminder]:
    """Return unresolved reminders where last_reminder_at is older than 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await session.execute(
        select(AdminTicketReminder).where(
            AdminTicketReminder.is_resolved.is_(False),
            AdminTicketReminder.last_reminder_at <= cutoff,
        )
    )
    return list(result.scalars().all())


async def resolve_admin_ticket_reminder(
    session: AsyncSession, ticket_id: int
) -> None:
    """Mark all reminders for a ticket as resolved."""
    await session.execute(
        update(AdminTicketReminder)
        .where(AdminTicketReminder.ticket_id == ticket_id)
        .values(is_resolved=True)
    )
