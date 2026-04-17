"""Tests for bot/db/queries/reminders.py — uses mocked AsyncSession."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# check_reminder_sent
# ---------------------------------------------------------------------------


class TestCheckReminderSent:
    async def test_returns_true_when_row_found(self):
        """scalar() returns non-None → True."""
        from bot.db.queries.reminders import check_reminder_sent

        session = _make_session()
        session.execute.return_value = _scalar_result(1)  # row ID found

        result = await check_reminder_sent(session, "111", "2024-06-01T08:00:00", "1h")

        assert result is True

    async def test_returns_false_when_no_row(self):
        """scalar() returns None → False."""
        from bot.db.queries.reminders import check_reminder_sent

        session = _make_session()
        session.execute.return_value = _scalar_result(None)

        result = await check_reminder_sent(session, "111", "2024-06-01T08:00:00", "1h")

        assert result is False


# ---------------------------------------------------------------------------
# check_reminders_sent_batch
# ---------------------------------------------------------------------------


class TestCheckRemindersSentBatch:
    async def test_returns_empty_set_for_empty_checks(self):
        """Early-return when checks list is empty."""
        from bot.db.queries.reminders import check_reminders_sent_batch

        session = _make_session()

        result = await check_reminders_sent_batch(session, [])

        assert result == set()
        session.execute.assert_not_called()

    async def test_returns_set_of_tuples_for_matching_rows(self):
        """Rows found → set of (telegram_id, reminder_type) tuples."""
        from bot.db.queries.reminders import check_reminders_sent_batch

        session = _make_session()
        row1 = SimpleNamespace(telegram_id="111", reminder_type="1h")
        row2 = SimpleNamespace(telegram_id="222", reminder_type="30m")
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([row1, row2]))
        session.execute.return_value = result_mock

        checks = [
            ("111", "2024-06-01T08:00:00", "1h"),
            ("222", "2024-06-01T08:00:00", "30m"),
        ]
        result = await check_reminders_sent_batch(session, checks)

        assert result == {("111", "1h"), ("222", "30m")}
        session.execute.assert_called_once()

    async def test_returns_empty_set_when_no_rows_match(self):
        """No matching rows → empty set."""
        from bot.db.queries.reminders import check_reminders_sent_batch

        session = _make_session()
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([]))
        session.execute.return_value = result_mock

        result = await check_reminders_sent_batch(
            session, [("999", "2024-06-01T08:00:00", "15m")]
        )

        assert result == set()


# ---------------------------------------------------------------------------
# mark_reminder_sent
# ---------------------------------------------------------------------------


class TestMarkReminderSent:
    async def test_executes_insert_on_conflict_do_nothing(self):
        from bot.db.queries.reminders import mark_reminder_sent

        session = _make_session()

        await mark_reminder_sent(session, "111", "kyiv", "1.1", "2024-06-01T08:00:00", "1h")

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# cleanup_old_reminders
# ---------------------------------------------------------------------------


class TestCleanupOldReminders:
    async def test_returns_deleted_count(self):
        from bot.db.queries.reminders import cleanup_old_reminders

        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 7
        session.execute.return_value = result_mock

        count = await cleanup_old_reminders(session)

        assert count == 7
        session.execute.assert_called_once()

    async def test_custom_hours(self):
        """Custom older_than_hours is accepted without error."""
        from bot.db.queries.reminders import cleanup_old_reminders

        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute.return_value = result_mock

        count = await cleanup_old_reminders(session, older_than_hours=24)

        assert count == 0


# ---------------------------------------------------------------------------
# get_active_reminder_anchors
# ---------------------------------------------------------------------------


class TestGetActiveReminderAnchors:
    async def test_returns_list_of_tuples(self):
        from bot.db.queries.reminders import get_active_reminder_anchors

        session = _make_session()
        row1 = SimpleNamespace(telegram_id="111", period_key="2024-06-01T08:00:00")
        row2 = SimpleNamespace(telegram_id="222", period_key="2024-06-01T09:00:00")
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([row1, row2]))
        session.execute.return_value = result_mock

        result = await get_active_reminder_anchors(session)

        assert result == [
            ("111", "2024-06-01T08:00:00"),
            ("222", "2024-06-01T09:00:00"),
        ]

    async def test_returns_empty_list_when_no_anchors(self):
        from bot.db.queries.reminders import get_active_reminder_anchors

        session = _make_session()
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([]))
        session.execute.return_value = result_mock

        result = await get_active_reminder_anchors(session, within_hours=24)

        assert result == []


# ---------------------------------------------------------------------------
# create_admin_ticket_reminder
# ---------------------------------------------------------------------------


class TestCreateAdminTicketReminder:
    async def test_creates_and_returns_reminder(self):
        from bot.db.queries.reminders import create_admin_ticket_reminder

        session = _make_session()

        result = await create_admin_ticket_reminder(session, ticket_id=42, admin_telegram_id="999")

        session.add.assert_called_once_with(result)
        session.flush.assert_called_once()
        assert result.ticket_id == 42
        assert result.admin_telegram_id == "999"


# ---------------------------------------------------------------------------
# get_pending_admin_reminders
# ---------------------------------------------------------------------------


class TestGetPendingAdminReminders:
    async def test_returns_list_of_reminders(self):
        from bot.db.queries.reminders import get_pending_admin_reminders

        session = _make_session()
        reminder = SimpleNamespace(id=1, ticket_id=10, is_resolved=False)
        session.execute.return_value = _scalars_result([reminder])

        result = await get_pending_admin_reminders(session)

        assert result == [reminder]

    async def test_returns_empty_list_when_none_pending(self):
        from bot.db.queries.reminders import get_pending_admin_reminders

        session = _make_session()
        session.execute.return_value = _scalars_result([])

        result = await get_pending_admin_reminders(session)

        assert result == []


# ---------------------------------------------------------------------------
# resolve_admin_ticket_reminder
# ---------------------------------------------------------------------------


class TestResolveAdminTicketReminder:
    async def test_executes_update(self):
        from bot.db.queries.reminders import resolve_admin_ticket_reminder

        session = _make_session()

        await resolve_admin_ticket_reminder(session, ticket_id=42)

        session.execute.assert_called_once()
