"""Tests for bot/services/scheduler.py.

These tests cover the isolated, unit-testable parts of the scheduler service:
- Pure helper functions: _is_quiet_hours, _filter_events_for_date, _compute_changes,
  _merge_tomorrow_events_into_changes, _compute_date_hash, _event_anchor_passed
- stop_scheduler: sets _running = False
- _send_notifications_to_users: batch dispatch, RetryAfter retry, ForbiddenError handling
- _check_single_queue: hash unchanged, hash changed (quiet hours / active hours), no data
- flush_pending_notifications: pending notification path, daily-planned fallback
- _check_and_send_reminders: quiet-hours guard, reminder timing window, deduplication
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_method_mock() -> MagicMock:
    """Return a minimal aiogram method mock (needed for Telegram exception constructors)."""
    return MagicMock()


def _make_telegram_retry_after(retry_after: int = 1) -> TelegramRetryAfter:
    return TelegramRetryAfter(method=_make_method_mock(), message="Flood control", retry_after=retry_after)


def _make_telegram_forbidden() -> TelegramForbiddenError:
    return TelegramForbiddenError(method=_make_method_mock(), message="Forbidden: bot was blocked by the user")


def _make_mock_session() -> AsyncMock:
    """Return a minimal async SQLAlchemy session mock."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@asynccontextmanager
async def _mock_async_session(session: AsyncMock):
    """Async context manager that yields the given mock session."""
    yield session


def _patch_async_session(mock_session: AsyncMock):
    """Patch bot.services.scheduler.async_session to always yield mock_session."""
    return patch(
        "bot.services.scheduler.async_session",
        side_effect=lambda: _mock_async_session(mock_session),
    )


def _make_ns(**kwargs) -> SimpleNamespace:
    """Create a mock NotificationSettings namespace."""
    defaults = dict(
        notify_schedule_changes=True,
        notify_schedule_target=None,
        notify_remind_off=True,
        notify_remind_on=True,
        notify_remind_target=None,
        remind_15m=True,
        remind_30m=False,
        remind_1h=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_cc(**kwargs) -> SimpleNamespace:
    """Create a mock ChannelConfig namespace."""
    defaults = dict(
        channel_id=None,
        channel_status=None,
        channel_paused=False,
        ch_notify_schedule=False,
        ch_notify_remind_off=False,
        ch_notify_remind_on=False,
        ch_remind_15m=False,
        ch_remind_30m=False,
        ch_remind_1h=False,
        last_schedule_message_id=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_user(telegram_id: str = "111222333", region: str = "kyiv", queue: str = "1.1", **kwargs) -> SimpleNamespace:
    """Create a mock User namespace."""
    defaults = dict(
        telegram_id=telegram_id,
        username="testuser",
        region=region,
        queue=queue,
        is_active=True,
        notification_settings=_make_ns(),
        channel_config=_make_cc(),
        message_tracking=SimpleNamespace(
            last_schedule_message_id=None,
            last_reminder_message_id=None,
            last_channel_reminder_message_id=None,
        ),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_event(start: str, end: str, is_possible: bool = False) -> dict:
    return {"start": start, "end": end, "isPossible": is_possible}


def _make_sched(events: list[dict] | None = None, region: str = "kyiv", queue: str = "1.1") -> dict:
    return {"region": region, "queue": queue, "events": events or []}


# ─── _is_quiet_hours ──────────────────────────────────────────────────────


class TestIsQuietHours:
    def test_quiet_at_midnight(self):
        from bot.services.scheduler import _is_quiet_hours

        fake_now = datetime(2025, 1, 15, 0, 0, 0, tzinfo=KYIV_TZ)
        with patch("bot.services.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert _is_quiet_hours() is True

    def test_quiet_at_3am(self):
        from bot.services.scheduler import _is_quiet_hours

        fake_now = datetime(2025, 1, 15, 3, 30, 0, tzinfo=KYIV_TZ)
        with patch("bot.services.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert _is_quiet_hours() is True

    def test_quiet_at_0559(self):
        from bot.services.scheduler import _is_quiet_hours

        fake_now = datetime(2025, 1, 15, 5, 59, 59, tzinfo=KYIV_TZ)
        with patch("bot.services.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert _is_quiet_hours() is True

    def test_not_quiet_at_0600(self):
        from bot.services.scheduler import _is_quiet_hours

        fake_now = datetime(2025, 1, 15, 6, 0, 0, tzinfo=KYIV_TZ)
        with patch("bot.services.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert _is_quiet_hours() is False

    def test_not_quiet_at_noon(self):
        from bot.services.scheduler import _is_quiet_hours

        fake_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=KYIV_TZ)
        with patch("bot.services.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert _is_quiet_hours() is False

    def test_not_quiet_at_2359(self):
        """23:59 is not a quiet hour — quiet window is 00:00-05:59 only."""
        from bot.services.scheduler import _is_quiet_hours

        fake_now = datetime(2025, 1, 15, 23, 59, 59, tzinfo=KYIV_TZ)
        with patch("bot.services.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert _is_quiet_hours() is False


# ─── Pure helper functions ────────────────────────────────────────────────


class TestFilterEventsForDate:
    def test_returns_matching_events(self):
        from bot.services.scheduler import _filter_events_for_date

        events = [
            {"start": "2025-01-15T10:00:00", "end": "2025-01-15T12:00:00"},
            {"start": "2025-01-16T08:00:00", "end": "2025-01-16T10:00:00"},
        ]
        result = _filter_events_for_date(events, "2025-01-15")
        assert len(result) == 1
        assert result[0]["start"] == "2025-01-15T10:00:00"

    def test_returns_empty_for_no_match(self):
        from bot.services.scheduler import _filter_events_for_date

        events = [{"start": "2025-01-16T10:00:00", "end": "2025-01-16T12:00:00"}]
        result = _filter_events_for_date(events, "2025-01-15")
        assert result == []

    def test_returns_empty_for_empty_input(self):
        from bot.services.scheduler import _filter_events_for_date

        assert _filter_events_for_date([], "2025-01-15") == []

    def test_returns_multiple_matching_events(self):
        from bot.services.scheduler import _filter_events_for_date

        events = [
            {"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"},
            {"start": "2025-01-15T14:00:00", "end": "2025-01-15T16:00:00"},
            {"start": "2025-01-16T08:00:00", "end": "2025-01-16T10:00:00"},
        ]
        result = _filter_events_for_date(events, "2025-01-15")
        assert len(result) == 2


class TestComputeChanges:
    def test_added_events(self):
        from bot.services.scheduler import _compute_changes

        old = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        new = [
            {"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"},
            {"start": "2025-01-15T14:00:00", "end": "2025-01-15T16:00:00"},
        ]
        result = _compute_changes(old, new)
        assert len(result["added"]) == 1
        assert result["added"][0]["start"] == "2025-01-15T14:00:00"
        assert result["removed"] == []

    def test_removed_events(self):
        from bot.services.scheduler import _compute_changes

        old = [
            {"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"},
            {"start": "2025-01-15T14:00:00", "end": "2025-01-15T16:00:00"},
        ]
        new = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        result = _compute_changes(old, new)
        assert result["added"] == []
        assert len(result["removed"]) == 1
        assert result["removed"][0]["start"] == "2025-01-15T14:00:00"

    def test_no_changes(self):
        from bot.services.scheduler import _compute_changes

        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        result = _compute_changes(events, events)
        assert result == {"added": [], "removed": []}

    def test_both_empty(self):
        from bot.services.scheduler import _compute_changes

        result = _compute_changes([], [])
        assert result == {"added": [], "removed": []}

    def test_completely_replaced(self):
        from bot.services.scheduler import _compute_changes

        old = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        new = [{"start": "2025-01-15T12:00:00", "end": "2025-01-15T14:00:00"}]
        result = _compute_changes(old, new)
        assert len(result["added"]) == 1
        assert len(result["removed"]) == 1


class TestMergeTomorrowEventsIntoChanges:
    def test_adds_new_tomorrow_events(self):
        from bot.services.scheduler import _merge_tomorrow_events_into_changes

        changes = {"added": [], "removed": []}
        events = [
            {"start": "2025-01-16T08:00:00", "end": "2025-01-16T10:00:00"},
        ]
        _merge_tomorrow_events_into_changes(changes, events, "2025-01-16")
        assert len(changes["added"]) == 1

    def test_does_not_duplicate_already_added_events(self):
        from bot.services.scheduler import _merge_tomorrow_events_into_changes

        ev = {"start": "2025-01-16T08:00:00", "end": "2025-01-16T10:00:00"}
        changes = {"added": [ev], "removed": []}
        _merge_tomorrow_events_into_changes(changes, [ev], "2025-01-16")
        assert len(changes["added"]) == 1

    def test_skips_events_for_other_dates(self):
        from bot.services.scheduler import _merge_tomorrow_events_into_changes

        changes = {"added": [], "removed": []}
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        _merge_tomorrow_events_into_changes(changes, events, "2025-01-16")
        assert changes["added"] == []


class TestComputeDateHash:
    def test_returns_none_for_no_events_on_date(self):
        from bot.services.scheduler import _compute_date_hash

        events = [{"start": "2025-01-16T08:00:00", "end": "2025-01-16T10:00:00"}]
        result = _compute_date_hash(events, "2025-01-15")
        assert result is None

    def test_returns_hash_for_events_on_date(self):
        from bot.services.scheduler import _compute_date_hash

        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        result = _compute_date_hash(events, "2025-01-15")
        assert result is not None
        assert isinstance(result, str)

    def test_same_events_produce_same_hash(self):
        from bot.services.scheduler import _compute_date_hash

        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        h1 = _compute_date_hash(events, "2025-01-15")
        h2 = _compute_date_hash(events, "2025-01-15")
        assert h1 == h2

    def test_different_events_produce_different_hash(self):
        from bot.services.scheduler import _compute_date_hash

        events1 = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        events2 = [{"start": "2025-01-15T12:00:00", "end": "2025-01-15T14:00:00"}]
        h1 = _compute_date_hash(events1, "2025-01-15")
        h2 = _compute_date_hash(events2, "2025-01-15")
        assert h1 != h2


# ─── _event_anchor_passed ────────────────────────────────────────────────


class TestEventAnchorPassed:
    def test_past_event_returns_true(self):
        from bot.services.scheduler import _event_anchor_passed

        past_iso = "2025-01-15T08:00:00+02:00"
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=KYIV_TZ)
        assert _event_anchor_passed(past_iso, now) is True

    def test_future_event_returns_false(self):
        from bot.services.scheduler import _event_anchor_passed

        future_iso = "2025-01-15T12:00:00+02:00"
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=KYIV_TZ)
        assert _event_anchor_passed(future_iso, now) is False

    def test_invalid_iso_returns_true(self):
        """Malformed anchor strings are treated as expired — safe fallback."""
        from bot.services.scheduler import _event_anchor_passed

        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=KYIV_TZ)
        assert _event_anchor_passed("not-a-date", now) is True

    def test_naive_datetime_assumed_kyiv(self):
        """A naive ISO string is treated as Kyiv-local time."""
        from bot.services.scheduler import _event_anchor_passed

        # Naive string that is in the future relative to now
        future_naive = "2025-01-15T14:00:00"
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=KYIV_TZ)
        assert _event_anchor_passed(future_naive, now) is False


# ─── stop_scheduler ───────────────────────────────────────────────────────


class TestStopScheduler:
    def setup_method(self):
        import bot.services.scheduler as sched
        sched._running = True

    def teardown_method(self):
        import bot.services.scheduler as sched
        sched._running = False

    def test_sets_running_to_false(self):
        import bot.services.scheduler as sched
        from bot.services.scheduler import stop_scheduler

        assert sched._running is True
        stop_scheduler()
        assert sched._running is False

    def test_idempotent_when_already_stopped(self):
        import bot.services.scheduler as sched
        from bot.services.scheduler import stop_scheduler

        sched._running = False
        stop_scheduler()
        assert sched._running is False


# ─── _send_notifications_to_users ────────────────────────────────────────


class TestSendNotificationsToUsers:
    async def test_empty_user_list_is_noop(self):
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        with patch("bot.services.scheduler._send_schedule_notification") as mock_send:
            await _send_notifications_to_users(bot_mock, [], {}, {}, {})
            mock_send.assert_not_called()

    async def test_single_user_sends_one_notification(self):
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        user = _make_user()
        sched = _make_sched()

        with patch("bot.services.scheduler._send_schedule_notification", new_callable=AsyncMock) as mock_send:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _send_notifications_to_users(bot_mock, [user], sched, {}, {})
        mock_send.assert_called_once_with(bot_mock, user, sched, {}, {}, False)

    async def test_multiple_users_all_receive_notification(self):
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        users = [_make_user(telegram_id=f"user_{i}") for i in range(5)]
        sched = _make_sched()

        with patch("bot.services.scheduler._send_schedule_notification", new_callable=AsyncMock) as mock_send:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _send_notifications_to_users(bot_mock, users, sched, {}, {})
        assert mock_send.call_count == len(users)

    async def test_daily_planned_flag_is_passed_through(self):
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        user = _make_user()
        sched = _make_sched()

        with patch("bot.services.scheduler._send_schedule_notification", new_callable=AsyncMock) as mock_send:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _send_notifications_to_users(
                    bot_mock, [user], sched, {}, {}, is_daily_planned=True
                )
        mock_send.assert_called_once_with(bot_mock, user, sched, {}, {}, True)

    async def test_telegram_retry_after_retries_once(self):
        """When _send_schedule_notification raises TelegramRetryAfter, the worker retries."""
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        user = _make_user()
        sched = _make_sched()
        retry_exc = _make_telegram_retry_after(retry_after=1)

        call_count = 0

        async def _failing_then_ok(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise retry_exc

        with patch("bot.services.scheduler._send_schedule_notification", side_effect=_failing_then_ok):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _send_notifications_to_users(bot_mock, [user], sched, {}, {})

        # Called twice: initial attempt + retry
        assert call_count == 2

    async def test_telegram_forbidden_error_is_handled_gracefully(self):
        """TelegramForbiddenError (user blocked bot) must not crash the worker."""
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        users = [_make_user(telegram_id="blocked"), _make_user(telegram_id="ok")]
        sched = _make_sched()
        forbidden_exc = _make_telegram_forbidden()

        call_count = 0

        async def _blocked_then_ok(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if args[1].telegram_id == "blocked":
                raise forbidden_exc

        with patch("bot.services.scheduler._send_schedule_notification", side_effect=_blocked_then_ok):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _send_notifications_to_users(bot_mock, users, sched, {}, {})

        # Both users were attempted
        assert call_count == 2


# ─── _check_single_queue ─────────────────────────────────────────────────


class TestCheckSingleQueue:
    async def test_returns_false_when_no_schedule_data(self):
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        with patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value=None):
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")
        assert result is False

    async def test_returns_false_when_hash_unchanged(self):
        """When stored hash equals new hash, return False (no notification)."""
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)
        current_hash = "sha_abc123"

        mock_session.commit = AsyncMock()

        with patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.calculate_schedule_hash", return_value=current_hash), \
             patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value=current_hash), \
             patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=MagicMock()), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             _patch_async_session(mock_session):
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is False

    async def test_queues_notification_during_quiet_hours(self):
        """Hash changed during quiet hours → save pending notification, return True."""
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)

        with patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.calculate_schedule_hash", side_effect=["new_hash", "today_hash"]), \
             patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value="old_hash"), \
             patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler._is_quiet_hours", return_value=True), \
             patch("bot.services.scheduler.invalidate_image_cache", new_callable=AsyncMock), \
             patch("bot.services.scheduler._prerender_chart", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock) as mock_save_pending, \
             _patch_async_session(mock_session):
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        mock_save_pending.assert_called_once()

    async def test_sends_notifications_when_hash_changed_and_not_quiet(self):
        """Hash changed during active hours → send notifications immediately."""
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)
        users = [_make_user()]

        with patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.calculate_schedule_hash", side_effect=["new_hash", "today_hash"]), \
             patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value="old_hash"), \
             patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.invalidate_image_cache", new_callable=AsyncMock), \
             patch("bot.services.scheduler._prerender_chart", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler._send_notifications_to_users", new_callable=AsyncMock) as mock_notify, \
             patch("bot.services.scheduler.mark_pending_notifications_sent", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_power_notifications_on_schedule_change", new_callable=AsyncMock), \
             _patch_async_session(mock_session):
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        mock_notify.assert_called_once()

    async def test_uses_prefetched_data_when_provided(self):
        """When prefetched_data is provided, fetch_schedule_data should not be called."""
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)
        existing_hash = "sha_abc123"

        with patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock) as mock_fetch, \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.calculate_schedule_hash", return_value=existing_hash), \
             patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value=existing_hash), \
             patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=MagicMock()), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             _patch_async_session(mock_session):
            await _check_single_queue(bot_mock, "kyiv", "1.1", prefetched_data={"already": "fetched"})

        mock_fetch.assert_not_called()

    async def test_initial_load_treated_as_daily_planned(self):
        """When stored_hash is None (initial load), no-change update type is tagged as initial."""
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)
        users = [_make_user()]
        notified_args = {}

        async def _capture_notify(b, u, sched_d, update_t, changes, is_daily_planned=False):
            notified_args["is_daily_planned"] = is_daily_planned
            notified_args["update_type"] = update_t

        with patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.calculate_schedule_hash", side_effect=["new_hash", "today_hash"]), \
             patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.invalidate_image_cache", new_callable=AsyncMock), \
             patch("bot.services.scheduler._prerender_chart", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler.mark_pending_notifications_sent", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_power_notifications_on_schedule_change", new_callable=AsyncMock), \
             patch("bot.services.scheduler._send_notifications_to_users", side_effect=_capture_notify), \
             _patch_async_session(mock_session):
            await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert notified_args.get("is_daily_planned") is True
        assert notified_args.get("update_type", {}).get("initial") is True


# ─── flush_pending_notifications ─────────────────────────────────────────


class TestFlushPendingNotifications:
    async def test_sends_pending_notifications_and_marks_sent(self):
        """Pending notifications are fetched, sent, and marked as sent."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        region, queue = "kyiv", "1.1"
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)
        users = [_make_user()]
        notif = SimpleNamespace(
            schedule_data=json.dumps(sched),
            update_type=json.dumps({"todayUpdated": True}),
            changes=json.dumps({"added": [], "removed": []}),
        )

        with patch("bot.services.scheduler.get_all_pending_region_queue_pairs", new_callable=AsyncMock, return_value=[(region, queue)]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[(region, queue)]), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler.get_latest_pending_notification", new_callable=AsyncMock, return_value=notif), \
             patch("bot.services.scheduler.mark_pending_notifications_sent", new_callable=AsyncMock) as mock_mark, \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler.calculate_schedule_hash", return_value="sent_hash"), \
             patch("bot.services.scheduler._send_notifications_to_users", new_callable=AsyncMock) as mock_send, \
             patch("bot.services.scheduler.delete_old_pending_notifications", new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders", new_callable=AsyncMock, return_value=0), \
             _patch_async_session(mock_session):
            await flush_pending_notifications(bot_mock)

        mock_send.assert_called_once()
        mock_mark.assert_called_once()

    async def test_sends_daily_planned_when_no_pending_notification(self):
        """When no pending notification row exists, send a fresh daily-planned message."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        region, queue = "kyiv", "1.1"
        events = [{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}]
        sched = _make_sched(events=events)
        users = [_make_user()]

        notified_args = {}

        async def _capture_notify(b, u, sched_d, update_t, changes, is_daily_planned=False):
            notified_args["is_daily_planned"] = is_daily_planned

        with patch("bot.services.scheduler.get_all_pending_region_queue_pairs", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[(region, queue)]), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.calculate_schedule_hash", return_value="fresh_hash"), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler._send_notifications_to_users", side_effect=_capture_notify), \
             patch("bot.services.scheduler.delete_old_pending_notifications", new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders", new_callable=AsyncMock, return_value=0), \
             _patch_async_session(mock_session):
            await flush_pending_notifications(bot_mock)

        assert notified_args.get("is_daily_planned") is True

    async def test_skips_pair_when_fetch_returns_no_data(self):
        """When fetch_schedule_data returns falsy, the pair is skipped gracefully."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        region, queue = "kyiv", "1.1"
        users = [_make_user()]

        with patch("bot.services.scheduler.get_all_pending_region_queue_pairs", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[(region, queue)]), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler._send_notifications_to_users", new_callable=AsyncMock) as mock_send, \
             patch("bot.services.scheduler.delete_old_pending_notifications", new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders", new_callable=AsyncMock, return_value=0), \
             _patch_async_session(mock_session):
            await flush_pending_notifications(bot_mock)

        mock_send.assert_not_called()

    async def test_is_daily_planned_when_pending_has_daily_planned_flag(self):
        """Pending notification with dailyPlanned flag should result in is_daily_planned=True."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        region, queue = "kyiv", "1.1"
        sched = _make_sched()
        users = [_make_user()]
        notif = SimpleNamespace(
            schedule_data=json.dumps(sched),
            update_type=json.dumps({"dailyPlanned": True}),
            changes=None,
        )
        notified_args = {}

        async def _capture_notify(b, u, sched_d, update_t, changes, is_daily_planned=False):
            notified_args["is_daily_planned"] = is_daily_planned

        with patch("bot.services.scheduler.get_all_pending_region_queue_pairs", new_callable=AsyncMock, return_value=[(region, queue)]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[(region, queue)]), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler.get_latest_pending_notification", new_callable=AsyncMock, return_value=notif), \
             patch("bot.services.scheduler.mark_pending_notifications_sent", new_callable=AsyncMock), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler.calculate_schedule_hash", return_value="hash"), \
             patch("bot.services.scheduler._send_notifications_to_users", side_effect=_capture_notify), \
             patch("bot.services.scheduler.delete_old_pending_notifications", new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders", new_callable=AsyncMock, return_value=0), \
             _patch_async_session(mock_session):
            await flush_pending_notifications(bot_mock)

        assert notified_args.get("is_daily_planned") is True


# ─── _check_and_send_reminders ────────────────────────────────────────────


class TestCheckAndSendReminders:
    async def test_returns_early_during_quiet_hours(self):
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        with patch("bot.services.scheduler._is_quiet_hours", return_value=True), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock) as mock_pairs:
            await _check_and_send_reminders(bot_mock)

        mock_pairs.assert_not_called()

    async def test_processes_pairs_when_not_quiet(self):
        """With no events in the next reminder window, _send_reminder is not called."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_sends_reminder_for_event_in_window(self):
        """Event exactly 15 minutes away triggers a 15-minute reminder for subscribed users."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        now = datetime.now(KYIV_TZ)
        start_iso = (now + timedelta(minutes=15)).isoformat()
        end_iso   = (now + timedelta(minutes=75)).isoformat()
        events = [{"start": start_iso, "end": end_iso, "isPossible": False}]
        sched = _make_sched(events=events)

        next_event = {
            "type": "power_off",
            "time": start_iso,
            "endTime": end_iso,
            "minutes": 15,
            "isPossible": False,
        }

        user = _make_user(notification_settings=_make_ns(remind_15m=True, notify_remind_off=True))

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.find_next_event", return_value=next_event), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler.check_reminders_sent_batch", new_callable=AsyncMock, return_value=set()), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock, return_value=True) as mock_send, \
             patch("bot.services.scheduler.mark_reminder_sent", new_callable=AsyncMock), \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_called_once()

    async def test_skips_already_sent_reminder(self):
        """Reminders already in the SentReminder table are not sent again."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        now = datetime.now(KYIV_TZ)
        start_iso = (now + timedelta(minutes=15)).isoformat()
        end_iso   = (now + timedelta(minutes=75)).isoformat()
        events = [{"start": start_iso, "end": end_iso}]
        sched = _make_sched(events=events)
        next_event = {
            "type": "power_off",
            "time": start_iso,
            "endTime": end_iso,
            "minutes": 15,
            "isPossible": False,
        }
        user = _make_user(notification_settings=_make_ns(remind_15m=True, notify_remind_off=True))

        # The reminder was already sent → batch check returns it in already_sent set
        already_sent = {("111222333", "15m")}

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.find_next_event", return_value=next_event), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler.check_reminders_sent_batch", new_callable=AsyncMock, return_value=already_sent), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock, return_value=True) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_skips_reminder_when_event_outside_window(self):
        """Events > remind_m + 1 minutes away are not in the timing window."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        now = datetime.now(KYIV_TZ)
        start_iso = (now + timedelta(minutes=45)).isoformat()
        end_iso   = (now + timedelta(minutes=105)).isoformat()
        events = [{"start": start_iso, "end": end_iso}]
        sched = _make_sched(events=events)
        next_event = {
            "type": "power_off",
            "time": start_iso,
            "endTime": end_iso,
            "minutes": 45,
            "isPossible": False,
        }
        user = _make_user(notification_settings=_make_ns(remind_15m=True, notify_remind_off=True))

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "data"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.find_next_event", return_value=next_event), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_no_pairs_means_no_reminders_sent(self):
        """When there are no active region/queue pairs, no reminders are sent."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()
