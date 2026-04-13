"""Tests for bot/db/queries/schedule.py — uses mocked AsyncSession."""
from __future__ import annotations

from datetime import datetime, timezone
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
    result.scalar_one_or_none.return_value = value
    result.scalar.return_value = value
    return result


def _scalars_first(value):
    scalars = MagicMock()
    scalars.first.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalars_one(value):
    scalars = MagicMock()
    scalars.one.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# get_schedule_check_time
# ---------------------------------------------------------------------------


class TestGetScheduleCheckTime:
    async def test_returns_timestamp_when_record_exists_with_tz(self):
        """check exists + last_checked_at has tzinfo → return its timestamp."""
        from bot.db.queries.schedule import get_schedule_check_time

        session = _make_session()
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        check = SimpleNamespace(last_checked_at=dt)
        session.execute.return_value = _scalars_first(check)

        result = await get_schedule_check_time(session, "kyiv", "1.1")

        assert result == int(dt.timestamp())

    async def test_naive_datetime_gets_utc_tzinfo(self):
        """check.last_checked_at without tzinfo → replace(tzinfo=utc) before .timestamp()."""
        from bot.db.queries.schedule import get_schedule_check_time

        session = _make_session()
        naive_dt = datetime(2024, 6, 1, 12, 0, 0)  # no tzinfo
        check = SimpleNamespace(last_checked_at=naive_dt)
        session.execute.return_value = _scalars_first(check)

        result = await get_schedule_check_time(session, "kyiv", "1.1")

        expected = int(naive_dt.replace(tzinfo=timezone.utc).timestamp())
        assert result == expected

    async def test_returns_current_time_when_no_record(self):
        """No record found → falls back to int(time.time())."""
        import time
        from bot.db.queries.schedule import get_schedule_check_time

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        before = int(time.time())
        result = await get_schedule_check_time(session, "kyiv", "1.1")
        after = int(time.time())

        assert before <= result <= after + 1

    async def test_returns_current_time_when_last_checked_at_is_none(self):
        """Record found but last_checked_at is None → fallback to time.time()."""
        import time
        from bot.db.queries.schedule import get_schedule_check_time

        session = _make_session()
        check = SimpleNamespace(last_checked_at=None)
        session.execute.return_value = _scalars_first(check)

        before = int(time.time())
        result = await get_schedule_check_time(session, "kyiv", "1.1")
        after = int(time.time())

        assert before <= result <= after + 1


# ---------------------------------------------------------------------------
# update_schedule_check_time
# ---------------------------------------------------------------------------


class TestUpdateScheduleCheckTime:
    async def test_upserts_without_hash(self):
        """last_hash=None → only last_checked_at in set_cols."""
        from bot.db.queries.schedule import update_schedule_check_time

        session = _make_session()
        await update_schedule_check_time(session, "kyiv", "1.1")

        session.execute.assert_called_once()
        session.flush.assert_called_once()

    async def test_upserts_with_hash(self):
        """last_hash provided → last_hash included in values and set_cols."""
        from bot.db.queries.schedule import update_schedule_check_time

        session = _make_session()
        await update_schedule_check_time(session, "kyiv", "1.1", last_hash="abc123")

        session.execute.assert_called_once()
        session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# get_schedule_hash
# ---------------------------------------------------------------------------


class TestGetScheduleHash:
    async def test_returns_hash_when_found(self):
        from bot.db.queries.schedule import get_schedule_hash

        session = _make_session()
        session.execute.return_value = _scalar_result("deadbeef")

        result = await get_schedule_hash(session, "kyiv", "1.1")

        assert result == "deadbeef"

    async def test_returns_none_when_not_found(self):
        from bot.db.queries.schedule import get_schedule_hash

        session = _make_session()
        session.execute.return_value = _scalar_result(None)

        result = await get_schedule_hash(session, "kyiv", "1.1")

        assert result is None


# ---------------------------------------------------------------------------
# get_daily_snapshot
# ---------------------------------------------------------------------------


class TestGetDailySnapshot:
    async def test_returns_snapshot_when_found(self):
        from bot.db.queries.schedule import get_daily_snapshot

        session = _make_session()
        snap = SimpleNamespace(region="kyiv", queue="1.1", date="2024-06-01")
        session.execute.return_value = _scalars_first(snap)

        result = await get_daily_snapshot(session, "kyiv", "1.1", "2024-06-01")

        assert result is snap

    async def test_returns_none_when_not_found(self):
        from bot.db.queries.schedule import get_daily_snapshot

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_daily_snapshot(session, "kyiv", "1.1", "2024-06-01")

        assert result is None


# ---------------------------------------------------------------------------
# upsert_daily_snapshot
# ---------------------------------------------------------------------------


class TestUpsertDailySnapshot:
    async def test_returns_snapshot_object(self):
        """INSERT … ON CONFLICT → returns ScheduleDailySnapshot from .scalars().one()."""
        from bot.db.queries.schedule import upsert_daily_snapshot

        session = _make_session()
        snap = SimpleNamespace(id=1, region="kyiv", queue="1.1", date="2024-06-01")
        session.execute.return_value = _scalars_one(snap)

        result = await upsert_daily_snapshot(
            session, "kyiv", "1.1", "2024-06-01", '{"data": true}', "h1", "h2"
        )

        assert result is snap
        session.execute.assert_called_once()
        session.flush.assert_called_once()

    async def test_accepts_none_hashes(self):
        """today_hash=None, tomorrow_hash=None → executed without error."""
        from bot.db.queries.schedule import upsert_daily_snapshot

        session = _make_session()
        snap = SimpleNamespace(id=2)
        session.execute.return_value = _scalars_one(snap)

        result = await upsert_daily_snapshot(
            session, "kyiv", "1.1", "2024-06-01", "{}", None, None
        )

        assert result is snap


# ---------------------------------------------------------------------------
# save_pending_notification
# ---------------------------------------------------------------------------


class TestSavePendingNotification:
    async def test_adds_notification_and_returns_it(self):
        from bot.db.queries.schedule import save_pending_notification

        session = _make_session()

        result = await save_pending_notification(
            session, "kyiv", "1.1", '{"data": true}', "update", "some changes"
        )

        session.add.assert_called_once_with(result)
        session.flush.assert_called_once()
        assert result.region == "kyiv"
        assert result.queue == "1.1"
        assert result.status == "pending"

    async def test_none_update_type_and_changes(self):
        """update_type=None, changes=None → still creates and adds notification."""
        from bot.db.queries.schedule import save_pending_notification

        session = _make_session()

        result = await save_pending_notification(session, "kyiv", "1.1", "{}", None, None)

        assert result.update_type is None
        assert result.changes is None
        assert result.status == "pending"


# ---------------------------------------------------------------------------
# get_latest_pending_notification
# ---------------------------------------------------------------------------


class TestGetLatestPendingNotification:
    async def test_returns_notification_when_found(self):
        from bot.db.queries.schedule import get_latest_pending_notification

        session = _make_session()
        notif = SimpleNamespace(id=42, region="kyiv", queue="1.1", status="pending")
        session.execute.return_value = _scalars_first(notif)

        result = await get_latest_pending_notification(session, "kyiv", "1.1")

        assert result is notif

    async def test_returns_none_when_not_found(self):
        from bot.db.queries.schedule import get_latest_pending_notification

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_latest_pending_notification(session, "kyiv", "1.1")

        assert result is None


# ---------------------------------------------------------------------------
# get_all_pending_region_queue_pairs
# ---------------------------------------------------------------------------


class TestGetAllPendingRegionQueuePairs:
    async def test_returns_list_of_tuples(self):
        from bot.db.queries.schedule import get_all_pending_region_queue_pairs

        session = _make_session()
        pairs = [("kyiv", "1.1"), ("lviv", "2.2")]
        result_mock = MagicMock()
        result_mock.all.return_value = pairs
        session.execute.return_value = result_mock

        result = await get_all_pending_region_queue_pairs(session)

        assert result == [("kyiv", "1.1"), ("lviv", "2.2")]

    async def test_returns_empty_list_when_no_pending(self):
        from bot.db.queries.schedule import get_all_pending_region_queue_pairs

        session = _make_session()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute.return_value = result_mock

        result = await get_all_pending_region_queue_pairs(session)

        assert result == []


# ---------------------------------------------------------------------------
# mark_pending_notifications_sent
# ---------------------------------------------------------------------------


class TestMarkPendingNotificationsSent:
    async def test_executes_update_statement(self):
        from bot.db.queries.schedule import mark_pending_notifications_sent

        session = _make_session()

        await mark_pending_notifications_sent(session, "kyiv", "1.1")

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# delete_old_pending_notifications
# ---------------------------------------------------------------------------


class TestDeleteOldPendingNotifications:
    async def test_returns_rowcount(self):
        from bot.db.queries.schedule import delete_old_pending_notifications

        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 5
        session.execute.return_value = result_mock

        count = await delete_old_pending_notifications(session)

        assert count == 5

    async def test_returns_zero_when_nothing_deleted(self):
        from bot.db.queries.schedule import delete_old_pending_notifications

        session = _make_session()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute.return_value = result_mock

        count = await delete_old_pending_notifications(session, older_than_hours=72)

        assert count == 0
