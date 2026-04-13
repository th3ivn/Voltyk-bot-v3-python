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
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

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

        async def _blocked_then_ok(bot, user, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if user.telegram_id == "blocked":
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

        async def _capture_notify(bot, user, schedule_data, update_type, changes, is_daily_planned=False):
            notified_args["is_daily_planned"] = is_daily_planned
            notified_args["update_type"] = update_type

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

        async def _capture_notify(bot, user, schedule_data, update_type, changes, is_daily_planned=False):
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

        async def _capture_notify(bot, user, schedule_data, update_type, changes, is_daily_planned=False):
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


# ─── _deactivate_blocked_user ────────────────────────────────────────────


class TestDeactivateBlockedUser:
    async def test_deactivates_user_and_commits(self):
        """Verify that deactivate_user is called with the telegram_id and session is committed."""
        from bot.services.scheduler import _deactivate_blocked_user

        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.deactivate_user", new_callable=AsyncMock) as mock_deactivate:
            await _deactivate_blocked_user(12345)

        mock_deactivate.assert_called_once_with(mock_session, "12345")
        mock_session.commit.assert_called_once()

    async def test_accepts_string_telegram_id(self):
        """Verify that string telegram_id is passed through correctly."""
        from bot.services.scheduler import _deactivate_blocked_user

        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.deactivate_user", new_callable=AsyncMock) as mock_deactivate:
            await _deactivate_blocked_user("67890")

        mock_deactivate.assert_called_once_with(mock_session, "67890")

    async def test_swallows_exception_and_logs_warning(self):
        """If deactivate_user raises, the exception is caught and logged, not propagated."""
        from bot.services.scheduler import _deactivate_blocked_user

        mock_session = _make_mock_session()
        mock_session.commit.side_effect = RuntimeError("db error")

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.deactivate_user", new_callable=AsyncMock), \
             patch("bot.services.scheduler.logger") as mock_logger:
            # Should NOT raise
            await _deactivate_blocked_user(999)

        mock_logger.warning.assert_called_once()
        warning_args, _ = mock_logger.warning.call_args
        assert any("999" in str(arg) for arg in warning_args)


# ─── _get_schedule_interval ───────────────────────────────────────────────


class TestGetScheduleInterval:
    async def test_returns_db_value(self):
        from bot.services.scheduler import _get_schedule_interval

        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_setting", AsyncMock(return_value="120")), \
             patch("bot.services.scheduler.settings") as mock_cfg:
            mock_cfg.SCHEDULE_CHECK_INTERVAL_S = 60
            result = await _get_schedule_interval()

        assert result == 120

    async def test_falls_back_when_none(self):
        from bot.services.scheduler import _get_schedule_interval

        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_setting", AsyncMock(return_value=None)), \
             patch("bot.services.scheduler.settings") as mock_cfg:
            mock_cfg.SCHEDULE_CHECK_INTERVAL_S = 60
            result = await _get_schedule_interval()

        assert result == 60

    async def test_falls_back_on_exception(self):
        from bot.services.scheduler import _get_schedule_interval

        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_setting", AsyncMock(side_effect=RuntimeError("db dead"))), \
             patch("bot.services.scheduler.settings") as mock_cfg:
            mock_cfg.SCHEDULE_CHECK_INTERVAL_S = 45
            result = await _get_schedule_interval()

        assert result == 45


# ─── _safe_delete_message ─────────────────────────────────────────────────


class TestSafeDeleteMessage:
    async def test_success(self):
        from bot.services.scheduler import _safe_delete_message

        bot = AsyncMock()
        await _safe_delete_message(bot, 111, 999)
        bot.delete_message.assert_awaited_once_with(111, 999)

    async def test_bad_request_suppressed(self):
        from bot.services.scheduler import _safe_delete_message

        bot = AsyncMock()
        bot.delete_message.side_effect = TelegramBadRequest(
            method=_make_method_mock(), message="message to delete not found"
        )
        await _safe_delete_message(bot, 111, 999)  # no raise

    async def test_forbidden_suppressed(self):
        from bot.services.scheduler import _safe_delete_message

        bot = AsyncMock()
        bot.delete_message.side_effect = _make_telegram_forbidden()
        await _safe_delete_message(bot, 111, 999)  # no raise

    async def test_generic_exception_suppressed(self):
        from bot.services.scheduler import _safe_delete_message

        bot = AsyncMock()
        bot.delete_message.side_effect = RuntimeError("network")
        await _safe_delete_message(bot, 111, 999)  # no raise


# ─── _delete_reminder_messages ────────────────────────────────────────────


class TestDeleteReminderMessages:
    async def test_no_user_is_noop(self):
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await _delete_reminder_messages(bot, "111")

        bot.delete_message.assert_not_awaited()

    async def test_deletes_bot_and_channel_messages(self):
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        mt = SimpleNamespace(
            last_reminder_message_id=42,
            last_channel_reminder_message_id=77,
        )
        cc = SimpleNamespace(channel_id="-100555")
        user = SimpleNamespace(message_tracking=mt, channel_config=cc)

        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await _delete_reminder_messages(bot, "111")

        assert bot.delete_message.await_count == 2
        assert mt.last_reminder_message_id is None
        assert mt.last_channel_reminder_message_id is None

    async def test_no_channel_config_skips_channel(self):
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        mt = SimpleNamespace(last_reminder_message_id=42, last_channel_reminder_message_id=None)
        user = SimpleNamespace(message_tracking=mt, channel_config=None)

        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await _delete_reminder_messages(bot, "111")

        assert bot.delete_message.await_count == 1

    async def test_outer_exception_suppressed(self):
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch(
                 "bot.services.scheduler.get_user_by_telegram_id",
                 AsyncMock(side_effect=RuntimeError("db gone")),
             ):
            await _delete_reminder_messages(bot, "111")  # no raise


# ─── _prerender_chart ─────────────────────────────────────────────────────


class TestPrerenderChart:
    async def test_redis_unavailable_skips(self):
        from bot.services.scheduler import _prerender_chart

        with patch("bot.services.chart_cache.is_usable", return_value=False), \
             patch("bot.services.chart_cache.delete", AsyncMock()) as mock_del:
            await _prerender_chart("kyiv", "1.1", _make_sched())

        mock_del.assert_not_awaited()

    async def test_success_stores_chart(self):
        from bot.services.scheduler import _prerender_chart

        with patch("bot.services.chart_cache.is_usable", return_value=True), \
             patch("bot.services.chart_cache.delete", AsyncMock()), \
             patch("bot.services.chart_cache.store", AsyncMock()) as mock_store, \
             patch(
                 "bot.services.chart_generator.generate_schedule_chart",
                 AsyncMock(return_value=b"PNG"),
             ):
            await _prerender_chart("kyiv", "1.1", _make_sched())

        mock_store.assert_awaited_once()

    async def test_chart_none_no_store(self):
        from bot.services.scheduler import _prerender_chart

        with patch("bot.services.chart_cache.is_usable", return_value=True), \
             patch("bot.services.chart_cache.delete", AsyncMock()), \
             patch("bot.services.chart_cache.store", AsyncMock()) as mock_store, \
             patch(
                 "bot.services.chart_generator.generate_schedule_chart",
                 AsyncMock(return_value=None),
             ):
            await _prerender_chart("kyiv", "1.1", _make_sched())

        mock_store.assert_not_awaited()

    async def test_exception_suppressed(self):
        from bot.services.scheduler import _prerender_chart

        with patch("bot.services.chart_cache.is_usable", return_value=True), \
             patch("bot.services.chart_cache.delete", AsyncMock(side_effect=RuntimeError("redis down"))):
            await _prerender_chart("kyiv", "1.1", _make_sched())  # no raise


# ─── _build_reminder_text ─────────────────────────────────────────────────


class TestBuildReminderText:
    def _next_event(self, event_type="power_off", anchor="2026-04-07T10:00:00",
                    end_time="2026-04-07T12:00:00", start_time="2026-04-07T10:00:00") -> dict:
        return {
            "type": event_type,
            "time": anchor,
            "endTime": end_time,
            "startTime": start_time,
            "minutes": 15,
        }

    def test_power_off_includes_outage_header(self):
        from bot.services.scheduler import _build_reminder_text

        ev = self._next_event("power_off")
        text = _build_reminder_text(ev, 15, _make_sched(), "kyiv", "1.1", is_possible=False)

        assert "Відключення через 15 хвилин" in text
        assert "Київ" in text
        assert "10:00" in text
        assert "Увімкнення о 12:00" in text

    def test_power_on_no_next_outage(self):
        from bot.services.scheduler import _build_reminder_text

        ev = self._next_event("power_on", anchor="2026-04-07T12:00:00",
                              start_time="2026-04-07T10:00:00", end_time="2026-04-07T12:00:00")
        text = _build_reminder_text(ev, 15, _make_sched(events=[]), "kyiv", "1.1", is_possible=False)

        assert "Увімкнення через 15 хвилин" in text
        assert "Більше відключень" in text

    def test_power_on_with_next_outage(self):
        from bot.services.scheduler import _build_reminder_text

        ev = self._next_event("power_on", anchor="2026-04-07T12:00:00",
                              start_time="2026-04-07T10:00:00", end_time="2026-04-07T12:00:00")
        events = [{"start": "2026-04-07T16:00:00", "end": "2026-04-07T18:00:00", "isPossible": False}]
        text = _build_reminder_text(ev, 30, _make_sched(events=events), "kyiv", "1.1", is_possible=False)

        assert "Наступне відключення о 16:00" in text

    def test_is_possible_flag(self):
        from bot.services.scheduler import _build_reminder_text

        ev = self._next_event("power_off")
        text = _build_reminder_text(ev, 15, _make_sched(), "kyiv", "1.1", is_possible=True)

        assert "Можливе відключення" in text

    def test_bad_event_data_no_schedule_line(self):
        from bot.services.scheduler import _build_reminder_text

        ev = {"type": "power_off", "time": "NOT_A_DATE", "minutes": 15}
        text = _build_reminder_text(ev, 15, _make_sched(), "kyiv", "1.1", is_possible=False)

        # Header still present, schedule block silently skipped
        assert "Відключення" in text


# ─── _find_next_outage_after ──────────────────────────────────────────────


class TestFindNextOutageAfter:
    def _dt(self, iso: str) -> datetime:
        dt = datetime.fromisoformat(iso)
        return dt.replace(tzinfo=KYIV_TZ) if dt.tzinfo is None else dt

    def test_returns_first_outage_after_dt(self):
        from bot.services.scheduler import _find_next_outage_after

        after = self._dt("2026-04-07T13:00:00")
        sched = _make_sched(events=[
            {"start": "2026-04-07T10:00:00", "end": "2026-04-07T12:00:00", "isPossible": False},
            {"start": "2026-04-07T16:00:00", "end": "2026-04-07T18:00:00", "isPossible": False},
        ])
        result = _find_next_outage_after(sched, after)
        assert result is not None
        assert "16:00" in result["start"]

    def test_returns_none_when_no_future_outage(self):
        from bot.services.scheduler import _find_next_outage_after

        after = self._dt("2026-04-07T23:00:00")
        result = _find_next_outage_after(_make_sched(), after)
        assert result is None

    def test_skips_possible_events(self):
        from bot.services.scheduler import _find_next_outage_after

        after = self._dt("2026-04-07T08:00:00")
        sched = _make_sched(events=[
            {"start": "2026-04-07T10:00:00", "end": "2026-04-07T12:00:00", "isPossible": True},
            {"start": "2026-04-07T16:00:00", "end": "2026-04-07T18:00:00", "isPossible": False},
        ])
        result = _find_next_outage_after(sched, after)
        assert result is not None
        assert "16:00" in result["start"]

    def test_bad_iso_event_skipped(self):
        from bot.services.scheduler import _find_next_outage_after

        after = self._dt("2026-04-07T08:00:00")
        sched = _make_sched(events=[{"start": "NOT_A_DATE", "end": "NOT_A_DATE", "isPossible": False}])
        result = _find_next_outage_after(sched, after)
        assert result is None


# ─── _check_all_schedules ────────────────────────────────────────────────


class TestCheckAllSchedules:
    async def test_no_update_returns_early(self):
        from bot.services.scheduler import _check_all_schedules

        with patch("bot.services.scheduler.check_source_repo_updated", AsyncMock(return_value=(False, None))), \
             patch("bot.services.scheduler._check_single_queue", AsyncMock()) as mock_single:
            await _check_all_schedules(AsyncMock())

        mock_single.assert_not_awaited()

    async def test_fetches_and_checks_all_pairs(self):
        from bot.services.scheduler import _check_all_schedules

        bot = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler.check_source_repo_updated", AsyncMock(return_value=(True, "abc"))), \
             _patch_async_session(mock_session), \
             patch(
                 "bot.services.scheduler.get_distinct_region_queue_pairs",
                 AsyncMock(return_value=[("kyiv", "1.1"), ("kyiv", "2.1")]),
             ), \
             patch("bot.services.scheduler.fetch_schedule_data", AsyncMock(return_value={"fact": {}})), \
             patch("bot.services.scheduler._check_single_queue", AsyncMock()) as mock_single:
            await _check_all_schedules(bot)

        assert mock_single.await_count == 2

    async def test_fetch_exception_continues_to_check(self):
        from bot.services.scheduler import _check_all_schedules

        bot = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler.check_source_repo_updated", AsyncMock(return_value=(True, "abc"))), \
             _patch_async_session(mock_session), \
             patch(
                 "bot.services.scheduler.get_distinct_region_queue_pairs",
                 AsyncMock(return_value=[("kyiv", "1.1")]),
             ), \
             patch("bot.services.scheduler.fetch_schedule_data", AsyncMock(side_effect=RuntimeError("net"))), \
             patch("bot.services.scheduler._check_single_queue", AsyncMock()) as mock_single:
            await _check_all_schedules(bot)

        # Fetch exception caught by asyncio.gather → single check called with None
        mock_single.assert_awaited_once()


# ─── _send_schedule_notification ─────────────────────────────────────────


async def _fake_retry_bot_call(fn, **kw):
    return await fn()


class TestSendScheduleNotification:
    def _common_patches(self, user):
        return [
            patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.services.scheduler.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.services.scheduler.format_schedule_message", return_value="<b>Розклад</b>"),
            patch("bot.services.scheduler.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.services.scheduler.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.services.scheduler.append_timestamp", return_value=("plain", [])),
            patch("bot.services.scheduler.html_to_entities", return_value=("plain", [])),
            patch("bot.services.scheduler.to_aiogram_entities", return_value=[]),
            patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call),
        ]

    async def test_user_not_found_returns_early(self):
        from bot.services.scheduler import _send_schedule_notification

        bot = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=None)), \
             patch("bot.services.scheduler.get_schedule_check_time", AsyncMock(return_value=None)):
            await _send_schedule_notification(bot, SimpleNamespace(telegram_id="111"), {}, {}, {})

        bot.send_message.assert_not_awaited()

    async def test_notify_disabled_returns_early(self):
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user(notification_settings=_make_ns(notify_schedule_changes=False))
        bot = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)), \
             patch("bot.services.scheduler.get_schedule_check_time", AsyncMock(return_value=None)):
            await _send_schedule_notification(bot, user, {}, {}, {})

        bot.send_message.assert_not_awaited()

    async def test_sends_text_message_when_no_image(self):
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user()
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        bot.send_message.return_value = mock_msg

        mock_session = _make_mock_session()
        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            await _send_schedule_notification(bot, user, {}, {}, {})

        bot.send_message.assert_awaited_once()

    async def test_sends_photo_when_image_available(self):
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user()
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        bot.send_photo.return_value = mock_msg

        mock_session = _make_mock_session()
        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            # Override: image is available
            stack.enter_context(
                patch("bot.services.scheduler.fetch_schedule_image", AsyncMock(return_value=b"PNG"))
            )
            await _send_schedule_notification(bot, user, {}, {}, {})

        bot.send_photo.assert_awaited_once()

    async def test_forbidden_error_deactivates_user(self):
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user()
        bot = AsyncMock()
        mock_session = _make_mock_session()
        mock_deact = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            stack.enter_context(
                patch("bot.services.scheduler.retry_bot_call",
                      AsyncMock(side_effect=_make_telegram_forbidden()))
            )
            stack.enter_context(
                patch("bot.services.scheduler._deactivate_blocked_user", mock_deact)
            )
            await _send_schedule_notification(bot, user, {}, {}, {})

        mock_deact.assert_awaited_once()


# ─── _send_reminder ───────────────────────────────────────────────────────


class TestSendReminder:
    async def test_ns_none_returns_false(self):
        from bot.services.scheduler import _send_reminder

        result = await _send_reminder(
            AsyncMock(), _make_user(), {"type": "power_off", "time": "2026-04-07T10:00:00",
                                        "endTime": "2026-04-07T12:00:00", "minutes": 15},
            15, _make_sched(), "kyiv", "1.1", False, None, None,
        )
        assert result is False

    async def test_sends_to_bot_returns_true(self):
        from bot.services.scheduler import _send_reminder

        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        bot.send_message.return_value = mock_msg

        user = _make_user()
        mock_session = _make_mock_session()
        db_user = _make_user()

        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="Нагадування"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=db_user)):
            result = await _send_reminder(
                bot, user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False,
                user.notification_settings, None,
            )

        assert result is True
        bot.send_message.assert_awaited_once()

    async def test_forbidden_deactivates_user(self):
        from bot.services.scheduler import _send_reminder

        user = _make_user()
        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", AsyncMock(side_effect=_make_telegram_forbidden())), \
             patch("bot.services.scheduler._deactivate_blocked_user", AsyncMock()) as mock_deact:
            result = await _send_reminder(
                AsyncMock(), user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False,
                user.notification_settings, None,
            )

        mock_deact.assert_awaited_once()
        assert result is False

    async def test_send_to_channel_when_configured(self):
        from bot.services.scheduler import _send_reminder

        bot = AsyncMock()
        bot_msg = MagicMock()
        bot_msg.message_id = 11
        ch_msg = MagicMock()
        ch_msg.message_id = 22
        bot.send_message.side_effect = [bot_msg, ch_msg]

        user = _make_user()
        cc = SimpleNamespace(
            channel_id="-100555",
            channel_status="active",
            channel_paused=False,
            ch_notify_remind_off=True,
            ch_notify_remind_on=True,
            ch_remind_15m=True,
            ch_remind_30m=False,
            ch_remind_1h=False,
        )
        mock_session = _make_mock_session()
        db_user = _make_user()

        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=db_user)):
            result = await _send_reminder(
                bot, user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False,
                user.notification_settings, cc,
            )

        assert result is True
        assert bot.send_message.await_count == 2


# ─── TestCheckSingleQueue — uncovered branches ───────────────────────────


class TestCheckSingleQueueBranches:
    """Additional branch coverage for _check_single_queue."""

    def _base_patches(self, stored_hash, snapshot, yesterday_snapshot=None,
                      quiet=False, users=None):
        """Return a list of common patches for _check_single_queue tests."""
        sched = _make_sched(events=[{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}])
        if users is None:
            users = [_make_user()]
        daily_side_effect = [snapshot, yesterday_snapshot]
        return sched, [
            patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "d"}),
            patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched),
            patch("bot.services.scheduler.calculate_schedule_hash", return_value="new_hash"),
            patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value=stored_hash),
            patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock,
                  side_effect=daily_side_effect),
            patch("bot.services.scheduler._is_quiet_hours", return_value=quiet),
            patch("bot.services.scheduler.invalidate_image_cache", new_callable=AsyncMock),
            patch("bot.services.scheduler._prerender_chart", new_callable=AsyncMock),
            patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock),
            patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock),
            patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock),
            patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users),
            patch("bot.services.scheduler._send_notifications_to_users", new_callable=AsyncMock),
            patch("bot.services.scheduler.mark_pending_notifications_sent", new_callable=AsyncMock),
            patch("bot.services.scheduler.update_power_notifications_on_schedule_change", new_callable=AsyncMock),
        ]

    async def test_hash_unchanged_snapshot_none_creates_snapshot(self):
        """When hash matches but no snapshot yet, upsert_daily_snapshot is called."""
        from contextlib import ExitStack

        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        sched = _make_sched(events=[])
        upsert_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            stack.enter_context(patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "d"}))
            stack.enter_context(patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched))
            stack.enter_context(patch("bot.services.scheduler.calculate_schedule_hash", return_value="same_hash"))
            stack.enter_context(patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value="same_hash"))
            stack.enter_context(patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=None))
            stack.enter_context(patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock))
            stack.enter_context(patch("bot.services.scheduler.upsert_daily_snapshot", upsert_mock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is False
        upsert_mock.assert_awaited_once()

    async def test_snapshot_none_yesterday_today_updated(self):
        """No today snapshot + yesterday's tomorrow_hash changed → todayUpdated in update_type."""
        from contextlib import ExitStack

        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        # yesterday had no events for "today" (tomorrow_hash=None) — consistent with
        # schedule_data={"events": []}. Now there ARE new events (new_today_hash="new_today_h")
        # → todayUpdated should be set.
        yesterday_mock = SimpleNamespace(
            schedule_data=json.dumps({"events": []}),
            tomorrow_hash=None,
        )
        sched, patches = self._base_patches(
            stored_hash=None,  # initial load
            snapshot=None,
            yesterday_snapshot=yesterday_mock,
            quiet=True,  # save as pending so we can verify update_type
        )

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            # today: new hash appears (was None, now "new_today_h") → todayUpdated
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash", side_effect=["new_today_h", None]))
            save_mock = stack.enter_context(patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        save_mock.assert_awaited_once()
        update_type_json = save_mock.await_args[0][4]
        assert json.loads(update_type_json).get("todayUpdated") is True

    async def test_snapshot_none_tomorrow_appeared(self):
        """No today snapshot, new tomorrow hash exists → tomorrowAppeared in update_type."""
        from contextlib import ExitStack

        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        sched = _make_sched(events=[{"start": "2025-01-15T08:00:00", "end": "2025-01-15T10:00:00"}])

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            stack.enter_context(patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "d"}))
            stack.enter_context(patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched))
            stack.enter_context(patch("bot.services.scheduler.calculate_schedule_hash", return_value="new_hash"))
            stack.enter_context(patch("bot.services.scheduler.get_schedule_hash", new_callable=AsyncMock, return_value=None))
            stack.enter_context(patch("bot.services.scheduler.get_daily_snapshot", new_callable=AsyncMock, return_value=None))
            # today=None (no events today), tomorrow="new_tomorrow_h" → tomorrowAppeared
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash", side_effect=[None, "new_tomorrow_h"]))
            stack.enter_context(patch("bot.services.scheduler._is_quiet_hours", return_value=True))
            stack.enter_context(patch("bot.services.scheduler.invalidate_image_cache", new_callable=AsyncMock))
            stack.enter_context(patch("bot.services.scheduler._prerender_chart", new_callable=AsyncMock))
            stack.enter_context(patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock))
            stack.enter_context(patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock))
            save_mock = stack.enter_context(patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        save_mock.assert_awaited_once()
        update_type_json = save_mock.await_args[0][4]
        assert json.loads(update_type_json).get("tomorrowAppeared") is True

    async def test_snapshot_exists_today_updated(self):
        """Snapshot exists with different today_hash → todayUpdated computed from old/new events."""
        from contextlib import ExitStack

        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        # today_hash=None is consistent with schedule_data={"events": []}:
        # no events on today's date → _compute_date_hash would return None.
        # New hash "new_today_h" differs → todayUpdated.
        snapshot_mock = SimpleNamespace(
            today_hash=None,
            tomorrow_hash=None,
            schedule_data=json.dumps({"events": []}),
        )
        sched, patches = self._base_patches(
            stored_hash="old_all_hash",
            snapshot=snapshot_mock,
            yesterday_snapshot=None,
            quiet=True,
        )

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            # today: "new_today_h" ≠ stored None → todayUpdated; tomorrow: None
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash", side_effect=["new_today_h", None]))
            save_mock = stack.enter_context(patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        save_mock.assert_awaited_once()
        update_type_json = save_mock.await_args[0][4]
        assert json.loads(update_type_json).get("todayUpdated") is True

    async def test_snapshot_exists_tomorrow_appeared(self):
        """Snapshot exists with null tomorrow_hash, new tomorrow appears → tomorrowAppeared."""
        from contextlib import ExitStack

        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        # today_hash=None consistent with schedule_data={"events": []} (no events).
        # tomorrow_hash=None: no tomorrow data was stored previously.
        # New tomorrow_hash="new_tomorrow_h" → tomorrowAppeared.
        snapshot_mock = SimpleNamespace(
            today_hash=None,
            tomorrow_hash=None,
            schedule_data=json.dumps({"events": []}),
        )
        sched, patches = self._base_patches(
            stored_hash="old_all_hash",
            snapshot=snapshot_mock,
            yesterday_snapshot=None,
            quiet=True,
        )

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            # today same (both None), tomorrow newly appears → tomorrowAppeared
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash", side_effect=[None, "new_tomorrow_h"]))
            save_mock = stack.enter_context(patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        save_mock.assert_awaited_once()
        update_type_json = save_mock.await_args[0][4]
        assert json.loads(update_type_json).get("tomorrowAppeared") is True

    async def test_power_notify_exception_suppressed(self):
        """Exception from update_power_notifications_on_schedule_change is suppressed."""
        from contextlib import ExitStack

        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        sched, patches = self._base_patches(
            stored_hash="old_hash",
            snapshot=None,
            quiet=False,
        )
        # Apply all base patches first, then override update_power with raising version.
        # The innermost (last-entered) patch for the same target wins.
        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(
                patch("bot.services.scheduler.update_power_notifications_on_schedule_change",
                      new_callable=AsyncMock, side_effect=RuntimeError("pwr error"))
            )
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")  # no raise

        assert result is True


# ─── TestFlushPendingNotifications — extra branches ────────────────────────


class TestFlushPendingNotificationsBranches:
    async def test_pending_notif_disappeared_falls_through_to_daily_planned(self):
        """If pending row exists in set but notif=None at fetch time, send daily-planned."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        sched = _make_sched(events=[])
        users = [_make_user()]
        notify_mock = AsyncMock()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_all_pending_region_queue_pairs", new_callable=AsyncMock, return_value=[["kyiv", "1.1"]]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=users), \
             patch("bot.services.scheduler.get_latest_pending_notification", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler._send_notifications_to_users", notify_mock), \
             patch("bot.services.scheduler.update_schedule_check_time", new_callable=AsyncMock), \
             patch("bot.services.scheduler.upsert_daily_snapshot", new_callable=AsyncMock), \
             patch("bot.services.scheduler.calculate_schedule_hash", return_value="h"), \
             patch("bot.services.scheduler._compute_date_hash", return_value=None), \
             patch("bot.services.scheduler.delete_old_pending_notifications", new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders", new_callable=AsyncMock, return_value=0):
            await flush_pending_notifications(bot_mock)

        # Should still send as daily planned
        notify_mock.assert_awaited_once()
        call_kwargs = notify_mock.call_args[1]
        assert call_kwargs.get("is_daily_planned") is True

    async def test_exception_in_pair_is_caught(self):
        """Per-pair exception is caught and loop continues."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_all_pending_region_queue_pairs", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1"), ("kyiv", "2.1")]), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, side_effect=RuntimeError("db error")), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": "d"}), \
             patch("bot.services.scheduler.delete_old_pending_notifications", new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders", new_callable=AsyncMock, return_value=0):
            # No raise — exception caught per pair
            await flush_pending_notifications(bot_mock)


# ─── TestCatchUpMissedReminders ───────────────────────────────────────────


class TestCatchUpMissedReminders:
    async def test_empty_pairs_is_noop(self):
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_no_raw_data_skips_pair(self):
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value=None), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_minutes_outside_window_skips(self):
        """minutes_until > max_remind_m + 1 → skip."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        sched = _make_sched(events=[])
        next_ev = {"type": "power_off", "time": "t", "minutes": 120, "isPossible": False}

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_sends_reminder_in_catch_up_window(self):
        """minutes_until=15, user has remind_15m → _send_reminder called."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        sched = _make_sched(events=[])
        next_ev = {
            "type": "power_off",
            "time": "2026-04-07T10:00:00",
            "endTime": "2026-04-07T12:00:00",
            "minutes": 15,
            "isPossible": False,
        }
        user = _make_user(notification_settings=_make_ns(remind_15m=True, notify_remind_off=True))

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=sched), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler.check_reminders_sent_batch", new_callable=AsyncMock, return_value=set()), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock, return_value=True) as mock_send, \
             patch("bot.services.scheduler.mark_reminder_sent", new_callable=AsyncMock):
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_called_once()


# ─── TestScheduleCheckerLoop ─────────────────────────────────────────────


class TestScheduleCheckerLoop:
    def setup_method(self):
        import bot.services.scheduler as sched
        sched._running = False

    def teardown_method(self):
        import bot.services.scheduler as sched
        sched._running = False

    async def test_one_iteration_then_stop(self):
        """Loop body runs once; asyncio.sleep sets _running=False to exit."""
        import bot.services.scheduler as bcast_mod
        from bot.services.scheduler import schedule_checker_loop

        bot_mock = AsyncMock()
        check_mock = AsyncMock()

        async def _stop_after_first(*_a, **_kw):
            bcast_mod._running = False

        with patch("bot.services.scheduler._get_schedule_interval", new_callable=AsyncMock, return_value=1), \
             patch("bot.services.scheduler._check_all_schedules", check_mock), \
             patch("bot.services.scheduler.asyncio.sleep", side_effect=_stop_after_first):
            await schedule_checker_loop(bot_mock)

        check_mock.assert_awaited_once()

    async def test_exception_in_loop_body_is_caught(self):
        """Exceptions from _check_all_schedules are caught; loop still sleeps."""
        import bot.services.scheduler as bcast_mod
        from bot.services.scheduler import schedule_checker_loop

        bot_mock = AsyncMock()

        async def _stop_after_first(*_a, **_kw):
            bcast_mod._running = False

        with patch("bot.services.scheduler._get_schedule_interval", new_callable=AsyncMock, return_value=1), \
             patch("bot.services.scheduler._check_all_schedules", AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("bot.services.scheduler.sentry_sdk"), \
             patch("bot.services.scheduler.asyncio.sleep", side_effect=_stop_after_first):
            await schedule_checker_loop(bot_mock)  # no raise


# ─── TestCheckAndSendReminders — extra branches ──────────────────────────


class TestCheckAndSendRemindersBranches:
    async def test_cleanup_db_error_is_suppressed(self):
        """get_active_reminder_anchors raising is caught; processing continues."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, side_effect=RuntimeError("db gone")), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[]), \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)  # no raise

    async def test_no_next_event_skips_pair(self):
        """find_next_event returning None causes the pair to be skipped."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=None), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_user_with_notify_remind_off_false_skipped(self):
        """User with notify_remind_off=False is excluded for power_off events."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        now = datetime.now(KYIV_TZ)
        start_iso = (now + timedelta(minutes=15)).isoformat()
        end_iso = (now + timedelta(minutes=75)).isoformat()
        next_ev = {"type": "power_off", "time": start_iso, "endTime": end_iso, "minutes": 15, "isPossible": False}
        # User has remind enabled but notify_remind_off=False → should be skipped
        user = _make_user(notification_settings=_make_ns(remind_15m=True, notify_remind_off=False))

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data", new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region", new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()


# ─── TestCheckAllSchedules — exception in _check_single_queue ───────────────


class TestCheckAllSchedulesExtraBranches:
    async def test_single_queue_exception_is_caught(self):
        """Exception from _check_single_queue is caught and reported to sentry."""
        from bot.services.scheduler import _check_all_schedules

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler.check_source_repo_updated", AsyncMock(return_value=(True, "abc"))), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs", AsyncMock(return_value=[("kyiv", "1.1")])), \
             patch("bot.services.scheduler.fetch_schedule_data", AsyncMock(return_value={"r": "d"})), \
             patch("bot.services.scheduler._check_single_queue", AsyncMock(side_effect=RuntimeError("queue error"))), \
             patch("bot.services.scheduler.sentry_sdk") as mock_sentry:
            await _check_all_schedules(bot_mock)  # no raise

        mock_sentry.capture_exception.assert_called_once()


# ─── TestCheckSingleQueue — more branch coverage ────────────────────────────


class TestCheckSingleQueueMoreBranches(TestCheckSingleQueueBranches):
    """Extra branches: 305-306, 314, 324-325, 331-348."""

    async def test_yesterday_json_parse_fails(self):
        """Invalid JSON in yesterday snapshot is caught (305-306)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        yesterday_mock = SimpleNamespace(schedule_data="NOT_VALID_JSON{", tomorrow_hash="some_hash")
        sched, patches = self._base_patches(stored_hash=None, snapshot=None,
                                            yesterday_snapshot=yesterday_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash", return_value=None))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True

    async def test_today_unchanged_when_tomorrow_appeared_and_today_matched(self):
        """todayUnchanged set when tomorrowAppeared + comparison succeeded + no todayUpdated (314)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        yesterday_mock = SimpleNamespace(schedule_data=json.dumps({"events": []}), tomorrow_hash="abc")
        sched, patches = self._base_patches(stored_hash=None, snapshot=None,
                                            yesterday_snapshot=yesterday_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            # today="abc" matches yesterday.tomorrow_hash → no todayUpdated; tomorrow appears
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash",
                                      side_effect=["abc", "new_tmrw"]))
            save_mock = stack.enter_context(
                patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        save_mock.assert_awaited_once()
        ut = json.loads(save_mock.await_args[0][4])
        assert ut.get("tomorrowAppeared") is True
        assert ut.get("todayUnchanged") is True

    async def test_snapshot_today_json_parse_fails(self):
        """Invalid schedule_data in snapshot when computing today changes is caught (324-325)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        snapshot_mock = SimpleNamespace(today_hash=None, tomorrow_hash=None,
                                        schedule_data="INVALID{JSON")
        sched, patches = self._base_patches(stored_hash="old_hash", snapshot=snapshot_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash",
                                      side_effect=["new_today_h", None]))
            save_mock = stack.enter_context(
                patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        ut = json.loads(save_mock.await_args[0][4])
        assert ut.get("todayUpdated") is True

    async def test_snapshot_tomorrow_cancelled(self):
        """tomorrow_hash was set but now None → tomorrowCancelled (331-332)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        snapshot_mock = SimpleNamespace(today_hash=None, tomorrow_hash="old_tmrw",
                                        schedule_data=json.dumps({"events": []}))
        sched, patches = self._base_patches(stored_hash="old_hash", snapshot=snapshot_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            # today same, tomorrow disappears → tomorrowCancelled
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash",
                                      side_effect=[None, None]))
            save_mock = stack.enter_context(
                patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        ut = json.loads(save_mock.await_args[0][4])
        assert ut.get("tomorrowCancelled") is True

    async def test_snapshot_tomorrow_updated(self):
        """tomorrow_hash changed to new non-None value → tomorrowUpdated (334-346)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        snapshot_mock = SimpleNamespace(today_hash=None, tomorrow_hash="old_tmrw",
                                        schedule_data=json.dumps({"events": []}))
        sched, patches = self._base_patches(stored_hash="old_hash", snapshot=snapshot_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash",
                                      side_effect=[None, "new_tmrw"]))
            save_mock = stack.enter_context(
                patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        ut = json.loads(save_mock.await_args[0][4])
        assert ut.get("tomorrowUpdated") is True

    async def test_snapshot_tomorrow_update_json_parse_fails(self):
        """Invalid schedule_data when computing tomorrow changes is caught (347-348)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        snapshot_mock = SimpleNamespace(today_hash=None, tomorrow_hash="old_tmrw",
                                        schedule_data="INVALID{JSON")
        sched, patches = self._base_patches(stored_hash="old_hash", snapshot=snapshot_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash",
                                      side_effect=[None, "new_tmrw"]))
            save_mock = stack.enter_context(
                patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        ut = json.loads(save_mock.await_args[0][4])
        assert ut.get("tomorrowUpdated") is True


# ─── Flush purge logs + CatchUp extra branches ──────────────────────────────


class TestFlushPendingNotificationsPurgeLogs:
    async def test_deleted_count_logged(self):
        """Positive deleted counts exercise the purge branches (coverage for positive-count paths)."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_all_pending_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.delete_old_pending_notifications",
                   new_callable=AsyncMock, return_value=5), \
             patch("bot.services.scheduler.cleanup_old_reminders",
                   new_callable=AsyncMock, return_value=3):
            await flush_pending_notifications(bot_mock)  # no raise


class TestCatchUpMissedRemindersBranches:
    async def test_no_next_event_skips_pair(self):
        """find_next_event returning None → continue (561)."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=None), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_user_without_ns_skipped(self):
        """User with notification_settings=None is filtered out (581)."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        next_ev = {"type": "power_off", "time": "2026-04-07T10:00:00",
                   "minutes": 15, "isPossible": False}
        user_no_ns = _make_user(notification_settings=None)

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user_no_ns]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_per_remind_m_outside_window_skipped(self):
        """minutes_until > remind_m+1 → continue for that remind_m; only remind_m=60 eligible."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        # minutes_until=45: skips remind_m=30 (45>31) and remind_m=15 (45>16).
        # Only remind_m=60 is in window (45 ≤ 61), so _send_reminder is called once.
        next_ev = {"type": "power_off", "time": "2026-04-07T10:00:00",
                   "minutes": 45, "isPossible": False}
        user = _make_user(notification_settings=_make_ns(
            remind_1h=True, remind_30m=False, remind_15m=False))

        import bot.services.scheduler as _sched_mod

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user]) as mock_get_users, \
             patch("bot.services.scheduler.check_reminders_sent_batch",
                   new_callable=AsyncMock, return_value=set()) as mock_batch, \
             patch("bot.services.scheduler._send_reminder",
                   new_callable=AsyncMock, return_value=False) as mock_send, \
             patch("bot.services.scheduler.mark_reminder_sent", new_callable=AsyncMock), \
             patch("bot.services.scheduler._REMIND_MINUTES", [60, 30, 15]), \
             patch("bot.services.scheduler._REMIND_FIELDS",
                   {60: "remind_1h", 30: "remind_30m", 15: "remind_15m"}), \
             patch("bot.services.scheduler._REMIND_TYPE_MAP",
                   {60: "1h", 30: "30m", 15: "15m"}):
            # Diagnostics printed to stdout — visible in pytest failure CAPTURED STDOUT CALL.
            print(f"\n[diag] _REMIND_MINUTES={_sched_mod._REMIND_MINUTES!r}")
            print(f"[diag] _REMIND_FIELDS={_sched_mod._REMIND_FIELDS!r}")
            print(f"[diag] remind_1h={user.notification_settings.remind_1h!r}")
            print(f"[diag] notify_remind_off={user.notification_settings.notify_remind_off!r}")
            await catch_up_missed_reminders(bot_mock)
            print(f"[diag] mock_get_users.call_count={mock_get_users.call_count}")
            print(f"[diag] mock_batch.call_count={mock_batch.call_count}")
            print(f"[diag] mock_send.call_count={mock_send.call_count}")

        # get_active_users_by_region must be called — proves execution reached pair processing.
        assert mock_get_users.call_count == 1, (
            f"get_active_users_by_region called {mock_get_users.call_count} times "
            f"(expected 1 — execution should reach kyiv/1.1 pair processing)"
        )
        # check_reminders_sent_batch called once (for remind_m=60 batch).
        assert mock_batch.call_count == 1, (
            f"check_reminders_sent_batch called {mock_batch.call_count} times "
            f"(expected 1 — to_send should be non-empty for remind_m=60). "
            f"get_users_called={mock_get_users.call_count}, "
            f"remind_1h={user.notification_settings.remind_1h}"
        )
        # _send_reminder called once (only remind_m=60 window is eligible).
        assert mock_send.call_count == 1, (
            f"_send_reminder called {mock_send.call_count} times (expected 1). "
            f"batch_called={mock_batch.call_count}, "
            f"batch_args={mock_batch.call_args_list}"
        )

    async def test_power_off_notify_remind_off_false_skipped(self):
        """power_off + notify_remind_off=False → excluded from to_send (601)."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        next_ev = {"type": "power_off", "time": "2026-04-07T10:00:00",
                   "minutes": 15, "isPossible": False}
        user = _make_user(notification_settings=_make_ns(
            remind_15m=True, notify_remind_off=False, notify_remind_on=True))

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler.check_reminders_sent_batch",
                   new_callable=AsyncMock, return_value=set()), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_power_on_notify_remind_on_false_skipped(self):
        """power_on + notify_remind_on=False → excluded from to_send (603)."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        next_ev = {"type": "power_on", "time": "2026-04-07T10:00:00",
                   "minutes": 15, "isPossible": False}
        user = _make_user(notification_settings=_make_ns(
            remind_15m=True, notify_remind_off=True, notify_remind_on=False))

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler.check_reminders_sent_batch",
                   new_callable=AsyncMock, return_value=set()), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_already_sent_reminder_skipped(self):
        """User already in already_sent set is skipped (623)."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        next_ev = {"type": "power_off", "time": "2026-04-07T10:00:00",
                   "minutes": 15, "isPossible": False}
        user = _make_user(notification_settings=_make_ns(remind_15m=True, notify_remind_off=True))

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler.check_reminders_sent_batch",
                   new_callable=AsyncMock,
                   return_value=[("111222333", "2026-04-07T10:00:00")]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send:
            await catch_up_missed_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_exception_per_pair_is_suppressed(self):
        """Exception during pair processing is caught (638-639)."""
        from bot.services.scheduler import catch_up_missed_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, side_effect=RuntimeError("fetch error")):
            await catch_up_missed_reminders(bot_mock)  # no raise


# ─── TestDailyFlushLoop ──────────────────────────────────────────────────────


class TestDailyFlushLoop:
    def setup_method(self):
        import bot.services.scheduler as sched
        self._saved_running = sched._running

    def teardown_method(self):
        import bot.services.scheduler as sched
        sched._running = self._saved_running

    async def test_target_adjusted_when_past_six_am(self):
        """now >= 06:00 → target pushed to next day (651-652)."""
        from datetime import datetime as real_dt
        import bot.services.scheduler as sched_mod
        from bot.services.scheduler import daily_flush_loop

        sched_mod._running = True

        async def _stop(*_):
            sched_mod._running = False

        times = [
            real_dt(2026, 4, 7, 6, 1, 0, tzinfo=KYIV_TZ),  # outer: 06:01 ≥ 06:00 → +1 day
            real_dt(2026, 4, 7, 6, 1, 0, tzinfo=KYIV_TZ),  # inner: remaining positive → sleep
        ]
        mock_dt = MagicMock()
        mock_dt.now.side_effect = times

        with patch("bot.services.scheduler.datetime", mock_dt), \
             patch("bot.services.scheduler.asyncio.sleep", side_effect=_stop):
            await daily_flush_loop(AsyncMock())  # exits after _running=False

    async def test_flushes_once_and_catch_up_then_exits(self):
        """Flush and catch-up called once; loop exits when _running=False (646-677)."""
        from datetime import datetime as real_dt
        import bot.services.scheduler as sched_mod
        from bot.services.scheduler import daily_flush_loop

        sched_mod._running = True
        bot_mock = AsyncMock()
        flush_mock = AsyncMock()
        catchup_mock = AsyncMock()

        async def _flush_and_stop(*_):
            sched_mod._running = False

        flush_mock.side_effect = _flush_and_stop

        times = [
            real_dt(2026, 4, 7, 5, 59, 0, tzinfo=KYIV_TZ),  # outer: 05:59 → target=06:00
            real_dt(2026, 4, 7, 5, 59, 0, tzinfo=KYIV_TZ),  # inner 1st: remaining>0 → sleep
            real_dt(2026, 4, 7, 6, 1, 0, tzinfo=KYIV_TZ),   # inner 2nd: remaining<0 → break
        ]
        mock_dt = MagicMock()
        mock_dt.now.side_effect = times

        with patch("bot.services.scheduler.datetime", mock_dt), \
             patch("bot.services.scheduler.flush_pending_notifications", flush_mock), \
             patch("bot.services.scheduler.catch_up_missed_reminders", catchup_mock), \
             patch("bot.services.scheduler.asyncio.sleep", AsyncMock()):
            await daily_flush_loop(bot_mock)

        flush_mock.assert_awaited_once()
        catchup_mock.assert_awaited_once()

    async def test_flush_retries_on_exception_and_catch_up_exception_caught(self):
        """Flush retries on error; catch_up error caught (667-671, 679-680)."""
        from datetime import datetime as real_dt
        import bot.services.scheduler as sched_mod
        from bot.services.scheduler import daily_flush_loop

        sched_mod._running = True
        bot_mock = AsyncMock()
        attempt_count = [0]

        async def _flush_raises_twice_then_stops(*_):
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise RuntimeError("flush error")
            sched_mod._running = False  # 3rd attempt stops loop but doesn't raise

        times = [
            real_dt(2026, 4, 7, 5, 59, 0, tzinfo=KYIV_TZ),
            real_dt(2026, 4, 7, 5, 59, 0, tzinfo=KYIV_TZ),
            real_dt(2026, 4, 7, 6, 1, 0, tzinfo=KYIV_TZ),
        ]
        mock_dt = MagicMock()
        mock_dt.now.side_effect = times

        with patch("bot.services.scheduler.datetime", mock_dt), \
             patch("bot.services.scheduler.flush_pending_notifications",
                   side_effect=_flush_raises_twice_then_stops), \
             patch("bot.services.scheduler.catch_up_missed_reminders",
                   AsyncMock(side_effect=RuntimeError("catch error"))), \
             patch("bot.services.scheduler.asyncio.sleep", AsyncMock()), \
             patch("bot.services.scheduler.sentry_sdk"):
            await daily_flush_loop(bot_mock)  # no raise

        assert attempt_count[0] == 3


# ─── _send_notifications_to_users — retry second fail ───────────────────────


class TestSendNotificationsToUsersRetryFail:
    async def test_retry_after_second_attempt_exception(self):
        """Second attempt after TelegramRetryAfter also fails → error logged, no raise (720-721)."""
        from bot.services.scheduler import _send_notifications_to_users

        bot_mock = AsyncMock()
        user = _make_user()
        sched = _make_sched()
        retry_exc = _make_telegram_retry_after(retry_after=1)
        call_count = [0]

        async def _retry_then_fail(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise retry_exc
            raise RuntimeError("still failing after retry")

        with patch("bot.services.scheduler._send_schedule_notification",
                   side_effect=_retry_then_fail), \
             patch("bot.services.scheduler.asyncio.sleep", AsyncMock()):
            await _send_notifications_to_users(bot_mock, [user], sched, {}, {})  # no raise

        assert call_count[0] == 2


# ─── _send_schedule_notification — extra branches ───────────────────────────


class TestSendScheduleNotificationMore:
    def _common_patches(self, user):
        return [
            patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.services.scheduler.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.services.scheduler.format_schedule_message", return_value="<b>Розклад</b>"),
            patch("bot.services.scheduler.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.services.scheduler.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.services.scheduler.append_timestamp", return_value=("plain", [])),
            patch("bot.services.scheduler.html_to_entities", return_value=("plain", [])),
            patch("bot.services.scheduler.to_aiogram_entities", return_value=[]),
            patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call),
        ]

    async def test_deletes_previous_message_before_send(self):
        """Previous schedule message deleted when not daily_planned (833)."""
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user(message_tracking=SimpleNamespace(
            last_schedule_message_id=77,
            last_reminder_message_id=None,
            last_channel_reminder_message_id=None,
        ))
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        bot.send_message.return_value = mock_msg
        mock_session = _make_mock_session()
        safe_delete_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            stack.enter_context(
                patch("bot.services.scheduler._safe_delete_message", safe_delete_mock))
            await _send_schedule_notification(bot, user, {}, {}, {})

        safe_delete_mock.assert_awaited_once()

    async def test_send_exception_suppressed(self):
        """General exception in bot send is caught (862-863)."""
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user()
        bot = AsyncMock()
        mock_session = _make_mock_session()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            stack.enter_context(
                patch("bot.services.scheduler.retry_bot_call",
                      AsyncMock(side_effect=RuntimeError("net error"))))
            await _send_schedule_notification(bot, user, {}, {}, {})  # no raise

    async def test_channel_send_text(self):
        """Channel with ch_notify_schedule=True gets text message; ID saved (871-893, 915)."""
        from bot.services.scheduler import _send_schedule_notification

        cc = _make_cc(channel_id="-100555", channel_status="active", ch_notify_schedule=True)
        user = _make_user(channel_config=cc)
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        bot.send_message.return_value = mock_msg
        mock_session = _make_mock_session()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            await _send_schedule_notification(bot, user, {}, {}, {})

        assert bot.send_message.await_count == 2
        assert cc.last_schedule_message_id == 555

    async def test_channel_deletes_previous_message(self):
        """Channel previous message deleted when last_schedule_message_id set (877)."""
        from bot.services.scheduler import _send_schedule_notification

        cc = _make_cc(channel_id="-100555", channel_status="active",
                      ch_notify_schedule=True, last_schedule_message_id=88)
        user = _make_user(channel_config=cc)
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        bot.send_message.return_value = mock_msg
        mock_session = _make_mock_session()
        safe_delete_mock = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            stack.enter_context(
                patch("bot.services.scheduler._safe_delete_message", safe_delete_mock))
            await _send_schedule_notification(bot, user, {}, {}, {})

        # safe_delete called for channel (user.message_tracking.last_schedule_message_id=None)
        safe_delete_mock.assert_awaited_once()

    async def test_channel_send_photo(self):
        """Channel gets photo when image available (879-888)."""
        from bot.services.scheduler import _send_schedule_notification

        cc = _make_cc(channel_id="-100555", channel_status="active", ch_notify_schedule=True)
        user = _make_user(channel_config=cc)
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        bot.send_photo.return_value = mock_msg
        mock_session = _make_mock_session()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            stack.enter_context(
                patch("bot.services.scheduler.fetch_schedule_image", AsyncMock(return_value=b"PNG")))
            await _send_schedule_notification(bot, user, {}, {}, {})

        assert bot.send_photo.await_count == 2

    async def test_channel_forbidden_error_suppressed(self):
        """TelegramForbiddenError from channel send is caught (896-900)."""
        from bot.services.scheduler import _send_schedule_notification

        cc = _make_cc(channel_id="-100555", channel_status="active", ch_notify_schedule=True)
        user = _make_user(channel_config=cc)
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        call_count = [0]

        async def _send_or_forbidden(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_msg
            raise _make_telegram_forbidden()

        bot.send_message = _send_or_forbidden
        mock_session = _make_mock_session()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            await _send_schedule_notification(bot, user, {}, {}, {})  # no raise

    async def test_channel_exception_suppressed(self):
        """General exception in channel send is caught (901-902)."""
        from bot.services.scheduler import _send_schedule_notification

        cc = _make_cc(channel_id="-100555", channel_status="active", ch_notify_schedule=True)
        user = _make_user(channel_config=cc)
        bot = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 555
        call_count = [0]

        async def _send_or_error(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_msg
            raise RuntimeError("channel error")

        bot.send_message = _send_or_error
        mock_session = _make_mock_session()

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in self._common_patches(user):
                stack.enter_context(p)
            await _send_schedule_notification(bot, user, {}, {}, {})  # no raise

    async def test_top_level_exception_suppressed(self):
        """Top-level exception in _send_schedule_notification is caught (918-919)."""
        from bot.services.scheduler import _send_schedule_notification

        user = _make_user()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id",
                   AsyncMock(side_effect=RuntimeError("db gone"))):
            await _send_schedule_notification(AsyncMock(), user, {}, {}, {})  # no raise


# ─── reminder_checker_loop exception + _check_and_send_reminders extras ─────


class TestReminderCheckerLoopException:
    def setup_method(self):
        import bot.services.scheduler as sched
        self._saved = sched._running

    def teardown_method(self):
        import bot.services.scheduler as sched
        sched._running = self._saved

    async def test_exception_in_check_is_caught(self):
        """Exception from _check_and_send_reminders is caught (942-948)."""
        import bot.services.scheduler as sched_mod
        from bot.services.scheduler import reminder_checker_loop

        sched_mod._running = True

        async def _stop(*_):
            sched_mod._running = False

        with patch("bot.services.scheduler._check_and_send_reminders",
                   AsyncMock(side_effect=RuntimeError("check error"))), \
             patch("bot.services.scheduler.asyncio.sleep", side_effect=_stop):
            await reminder_checker_loop(AsyncMock())  # no raise


class TestCheckAndSendRemindersMore:
    async def test_passed_anchor_deletes_messages(self):
        """Active anchor that has passed triggers _delete_reminder_messages (962-963)."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        past_anchor = (datetime.now(KYIV_TZ) - timedelta(hours=1)).isoformat()

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors",
                   new_callable=AsyncMock, return_value=[("111222333", past_anchor)]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler._delete_reminder_messages",
                   new_callable=AsyncMock) as mock_delete, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_delete.assert_awaited_once_with(bot_mock, "111222333")

    async def test_user_without_ns_skipped(self):
        """User with notification_settings=None filtered out (994)."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        now = datetime.now(KYIV_TZ)
        next_ev = {"type": "power_off", "time": now.isoformat(), "minutes": 15, "isPossible": False}
        user_no_ns = _make_user(notification_settings=None)

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user_no_ns]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_power_on_notify_remind_on_false_skipped(self):
        """power_on event + notify_remind_on=False → not added to to_send (1006)."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        now = datetime.now(KYIV_TZ)
        next_ev = {"type": "power_on", "time": now.isoformat(), "minutes": 15, "isPossible": False}
        user = _make_user(notification_settings=_make_ns(
            remind_15m=True, notify_remind_off=True, notify_remind_on=False))

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, return_value={"r": "d"}), \
             patch("bot.services.scheduler.parse_schedule_for_queue", return_value=_make_sched()), \
             patch("bot.services.scheduler.find_next_event", return_value=next_ev), \
             patch("bot.services.scheduler.get_active_users_by_region",
                   new_callable=AsyncMock, return_value=[user]), \
             patch("bot.services.scheduler._send_reminder", new_callable=AsyncMock) as mock_send, \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)

        mock_send.assert_not_called()

    async def test_exception_per_pair_is_suppressed(self):
        """Exception during pair processing is caught (1046-1047)."""
        from bot.services.scheduler import _check_and_send_reminders

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler._is_quiet_hours", return_value=False), \
             patch("bot.services.scheduler.get_active_reminder_anchors",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[("kyiv", "1.1")]), \
             patch("bot.services.scheduler.fetch_schedule_data",
                   new_callable=AsyncMock, side_effect=RuntimeError("fetch error")), \
             _patch_async_session(mock_session):
            await _check_and_send_reminders(bot_mock)  # no raise


# ─── _delete_reminder_messages extra exceptions ──────────────────────────────


class TestDeleteReminderMessagesExceptions:
    async def test_bot_delete_exception_suppressed(self):
        """Exception from bot.delete_message for user chat is caught (1073-1074)."""
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        bot.delete_message.side_effect = RuntimeError("tg error")
        mt = SimpleNamespace(last_reminder_message_id=42, last_channel_reminder_message_id=None)
        user = SimpleNamespace(message_tracking=mt, channel_config=None)
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await _delete_reminder_messages(bot, "111")  # no raise

        assert mt.last_reminder_message_id is None

    async def test_string_channel_id_fallback(self):
        """Non-numeric channel_id is used as-is (1082-1083)."""
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        mt = SimpleNamespace(last_reminder_message_id=None, last_channel_reminder_message_id=77)
        cc = SimpleNamespace(channel_id="@mychannel")
        user = SimpleNamespace(message_tracking=mt, channel_config=cc)
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await _delete_reminder_messages(bot, "111")

        bot.delete_message.assert_awaited_once_with("@mychannel", 77)
        assert mt.last_channel_reminder_message_id is None

    async def test_channel_delete_exception_suppressed(self):
        """Exception from bot.delete_message for channel is caught (1085-1086)."""
        from bot.services.scheduler import _delete_reminder_messages

        bot = AsyncMock()
        bot.delete_message.side_effect = RuntimeError("ch error")
        mt = SimpleNamespace(last_reminder_message_id=None, last_channel_reminder_message_id=77)
        cc = SimpleNamespace(channel_id="-100555")
        user = SimpleNamespace(message_tracking=mt, channel_config=cc)
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await _delete_reminder_messages(bot, "111")  # no raise

        assert mt.last_channel_reminder_message_id is None


# ─── _build_reminder_text — power_off with next outage ──────────────────────


class TestBuildReminderTextMore:
    def test_power_off_with_next_outage_shows_next_outage_time(self):
        """power_off + next outage after end_dt → context line includes outage time (1147-1150)."""
        from bot.services.scheduler import _build_reminder_text

        ev = {
            "type": "power_off",
            "time": "2026-04-07T10:00:00",
            "endTime": "2026-04-07T12:00:00",
            "minutes": 15,
        }
        events = [{"start": "2026-04-07T16:00:00", "end": "2026-04-07T18:00:00",
                   "isPossible": False}]
        text = _build_reminder_text(ev, 15, _make_sched(events=events), "kyiv", "1.1",
                                    is_possible=False)
        assert "Наступне відключення о 16:00" in text


# ─── _send_reminder extra branches ──────────────────────────────────────────


class TestSendReminderMore:
    async def test_bot_send_exception_suppressed(self):
        """General exception from bot send is caught (1231-1232)."""
        from bot.services.scheduler import _send_reminder

        user = _make_user()
        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call",
                   AsyncMock(side_effect=RuntimeError("net"))):
            result = await _send_reminder(
                AsyncMock(), user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False, user.notification_settings, None,
            )

        assert result is False

    async def test_channel_string_channel_id_fallback(self):
        """Non-numeric channel_id is used as-is for channel send (1239-1240)."""
        from bot.services.scheduler import _send_reminder

        bot = AsyncMock()
        bot_msg = MagicMock(); bot_msg.message_id = 11
        ch_msg = MagicMock(); ch_msg.message_id = 22
        bot.send_message.side_effect = [bot_msg, ch_msg]

        user = _make_user()
        cc = SimpleNamespace(
            channel_id="@mychannel",
            channel_status="active", channel_paused=False,
            ch_notify_remind_off=True, ch_notify_remind_on=True,
            ch_remind_15m=True, ch_remind_30m=False, ch_remind_1h=False,
        )
        mock_session = _make_mock_session()
        db_user = _make_user()

        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=db_user)):
            result = await _send_reminder(
                bot, user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False, user.notification_settings, cc,
            )

        assert result is True
        assert bot.send_message.await_args_list[1].args[0] == "@mychannel"

    async def test_channel_forbidden_suppressed(self):
        """TelegramForbiddenError from channel send caught silently (1246-1247)."""
        from bot.services.scheduler import _send_reminder

        bot = AsyncMock()
        bot_msg = MagicMock(); bot_msg.message_id = 11
        call_count = [0]

        async def _send_or_forbidden(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return bot_msg
            raise _make_telegram_forbidden()

        bot.send_message = _send_or_forbidden
        user = _make_user()
        cc = SimpleNamespace(
            channel_id="-100555",
            channel_status="active", channel_paused=False,
            ch_notify_remind_off=True, ch_notify_remind_on=True,
            ch_remind_15m=True, ch_remind_30m=False, ch_remind_1h=False,
        )
        mock_session = _make_mock_session()
        db_user = _make_user()

        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=db_user)):
            result = await _send_reminder(
                bot, user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False, user.notification_settings, cc,
            )

        assert result is True  # bot message sent ok

    async def test_channel_exception_suppressed(self):
        """General exception from channel send caught (1248-1249)."""
        from bot.services.scheduler import _send_reminder

        bot = AsyncMock()
        bot_msg = MagicMock(); bot_msg.message_id = 11
        call_count = [0]

        async def _send_or_error(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return bot_msg
            raise RuntimeError("channel net error")

        bot.send_message = _send_or_error
        user = _make_user()
        cc = SimpleNamespace(
            channel_id="-100555",
            channel_status="active", channel_paused=False,
            ch_notify_remind_off=True, ch_notify_remind_on=True,
            ch_remind_15m=True, ch_remind_30m=False, ch_remind_1h=False,
        )
        mock_session = _make_mock_session()
        db_user = _make_user()

        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id", AsyncMock(return_value=db_user)):
            result = await _send_reminder(
                bot, user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False, user.notification_settings, cc,
            )

        assert result is True

    async def test_save_ids_exception_suppressed(self):
        """Exception when saving reminder message IDs is caught (1261-1262)."""
        from bot.services.scheduler import _send_reminder

        bot = AsyncMock()
        mock_msg = MagicMock(); mock_msg.message_id = 11
        bot.send_message.return_value = mock_msg
        user = _make_user()
        mock_session = _make_mock_session()

        with patch("bot.services.scheduler._delete_reminder_messages", AsyncMock()), \
             patch("bot.services.scheduler._build_reminder_text", return_value="text"), \
             patch("bot.services.scheduler.get_reminder_keyboard", return_value=MagicMock()), \
             patch("bot.services.scheduler.retry_bot_call", side_effect=_fake_retry_bot_call), \
             _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_user_by_telegram_id",
                   AsyncMock(side_effect=RuntimeError("db error"))):
            result = await _send_reminder(
                bot, user,
                {"type": "power_off", "time": "2026-04-07T10:00:00", "minutes": 15},
                15, _make_sched(), "kyiv", "1.1", False, user.notification_settings, None,
            )

        assert result is True  # message sent even though ID save failed


# ─── Covering last missing lines ─────────────────────────────────────────────


class TestCheckSingleQueueTomorrowMerge(TestCheckSingleQueueBranches):
    """Covers lines 342-345: tomorrow added events merged into changes."""

    async def test_snapshot_tomorrow_updated_merges_added_events(self):
        """tomorrowUpdated + added tomorrow events merged into changes dict (342-345)."""
        from contextlib import ExitStack
        from bot.services.scheduler import _check_single_queue

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        snapshot_mock = SimpleNamespace(today_hash=None, tomorrow_hash="old_tmrw",
                                        schedule_data=json.dumps({"events": []}))
        sched, patches = self._base_patches(stored_hash="old_hash", snapshot=snapshot_mock, quiet=True)

        with ExitStack() as stack:
            stack.enter_context(_patch_async_session(mock_session))
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(patch("bot.services.scheduler._compute_date_hash",
                                      side_effect=[None, "new_tmrw"]))
            # _compute_changes called once (for tomorrow); return non-empty added list
            stack.enter_context(patch("bot.services.scheduler._compute_changes",
                                      return_value={"added": [{"start": "t1", "end": "t2"}],
                                                    "removed": []}))
            save_mock = stack.enter_context(
                patch("bot.services.scheduler.save_pending_notification", new_callable=AsyncMock))
            result = await _check_single_queue(bot_mock, "kyiv", "1.1")

        assert result is True
        ut = json.loads(save_mock.await_args[0][4])
        assert ut.get("tomorrowUpdated") is True


class TestFlushPendingNotificationsPurgeExceptions:
    async def test_purge_notifications_exception_suppressed(self):
        """Exception from delete_old_pending_notifications is caught (518-519)."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_all_pending_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.delete_old_pending_notifications",
                   new_callable=AsyncMock, side_effect=RuntimeError("db gone")), \
             patch("bot.services.scheduler.cleanup_old_reminders",
                   new_callable=AsyncMock, return_value=0):
            await flush_pending_notifications(bot_mock)  # no raise

    async def test_purge_reminders_exception_suppressed(self):
        """Exception from cleanup_old_reminders is caught (528-529)."""
        from bot.services.scheduler import flush_pending_notifications

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_async_session(mock_session), \
             patch("bot.services.scheduler.get_all_pending_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.get_distinct_region_queue_pairs",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.scheduler.delete_old_pending_notifications",
                   new_callable=AsyncMock, return_value=0), \
             patch("bot.services.scheduler.cleanup_old_reminders",
                   new_callable=AsyncMock, side_effect=RuntimeError("reminders db gone")):
            await flush_pending_notifications(bot_mock)  # no raise
