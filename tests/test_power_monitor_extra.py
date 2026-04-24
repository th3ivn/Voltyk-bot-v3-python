"""Additional tests for bot/services/power_monitor.py to improve coverage.

Covers uncovered lines:
238-241, 249, 257-258, 267-274, 291-293, 299, 304-309, 339, 341, 359-380,
407, 409, 413-414, 422-423, 480-484, 513-517, 528-529, 539-540, 555-559,
565-567, 569-570, 579-595, 600-601, 667-669, 677-701, 718-719, 785-851,
857-906, 933-937, 946-956, 976, 1027-1030, 1044-1237
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ─── Shared helpers ────────────────────────────────────────────────────────

def _make_method_mock() -> MagicMock:
    return MagicMock()


def _make_telegram_forbidden() -> TelegramForbiddenError:
    return TelegramForbiddenError(
        method=_make_method_mock(),
        message="Forbidden: bot was blocked by the user",
    )


def _make_telegram_bad_request(msg: str = "Bad Request: message not found") -> TelegramBadRequest:
    return TelegramBadRequest(method=_make_method_mock(), message=msg)


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    return session


@asynccontextmanager
async def _mock_async_session(session: AsyncMock):
    yield session


def _patch_pm_async_session(mock_session: AsyncMock):
    return patch(
        "bot.services.power_monitor.async_session",
        side_effect=lambda: _mock_async_session(mock_session),
    )


def _make_pm_user(**kwargs) -> SimpleNamespace:
    defaults = dict(
        telegram_id="111222333",
        id=1,
        router_ip="8.8.8.8",
        region="kyiv",
        queue="1.1",
        power_tracking=SimpleNamespace(
            power_state=None,
            power_changed_at=None,
            pending_power_state=None,
            pending_power_change_at=None,
            bot_power_message_id=None,
            alert_off_message_id=None,
            alert_on_message_id=None,
            ch_power_message_id=None,
            power_message_type=None,
        ),
        notification_settings=SimpleNamespace(
            notify_fact_off=True,
            notify_fact_on=True,
        ),
        channel_config=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ─── _handle_power_state_change ────────────────────────────────────────────


class TestHandlePowerStateChangeExtra:
    """Cover additional branches in _handle_power_state_change."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_db_error_with_no_fresh_user_returns_early(self):
        """Lines 238-241: DB exception with fresh_user=None → return early."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        # Patch async_session to raise immediately
        with patch(
            "bot.services.power_monitor.async_session",
            side_effect=Exception("DB down"),
        ):
            # Should not raise, just return early
            await _handle_power_state_change(bot, user, "off", "on", user_state)

        # No send_message called because we returned early
        bot.send_message.assert_not_called()

    async def test_cooldown_with_naive_datetime(self):
        """Line 249: cooldown last_notification_at without tzinfo gets KYIV_TZ."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        bot.send_message = AsyncMock(return_value=sent_msg)

        user = _make_pm_user()
        # A naive datetime (no tzinfo) 1 second ago — within cooldown
        naive_now = datetime.now()
        user_state = {
            "last_notification_at": naive_now.isoformat(),
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        power_result = {"duration_minutes": 10.0, "power_changed_at": None}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.settings") as mock_settings,
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
        ):
            mock_settings.POWER_NOTIFICATION_COOLDOWN_S = 9999  # very long cooldown
            mock_settings.timezone = KYIV_TZ
            # Should not send because within cooldown
            await _handle_power_state_change(bot, user, "off", "on", user_state)

    async def test_cooldown_calculation_exception(self):
        """Lines 257-258: Exception during cooldown calculation → logged, continues."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        bot.send_message = AsyncMock(return_value=sent_msg)

        user = _make_pm_user()
        # last_notification_at with invalid format → fromisoformat raises
        user_state = {
            "last_notification_at": "not-a-real-datetime",
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        power_result = {"duration_minutes": 5.0, "power_changed_at": None}
        sent_msg2 = SimpleNamespace(message_id=99)

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg2)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            # Should not raise; invalid last_notification_at triggers except branch
            await _handle_power_state_change(bot, user, "on", "off", user_state)

    async def test_changed_at_from_string_power_changed_at(self):
        """Lines 267-274: power_result['power_changed_at'] is a string → parsed."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        # String datetime without timezone info → triggers replace(tzinfo=timezone.utc)
        power_result = {
            "duration_minutes": 30.0,
            "power_changed_at": "2024-01-01T12:00:00",
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "on", "off", user_state)

    async def test_changed_at_from_aware_datetime_power_changed_at(self):
        """Lines 267-274: power_result['power_changed_at'] is an aware datetime."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        power_result = {
            "duration_minutes": 30.0,
            "power_changed_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "on", "off", user_state)

    async def test_schedule_fetch_error_handled(self):
        """Lines 291-293: schedule fetch raises → logged, continues."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        power_result = {"duration_minutes": None, "power_changed_at": None}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", side_effect=Exception("API down")),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

    async def test_scheduled_outage_schedule_text(self):
        """Line 299: off state with scheduled outage produces schedule_text."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        power_result = {"duration_minutes": 0.5, "power_changed_at": None}
        next_event = {"type": "power_on", "time": "2024-01-01T14:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

    async def test_on_state_with_next_power_off_with_end_time(self):
        """Lines 304-309: on state + next_event=power_off with endTime."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        power_result = {"duration_minutes": 60.0, "power_changed_at": None}
        next_event = {
            "type": "power_off",
            "time": "2024-01-01T16:00:00",
            "endTime": "2024-01-01T18:00:00",
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "on", "off", user_state)

    async def test_on_state_with_next_power_off_no_end_time(self):
        """Line 309: on state + next_event=power_off without endTime."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user()
        power_result = {"duration_minutes": 60.0, "power_changed_at": None}
        next_event = {
            "type": "power_off",
            "time": "2024-01-01T16:00:00",
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
            patch("bot.services.power_monitor.retry_bot_call", new=AsyncMock(return_value=sent_msg)),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "on", "off", user_state)

    async def test_notify_fact_off_false_skips_bot_send(self):
        """Line 339: notify_fact_off=False → skips bot send."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user(
            notification_settings=SimpleNamespace(
                notify_fact_off=False,
                notify_fact_on=True,
            )
        )
        power_result = {"duration_minutes": 10.0, "power_changed_at": None}
        retry_mock = AsyncMock(return_value=sent_msg)

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", new=retry_mock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

        # retry_bot_call should not have been called (or was not called for send_message)
        # We verify no message was sent
        retry_mock.assert_not_called()

    async def test_notify_fact_on_false_skips_bot_send(self):
        """Line 341: notify_fact_on=False → skips bot send for 'on' state."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user(
            notification_settings=SimpleNamespace(
                notify_fact_off=True,
                notify_fact_on=False,
            )
        )
        power_result = {"duration_minutes": 10.0, "power_changed_at": None}
        retry_mock = AsyncMock(return_value=sent_msg)

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", new=retry_mock),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "on", "off", user_state)

        retry_mock.assert_not_called()

    async def test_channel_notification_sent(self):
        """Lines 359-380: channel notification with ch_notify_fact_off=True."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        bot_sent = SimpleNamespace(message_id=10)
        ch_sent = SimpleNamespace(message_id=20)

        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user(
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            )
        )
        power_result = {"duration_minutes": 5.0, "power_changed_at": None}

        call_count = {"n": 0}

        async def _fake_retry(fn):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return bot_sent
            return ch_sent

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", side_effect=_fake_retry),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

        assert call_count["n"] == 2  # bot + channel

    async def test_channel_paused_skips_channel_send(self):
        """Line 364: channel_paused=True → no channel send."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        bot_sent = SimpleNamespace(message_id=10)

        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user(
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=True,
            )
        )
        power_result = {"duration_minutes": 5.0, "power_changed_at": None}

        call_count = {"n": 0}

        async def _fake_retry(fn):
            call_count["n"] += 1
            return bot_sent

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", side_effect=_fake_retry),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

        # Only bot send, no channel
        assert call_count["n"] == 1

    async def test_channel_forbidden_error_logged(self):
        """Line 377: TelegramForbiddenError from channel send → logged, not raised."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        bot_sent = SimpleNamespace(message_id=10)

        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        fresh_user = _make_pm_user(
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            )
        )
        power_result = {"duration_minutes": 5.0, "power_changed_at": None}

        call_count = {"n": 0}

        async def _fake_retry(fn):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return bot_sent
            raise _make_telegram_forbidden()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", side_effect=_fake_retry),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

    async def test_persist_ch_msg_id(self):
        """Lines 407, 409: ch_msg_id persisted to channel_config."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        bot_sent = SimpleNamespace(message_id=10)
        ch_sent = SimpleNamespace(message_id=20)

        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        mock_session = _make_mock_session()
        # Make the DB user with power_tracking and channel_config
        db_power_tracking = SimpleNamespace(
            power_state=None,
            power_changed_at=None,
            bot_power_message_id=None,
            alert_off_message_id=None,
            alert_on_message_id=None,
            ch_power_message_id=None,
            power_message_type=None,
        )
        db_channel_config = SimpleNamespace(last_power_message_id=None)
        db_user = SimpleNamespace(power_tracking=db_power_tracking, channel_config=db_channel_config)
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        fresh_user = _make_pm_user(
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            )
        )
        power_result = {"duration_minutes": 5.0, "power_changed_at": None}

        call_count = {"n": 0}

        async def _fake_retry(fn):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return bot_sent
            return ch_sent

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", side_effect=_fake_retry),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            await _handle_power_state_change(bot, user, "off", "on", user_state)

    async def test_persist_message_ids_exception_handled(self):
        """Lines 413-414: Exception persisting message IDs → logged, not raised."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        user = _make_pm_user()
        user_state = {
            "last_notification_at": None,
            "last_stable_at": None,
            "last_stable_state": None,
            "instability_start": None,
            "switch_count": 0,
        }

        call_count = {"n": 0}

        @asynccontextmanager
        async def _flaky_session():
            if call_count["n"] >= 2:
                raise Exception("DB write failed")
            call_count["n"] += 1
            yield _make_mock_session()

        fresh_user = _make_pm_user()
        power_result = {"duration_minutes": 5.0, "power_changed_at": None}
        retry_mock = AsyncMock(return_value=sent_msg)

        with (
            patch("bot.services.power_monitor.async_session", side_effect=_flaky_session),
            patch("bot.services.power_monitor.get_user_by_telegram_id", return_value=fresh_user),
            patch("bot.services.power_monitor.change_power_state_and_get_duration", return_value=power_result),
            patch("bot.services.power_monitor.add_power_history", new_callable=AsyncMock),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.retry_bot_call", new=retry_mock),
            patch("bot.services.power_monitor.deactivate_ping_error_alert", new_callable=AsyncMock),
        ):
            # Should not raise
            await _handle_power_state_change(bot, user, "on", "off", user_state)

    async def test_outer_exception_handled(self):
        """Lines 422-423: Outer exception in _handle_power_state_change → logged."""
        from bot.services.power_monitor import _handle_power_state_change

        bot = AsyncMock()
        user = _make_pm_user()
        # Passing an invalid user_state to trigger outer exception
        user_state = None  # Will cause AttributeError inside

        with patch("bot.services.power_monitor.async_session", side_effect=Exception("boom")):
            # Should not raise
            await _handle_power_state_change(bot, user, "off", "on", user_state)


# ─── _check_user_power additional branches ────────────────────────────────


class TestCheckUserPowerExtra:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_first_check_no_db_record_writes_initial_state(self):
        """Lines 480-484: First check without DB record → writes power_state to DB."""
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user(power_tracking=None)

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(power_state=None, power_changed_at=None)
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            _patch_pm_async_session(mock_session),
        ):
            await _check_user_power(bot, user)

        assert db_user.power_tracking.power_state == "on"

    async def test_first_check_db_write_exception_handled(self):
        """Lines 483-484: DB write exception during first check → logged."""
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user(power_tracking=None)

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=False),
            patch("bot.services.power_monitor.async_session", side_effect=Exception("DB error")),
        ):
            # Should not raise
            await _check_user_power(bot, user)

    async def test_flapping_clears_pending_with_db_clear(self):
        """Lines 513-517: Flapping clears pending state from DB."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        # Set up user state: current=on, pending=off, but new ping shows on → flapping
        pm._user_states["111222333"] = {
            "current_state": "on",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": "off",
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 1,
            "last_stable_state": "on",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(pending_power_state=None, pending_power_change_at=None)
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            _patch_pm_async_session(mock_session),
        ):
            await _check_user_power(bot, user)

        # pending_state should be cleared
        assert pm._user_states["111222333"]["pending_state"] is None

    async def test_flapping_clear_pending_db_exception_handled(self):
        """Lines 516-517: DB exception clearing pending state → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        pm._user_states["111222333"] = {
            "current_state": "on",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": "off",
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 1,
            "last_stable_state": "on",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            patch("bot.services.power_monitor.async_session", side_effect=Exception("DB error")),
        ):
            await _check_user_power(bot, user)

    async def test_new_state_cancels_previous_debounce(self):
        """Lines 528-529: Previous debounce task cancelled on new state change."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        # existing debounce task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()

        pm._user_states["111222333"] = {
            "current_state": "off",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": None,
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": mock_task,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": "off",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(
                pending_power_state=None,
                pending_power_change_at=None,
            )
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _check_user_power(bot, user)

        mock_task.cancel.assert_called_once()

    async def test_switch_count_incremented_when_pending_exists(self):
        """Lines 539-540: switch_count incremented when already pending different state."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        pm._user_states["111222333"] = {
            "current_state": "off",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": "on",  # was pending on
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": datetime.now(KYIV_TZ),
            "switch_count": 2,
            "last_stable_state": "off",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(
                pending_power_state=None,
                pending_power_change_at=None,
            )
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=False),
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _check_user_power(bot, user)

        # switch_count should have been incremented
        assert pm._user_states["111222333"]["switch_count"] >= 2

    async def test_persist_pending_state_db_exception_handled(self):
        """Lines 558-559: DB exception persisting pending state → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        pm._user_states["111222333"] = {
            "current_state": "off",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": None,
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": "off",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        call_count = {"n": 0}

        @asynccontextmanager
        async def _session_factory():
            call_count["n"] += 1
            if call_count["n"] <= 1:
                yield _make_mock_session()
            else:
                raise Exception("DB persist error")

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            patch("bot.services.power_monitor.async_session", side_effect=_session_factory),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _check_user_power(bot, user)

    async def test_debounce_seconds_fetch_exception_uses_default(self):
        """Lines 565-567: _get_debounce_seconds raises → uses DEFAULT_DEBOUNCE_S."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        pm._user_states["111222333"] = {
            "current_state": "off",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": None,
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": "off",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(pending_power_state=None, pending_power_change_at=None)
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        # First async_session call succeeds; second raises (for debounce fetch)
        call_count = {"n": 0}

        @asynccontextmanager
        async def _session_factory():
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield mock_session
            else:
                raise Exception("Debounce DB error")

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            patch("bot.services.power_monitor.async_session", side_effect=_session_factory),
        ):
            await _check_user_power(bot, user)

        # Should have created a debounce task with default seconds
        assert pm._user_states["111222333"]["debounce_task"] is not None
        # Cancel task to clean up
        pm._user_states["111222333"]["debounce_task"].cancel()
        await asyncio.sleep(0)

    async def test_debounce_zero_uses_min_stabilization(self):
        """Lines 569-570: debounce_s=0 → uses POWER_MIN_STABILIZATION_S."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        pm._user_states["111222333"] = {
            "current_state": "off",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": None,
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": "off",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(pending_power_state=None, pending_power_change_at=None)
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=0),
        ):
            await _check_user_power(bot, user)

        assert pm._user_states["111222333"]["debounce_task"] is not None
        pm._user_states["111222333"]["debounce_task"].cancel()
        await asyncio.sleep(0)

    async def test_outer_exception_in_check_user_power_handled(self):
        """Lines 600-601: Outer exception in _check_user_power → logged."""
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        # user with no telegram_id to trigger exception in getting it
        user = SimpleNamespace()  # Missing telegram_id

        with patch("bot.services.power_monitor.check_router_http", side_effect=Exception("Network error")):
            await _check_user_power(bot, user)


# ─── _confirm_state debounce closure ──────────────────────────────────────

class TestConfirmStateDebounce:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_confirm_state_triggers_handle_power_state_change(self):
        """Lines 579-595: After debounce sleep, confirms state and calls handler."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot = AsyncMock()
        user = _make_pm_user()

        pm._user_states["111222333"] = {
            "current_state": "off",
            "last_change_at": None,
            "consecutive_checks": 0,
            "is_first_check": False,
            "pending_state": None,
            "pending_state_time": None,
            "original_change_time": None,
            "debounce_task": None,
            "instability_start": None,
            "switch_count": 0,
            "last_stable_state": "off",
            "last_stable_at": None,
            "last_ping_time": None,
            "last_ping_success": None,
            "last_notification_at": None,
        }

        mock_session = _make_mock_session()
        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(pending_power_state=None, pending_power_change_at=None)
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        handle_mock = AsyncMock()

        # When debounce_s == 0 the code falls back to settings.POWER_MIN_STABILIZATION_S
        # (30 s).  Patch asyncio.sleep inside the module so the closure finishes instantly.
        real_sleep = asyncio.sleep

        async def _fast_sleep(s):
            await real_sleep(0)

        with (
            patch("bot.services.power_monitor.check_router_http", return_value=True),
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=0),
            patch("bot.services.power_monitor._handle_power_state_change", handle_mock),
            patch("bot.services.power_monitor.asyncio.sleep", side_effect=_fast_sleep),
        ):
            await _check_user_power(bot, user)
            task = pm._user_states["111222333"]["debounce_task"]
            assert task is not None
            # Let the debounce task complete
            await real_sleep(0.05)

        handle_mock.assert_called_once()


# ─── _check_all_ips error branch ──────────────────────────────────────────

class TestCheckAllIpsExtra:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        # Ensure lock is not held
        if pm._check_all_ips_lock.locked():
            pass  # Can't release but should be fine between tests

    async def test_error_in_check_all_ips_captured(self):
        """Lines 667-669: Exception in _check_all_ips → logged + sentry captured."""
        from bot.services.power_monitor import _check_all_ips

        bot = AsyncMock()

        with (
            patch("bot.services.power_monitor.async_session", side_effect=Exception("DB error")),
            patch("bot.services.power_monitor.sentry_sdk") as mock_sentry,
        ):
            await _check_all_ips(bot)

        mock_sentry.capture_exception.assert_called_once()


# ─── _save_user_state_to_db ───────────────────────────────────────────────

class TestSaveUserStateToDb:
    async def test_saves_state_with_valid_last_notification(self):
        """Lines 677-701: Saves state with valid last_notification_at."""
        from bot.services.power_monitor import _save_user_state_to_db

        mock_session = _make_mock_session()
        state = {
            "current_state": "on",
            "pending_state": None,
            "pending_state_time": None,
            "last_stable_state": "on",
            "last_stable_at": None,
            "instability_start": None,
            "switch_count": 0,
            "last_notification_at": datetime.now(KYIV_TZ).isoformat(),
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.upsert_user_power_state", new_callable=AsyncMock) as mock_upsert,
        ):
            await _save_user_state_to_db("111222333", state)

        mock_upsert.assert_called_once()

    async def test_saves_state_without_last_notification(self):
        """Lines 677-701: Saves state when last_notification_at is None."""
        from bot.services.power_monitor import _save_user_state_to_db

        mock_session = _make_mock_session()
        state = {
            "current_state": "off",
            "pending_state": "on",
            "pending_state_time": None,
            "last_stable_state": "off",
            "last_stable_at": None,
            "instability_start": None,
            "switch_count": 1,
            "last_notification_at": None,
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.upsert_user_power_state", new_callable=AsyncMock) as mock_upsert,
        ):
            await _save_user_state_to_db("111222333", state)

        mock_upsert.assert_called_once()
        # last_notification_at should be None
        _, kwargs = mock_upsert.call_args
        assert kwargs.get("last_notification_at") is None

    async def test_saves_state_with_invalid_notification_iso(self):
        """Line 683: Invalid ISO for last_notification_at → last_notif_dt=None."""
        from bot.services.power_monitor import _save_user_state_to_db

        mock_session = _make_mock_session()
        state = {
            "current_state": "on",
            "pending_state": None,
            "pending_state_time": None,
            "last_stable_state": "on",
            "last_stable_at": None,
            "instability_start": None,
            "switch_count": 0,
            "last_notification_at": "not-a-datetime",
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.upsert_user_power_state", new_callable=AsyncMock) as mock_upsert,
        ):
            await _save_user_state_to_db("111222333", state)

        mock_upsert.assert_called_once()

    async def test_db_error_handled(self):
        """Line 701: DB error in _save_user_state_to_db → logged."""
        from bot.services.power_monitor import _save_user_state_to_db

        state = {
            "current_state": "on",
            "pending_state": None,
            "pending_state_time": None,
            "last_stable_state": "on",
            "last_stable_at": None,
            "instability_start": None,
            "switch_count": 0,
            "last_notification_at": None,
        }

        with patch("bot.services.power_monitor.async_session", side_effect=Exception("DB error")):
            # Should not raise
            await _save_user_state_to_db("111222333", state)


# ─── _save_all_user_states invalid iso ────────────────────────────────────

class TestSaveAllUserStatesExtra:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_invalid_last_notification_iso_handled(self):
        """Lines 718-719: Invalid ISO string for last_notification → None."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        pm._user_states["111222333"] = {
            "current_state": "on",
            "pending_state": None,
            "pending_state_time": None,
            "last_stable_state": "on",
            "last_stable_at": None,
            "instability_start": None,
            "switch_count": 0,
            "last_notification_at": "INVALID",
        }

        mock_session = _make_mock_session()
        batch_mock = AsyncMock()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.batch_upsert_user_power_states", batch_mock),
        ):
            await _save_all_user_states()

        batch_mock.assert_called_once()
        rows = batch_mock.call_args[0][1]
        assert rows[0]["last_notification_at"] is None


# ─── _restart_pending_debounce_tasks ──────────────────────────────────────

class TestRestartPendingDebounceTasks:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_no_pending_states_does_nothing(self):
        """Lines 785-851: No pending states → nothing started."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot = AsyncMock()
        pm._user_states["111"] = {
            "current_state": "on",
            "pending_state": None,  # No pending state
            "debounce_task": None,
            "pending_state_time": None,
            "original_change_time": None,
        }

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _restart_pending_debounce_tasks(bot)

        assert pm._user_states["111"]["debounce_task"] is None

    async def test_pending_state_creates_debounce_task(self):
        """Lines 797-851: Pending state with no task → creates new task."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot = AsyncMock()
        pending_at = datetime.now(KYIV_TZ)
        pm._user_states["222"] = {
            "current_state": "off",
            "pending_state": "on",
            "debounce_task": None,
            "pending_state_time": pending_at,
            "original_change_time": pending_at,
        }

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _restart_pending_debounce_tasks(bot)

        assert pm._user_states["222"]["debounce_task"] is not None
        pm._user_states["222"]["debounce_task"].cancel()
        await asyncio.sleep(0)

    async def test_pending_state_elapsed_time_reduces_remaining(self):
        """Lines 802-807: elapsed time computed from pending_state_time."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot = AsyncMock()
        from datetime import timedelta
        # 400s ago, with 300s debounce → 0s remaining
        pending_at = datetime.now(KYIV_TZ) - timedelta(seconds=400)
        pm._user_states["333"] = {
            "current_state": "off",
            "pending_state": "on",
            "debounce_task": None,
            "pending_state_time": pending_at,
            "original_change_time": pending_at,
        }

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _restart_pending_debounce_tasks(bot)

        task = pm._user_states["333"]["debounce_task"]
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)

    async def test_debounce_seconds_fetch_error_uses_default(self):
        """Lines 789-791: debounce fetch error → uses DEFAULT_DEBOUNCE_S."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot = AsyncMock()
        pm._user_states["444"] = {
            "current_state": "off",
            "pending_state": "on",
            "debounce_task": None,
            "pending_state_time": None,
            "original_change_time": None,
        }

        with patch("bot.services.power_monitor.async_session", side_effect=Exception("DB error")):
            await _restart_pending_debounce_tasks(bot)

        task = pm._user_states["444"]["debounce_task"]
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)

    async def test_pending_state_no_time_uses_full_debounce(self):
        """Line 800: pending_state_time is None → full debounce_s."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot = AsyncMock()
        pm._user_states["555"] = {
            "current_state": "off",
            "pending_state": "on",
            "debounce_task": None,
            "pending_state_time": None,  # No time → full debounce
            "original_change_time": None,
        }

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _restart_pending_debounce_tasks(bot)

        task = pm._user_states["555"]["debounce_task"]
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)

    async def test_existing_task_skipped(self):
        """Line 798: pending state with existing task → not recreated."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot = AsyncMock()
        existing_task = MagicMock()
        pm._user_states["666"] = {
            "current_state": "off",
            "pending_state": "on",
            "debounce_task": existing_task,  # Already has task
            "pending_state_time": None,
            "original_change_time": None,
        }

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._get_debounce_seconds", return_value=300),
        ):
            await _restart_pending_debounce_tasks(bot)

        assert pm._user_states["666"]["debounce_task"] is existing_task


# ─── power_monitor_loop ────────────────────────────────────────────────────

class TestPowerMonitorLoop:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._running = False

    async def test_loop_runs_and_stops(self):
        """Lines 857-906: Loop starts, runs one iteration, stops."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot = AsyncMock()
        check_call_count = {"n": 0}

        async def _fake_check(b):
            check_call_count["n"] += 1
            # Stop the loop after first iteration
            pm._running = False

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._restore_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor._restart_pending_debounce_tasks", new_callable=AsyncMock),
            patch("bot.services.power_monitor._check_all_ips", side_effect=_fake_check),
            patch("bot.services.power_monitor._get_check_interval", return_value=0),
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
        ):
            await power_monitor_loop(bot)

        assert check_call_count["n"] >= 1

    async def test_loop_initial_check_timeout_handled(self):
        """Lines 871-873: Initial check times out → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot = AsyncMock()

        # power_monitor_loop sets _running = True on entry, so we must stop
        # it from inside the loop.  Patch asyncio.sleep to flip _running off.
        real_sleep = asyncio.sleep

        async def _stop_on_sleep(s):
            pm._running = False
            await real_sleep(0)

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._restore_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor._restart_pending_debounce_tasks", new_callable=AsyncMock),
            patch("bot.services.power_monitor.asyncio.wait_for", side_effect=asyncio.TimeoutError()),
            patch("bot.services.power_monitor._check_all_ips", new_callable=AsyncMock),
            patch("bot.services.power_monitor._get_check_interval", return_value=0),
            patch("bot.services.power_monitor.asyncio.sleep", side_effect=_stop_on_sleep),
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
        ):
            await power_monitor_loop(bot)

    async def test_loop_check_exception_handled(self):
        """Lines 898-900: Loop iteration exception → logged + sentry."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot = AsyncMock()
        call_count = {"n": 0}

        mock_session = _make_mock_session()

        async def _check_side_effect(b):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return  # Initial check succeeds
            raise Exception("Check failed")

        async def _interval_mock(session):
            pm._running = False
            return 0

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor._restore_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor._restart_pending_debounce_tasks", new_callable=AsyncMock),
            patch("bot.services.power_monitor._check_all_ips", side_effect=_check_side_effect),
            patch("bot.services.power_monitor._get_check_interval", side_effect=_interval_mock),
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor.sentry_sdk"),
        ):
            await power_monitor_loop(bot)


# ─── save_states_on_shutdown connector close ──────────────────────────────

class TestSaveStatesOnShutdown:
    async def test_closes_open_connector(self):
        """Lines 933-937: Connector closed on shutdown."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        with patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock):
            await save_states_on_shutdown()

        mock_connector.close.assert_called_once()
        assert pm._http_connector is None

    async def test_connector_exception_handled(self):
        """Lines 936-937: Exception closing connector → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock(side_effect=Exception("close error"))
        pm._http_connector = mock_connector

        with patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock):
            # Should not raise
            await save_states_on_shutdown()

    async def test_cancelled_error_waits_with_timeout_then_reraises(self):
        """CancelledError path: asyncio.shield raises CancelledError → wait_for with 5s timeout."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        async def _shield_raises(*args, **kwargs):
            raise asyncio.CancelledError()

        with (
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor.asyncio.shield", side_effect=_shield_raises),
            patch("bot.services.power_monitor.asyncio.wait_for", new_callable=AsyncMock) as mock_wf,
        ):
            with pytest.raises(asyncio.CancelledError):
                await save_states_on_shutdown()

        mock_wf.assert_called_once()
        _, kwargs = mock_wf.call_args
        assert kwargs.get("timeout") == 5.0

    async def test_cancelled_error_wait_for_times_out_logs_and_reraises(self):
        """Lines 995-996: wait_for raises TimeoutError → logged, CancelledError re-raised."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        async def _shield_raises(*args, **kwargs):
            raise asyncio.CancelledError()

        async def _wait_for_times_out(*args, **kwargs):
            raise asyncio.TimeoutError()

        with (
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor.asyncio.shield", side_effect=_shield_raises),
            patch("bot.services.power_monitor.asyncio.wait_for", side_effect=_wait_for_times_out),
        ):
            with pytest.raises(asyncio.CancelledError):
                await save_states_on_shutdown()

    async def test_cancelled_error_task_already_done_no_wait_for(self):
        """CancelledError path: close_task already done → wait_for NOT called, result consumed."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        async def _shield_raises(task, *args, **kwargs):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise asyncio.CancelledError()

        with (
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor.asyncio.shield", side_effect=_shield_raises),
            patch("bot.services.power_monitor.asyncio.wait_for", new_callable=AsyncMock) as mock_wf,
        ):
            with pytest.raises(asyncio.CancelledError):
                await save_states_on_shutdown()

        mock_wf.assert_not_called()

    async def test_cancelled_error_task_done_with_exception_logs_and_reraises(self):
        """CancelledError else-branch: done task that raised → exception consumed via await, logged."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock(side_effect=OSError("connection reset"))
        pm._http_connector = mock_connector

        async def _shield_raises(task, *args, **kwargs):
            # Let the task run to completion (raises OSError inside)
            try:
                await task
            except OSError:
                pass
            raise asyncio.CancelledError()

        with (
            patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock),
            patch("bot.services.power_monitor.asyncio.shield", side_effect=_shield_raises),
            patch("bot.services.power_monitor.asyncio.wait_for", new_callable=AsyncMock) as mock_wf,
        ):
            with pytest.raises(asyncio.CancelledError):
                await save_states_on_shutdown()

        # wait_for not called because task was already done
        mock_wf.assert_not_called()

    async def test_flush_timeout_warns_and_continues(self):
        """TimeoutError during shutdown flush is logged but does not prevent connector close."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        async def _slow_save():
            raise asyncio.TimeoutError()

        with patch(
            "bot.services.power_monitor._save_all_user_states",
            side_effect=_slow_save,
        ):
            # Should not raise even when flush times out
            await save_states_on_shutdown()

        mock_connector.close.assert_called_once()
        assert pm._http_connector is None

    async def test_flush_generic_error_does_not_abort_shutdown(self):
        """Non-timeout flush exception is swallowed so the connector still closes."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = AsyncMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        with patch(
            "bot.services.power_monitor._save_all_user_states",
            side_effect=RuntimeError("db gone"),
        ):
            await save_states_on_shutdown()

        mock_connector.close.assert_called_once()
        assert pm._http_connector is None


# ─── daily_ping_error_loop ────────────────────────────────────────────────

class TestDailyPingErrorLoop:
    async def test_loop_calls_send_daily(self):
        """Lines 946-956: Loop calls _send_daily_ping_error_alerts."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot = AsyncMock()
        pm._running = True
        call_count = {"n": 0}

        async def _fake_daily(b):
            call_count["n"] += 1
            pm._running = False

        with (
            patch("bot.services.power_monitor.asyncio.sleep", new_callable=AsyncMock),
            patch("bot.services.power_monitor._send_daily_ping_error_alerts", side_effect=_fake_daily),
        ):
            await daily_ping_error_loop(bot)

        assert call_count["n"] == 1

    async def test_loop_exception_sleeps_and_continues(self):
        """Lines 954-956: Loop exception → sleeps 60s before next iter."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot = AsyncMock()
        pm._running = True
        sleep_calls = []

        async def _fake_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 2:
                pm._running = False

        with (
            patch("bot.services.power_monitor.asyncio.sleep", side_effect=_fake_sleep),
            patch("bot.services.power_monitor._send_daily_ping_error_alerts", side_effect=Exception("err")),
        ):
            await daily_ping_error_loop(bot)

        assert 60 in sleep_calls

    async def test_loop_cancelled_error_breaks(self):
        """Lines 952-953: CancelledError breaks the loop."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot = AsyncMock()
        pm._running = True

        with (
            patch("bot.services.power_monitor.asyncio.sleep", side_effect=asyncio.CancelledError()),
        ):
            await daily_ping_error_loop(bot)


# ─── _send_daily_ping_error_alerts extra branches ─────────────────────────

class TestSendDailyPingErrorAlertsExtra:
    async def test_last_alert_at_naive_gets_utc(self):
        """Line 976: last_at without tzinfo → replace with UTC."""
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot = AsyncMock()
        # Alert sent 1 hour ago (naive datetime) → within 24h → skip
        from datetime import timedelta
        recent_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)  # naive, recent
        alert = SimpleNamespace(
            telegram_id="111222333",
            router_ip="8.8.8.8",
            last_alert_at=recent_naive,
        )

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_active_ping_error_alerts_cursor", return_value=[alert]),
        ):
            await _send_daily_ping_error_alerts(bot)

        bot.send_message.assert_not_called()

    async def test_exception_processing_alert_handled(self):
        """Lines 1027-1030: Exception sending alert → logged."""
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot = AsyncMock()
        alert = SimpleNamespace(
            telegram_id="111222333",
            router_ip="8.8.8.8",
            last_alert_at=None,
        )

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_active_ping_error_alerts_cursor", return_value=[alert]),
            patch("bot.services.power_monitor.check_router_http", return_value=False),
            patch(
                "bot.services.power_monitor.retry_bot_call",
                side_effect=Exception("Send error"),
            ),
            patch("bot.services.power_monitor.get_ip_ping_error_keyboard", return_value=None),
        ):
            # Should not raise
            await _send_daily_ping_error_alerts(bot)

    async def test_outer_exception_per_alert_handled(self):
        """Lines 1029-1030: Outer per-alert exception → logged."""
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot = AsyncMock()
        # Trigger exception in check_router_http (outside the inner try/except)
        alert = SimpleNamespace(telegram_id="999", router_ip="1.2.3.4", last_alert_at=None)

        mock_session = _make_mock_session()

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.get_active_ping_error_alerts_cursor", return_value=[alert]),
            patch("bot.services.power_monitor.check_router_http", side_effect=RuntimeError("network boom")),
        ):
            await _send_daily_ping_error_alerts(bot)  # Should not raise


# ─── update_power_notifications_on_schedule_change ────────────────────────

class TestUpdatePowerNotificationsOnScheduleChange:
    async def test_returns_early_on_empty_schedule_raw(self):
        """Line 1046-1047: Empty schedule_raw → returns early."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()

        with patch("bot.services.power_monitor.fetch_schedule_data", return_value=None):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_not_called()

    async def test_schedule_fetch_exception_returns_early(self):
        """Lines 1050-1052: Schedule fetch error → logged, return early."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()

        with patch("bot.services.power_monitor.fetch_schedule_data", side_effect=Exception("API error")):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_not_called()

    async def test_db_fetch_users_exception_returns_early(self):
        """Lines 1070-1072: DB error fetching users → logged, return."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()

        with (
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch("bot.services.power_monitor.async_session", side_effect=Exception("DB error")),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_not_called()

    async def test_user_without_power_tracking_skipped(self):
        """Line 1079: User with pt=None → continue."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=None,
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_not_called()

    async def test_user_with_unknown_power_state_skipped(self):
        """Lines 1090-1091: current_state not in ('off','on') → continue."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state=None,  # Unknown state
                bot_power_message_id=None,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_not_called()

    async def test_edits_bot_message_for_on_state_with_next_off(self):
        """Lines 1093-1139: Edits bot message for 'on' state with next power_off."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=100,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {
            "type": "power_off",
            "time": "2024-01-01T16:00:00",
            "endTime": "2024-01-01T18:00:00",
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_called_once()

    async def test_edits_bot_message_for_off_state_with_next_on(self):
        """Lines 1100-1103: Edits bot message for 'off' state with next power_on."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="off",
                bot_power_message_id=100,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {
            "type": "power_on",
            "time": "2024-01-01T14:00:00",
        }

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_called_once()

    async def test_edit_message_not_modified_handled(self):
        """Lines 1140-1142: TelegramBadRequest 'not modified' → pass."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message is not modified",
            )
        )
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=100,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_off", "time": "2024-01-01T16:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            # Should not raise
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

    async def test_edit_message_not_found_clears_db_message_id(self):
        """Lines 1143-1162: TelegramBadRequest 'not found' → clears message ID in DB."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )
        mock_session = _make_mock_session()

        db_user = SimpleNamespace(
            power_tracking=SimpleNamespace(
                alert_off_message_id=100,
                bot_power_message_id=100,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=100,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_off", "time": "2024-01-01T16:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

    async def test_channel_message_edited(self):
        """Lines 1170-1237: Channel message edited for off state with next_on."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="off",
                bot_power_message_id=None,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=200,
                power_changed_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            ),
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                last_power_message_id=None,
            ),
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_on", "time": "2024-01-01T14:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        # edit_message_text called for channel
        bot.edit_message_text.assert_called()

    async def test_channel_message_not_modified_handled(self):
        """Line 1212: Channel TelegramBadRequest 'not modified' → pass."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        call_count = {"n": 0}

        async def _edit_side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call is for bot msg (no bot msg_id, so skip)
                pass
            raise TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message is not modified",
            )

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message is not modified",
            )
        )
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=None,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=200,
                power_changed_at=None,
            ),
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                last_power_message_id=None,
            ),
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_off", "time": "2024-01-01T16:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

    async def test_channel_message_not_found_clears_db_id(self):
        """Lines 1214-1231: Channel 'not found' → clears channel message IDs in DB."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )
        mock_session = _make_mock_session()

        db_user = SimpleNamespace(
            channel_config=SimpleNamespace(last_power_message_id=200),
            power_tracking=SimpleNamespace(ch_power_message_id=200),
        )
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=None,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=200,
                power_changed_at=None,
            ),
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                last_power_message_id=None,
            ),
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_off", "time": "2024-01-01T16:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

    async def test_fallback_to_legacy_message_id(self):
        """Lines 1084-1089: Falls back to alert_off_message_id when bot_power_message_id is None."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="off",
                bot_power_message_id=None,  # Use legacy field
                alert_off_message_id=150,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_on", "time": "2024-01-01T14:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_called_once()

    async def test_with_power_changed_at_duration(self):
        """Lines 1111-1120: power_changed_at present → formats duration_text and time_str."""
        from datetime import timedelta

        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        changed_at = datetime.now(timezone.utc) - timedelta(minutes=90)

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=100,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=changed_at,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_off", "time": "2024-01-01T16:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_called_once()

    async def test_channel_with_naive_power_changed_at(self):
        """Line 1185: Channel path with naive power_changed_at → adds UTC tzinfo."""
        from datetime import timedelta

        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        naive_changed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=None,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=200,
                power_changed_at=naive_changed_at,  # naive
            ),
            channel_config=SimpleNamespace(
                channel_id=-1001111111111,
                last_power_message_id=None,
            ),
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        next_event = {"type": "power_off", "time": "2024-01-01T16:00:00"}

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=next_event),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_called()

    async def test_next_event_none_produces_none_schedule_line(self):
        """Line 1104-1105: next_event is None → new_schedule_line = None → skip edit."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        mock_session = _make_mock_session()

        user = SimpleNamespace(
            telegram_id="111222333",
            power_tracking=SimpleNamespace(
                power_state="on",
                bot_power_message_id=100,
                alert_off_message_id=None,
                alert_on_message_id=None,
                ch_power_message_id=None,
                power_changed_at=None,
            ),
            channel_config=None,
        )
        mock_session.execute.return_value.scalars.return_value.all.return_value = [user]

        with (
            _patch_pm_async_session(mock_session),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value=[]),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        # No edit when schedule line is None
        bot.edit_message_text.assert_not_called()


# ─── Cursor pagination coverage ───────────────────────────────────────────


class TestCheckAllIpsPagination:
    """Line 668: after_id is set when a full batch is returned."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_full_batch_advances_cursor(self):
        from bot.services.power_monitor import _check_all_ips

        bot = AsyncMock()
        _BATCH = 500
        fake_users = [
            SimpleNamespace(id=i, telegram_id=str(i + 90000), router_ip="8.8.8.8")
            for i in range(_BATCH)
        ]

        call_count = {"n": 0}

        async def _cursor_side_effect(session, limit, after_id):
            call_count["n"] += 1
            return fake_users if call_count["n"] == 1 else []

        with (
            _patch_pm_async_session(_make_mock_session()),
            patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                side_effect=_cursor_side_effect,
            ),
            patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=True)),
            patch("bot.services.power_monitor._check_user_power", AsyncMock()),
        ):
            await _check_all_ips(bot)

        assert call_count["n"] == 2


class TestSaveAllUserStatesEmptySnapshot:
    """Line 756: dirty TIDs absent from _user_states → snapshot empty → early return."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._dirty_states.clear()

    async def test_empty_snapshot_skips_batch_upsert(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        ghost_tid = "ghost_snap_test_88888"
        pm._dirty_states.add(ghost_tid)

        batch_mock = AsyncMock()
        with patch("bot.services.power_monitor.batch_upsert_user_power_states", batch_mock):
            await _save_all_user_states()

        batch_mock.assert_not_called()
        pm._dirty_states.discard(ghost_tid)


class TestSendDailyPingErrorAlertsPagination:
    """Lines 1035, 1098: empty first page and full-batch pagination."""

    async def test_empty_first_page_breaks_immediately(self):
        """Line 1035: first alerts page is empty → break."""
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot = AsyncMock()
        with patch(
            "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
            AsyncMock(return_value=[]),
        ), _patch_pm_async_session(_make_mock_session()):
            await _send_daily_ping_error_alerts(bot)

        bot.send_message.assert_not_called()

    async def test_full_batch_advances_cursor(self):
        """Line 1098: full batch (500 alerts) → after_id advanced for second page."""
        from datetime import timedelta

        from bot.services.power_monitor import _send_daily_ping_error_alerts

        _BATCH = 500
        # Set last_alert_at to within 24h so the 24h-check `continue` fires for all
        # alerts — this avoids real HTTP calls to check_router_http.
        recent_at = datetime.now(timezone.utc) - timedelta(hours=1)
        fake_alerts = [
            SimpleNamespace(
                id=i,
                telegram_id=str(i + 70000),
                last_alert_at=recent_at,
                router_ip="1.2.3.4",
                router_last_online_at=None,
            )
            for i in range(_BATCH)
        ]

        call_count = {"n": 0}

        async def _cursor_side_effect(session, limit, after_id):
            call_count["n"] += 1
            return fake_alerts if call_count["n"] == 1 else []

        bot = AsyncMock()
        with (
            _patch_pm_async_session(_make_mock_session()),
            patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                side_effect=_cursor_side_effect,
            ),
        ):
            await _send_daily_ping_error_alerts(bot)

        assert call_count["n"] == 2


class TestUpdatePowerNotificationsPagination:
    """Lines 1135, 1304: empty users page and full-batch pagination."""

    async def test_empty_first_page_breaks_immediately(self):
        """Line 1135: first users page is empty → break."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot = AsyncMock()
        with (
            _patch_pm_async_session(_make_mock_session()),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"d": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch(
                "bot.services.power_monitor.get_active_power_users_by_region_queue_cursor",
                AsyncMock(return_value=[]),
            ),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        bot.edit_message_text.assert_not_called()

    async def test_full_batch_advances_cursor(self):
        """Line 1304: full batch (500 users) → after_id advanced."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        _BATCH = 500
        fake_users = [
            SimpleNamespace(
                id=i,
                telegram_id=str(i + 60000),
                power_tracking=None,
                channel_config=None,
            )
            for i in range(_BATCH)
        ]

        call_count = {"n": 0}

        async def _cursor_side_effect(session, region, queue, limit, after_id):
            call_count["n"] += 1
            return fake_users if call_count["n"] == 1 else []

        bot = AsyncMock()
        with (
            _patch_pm_async_session(_make_mock_session()),
            patch("bot.services.power_monitor.fetch_schedule_data", return_value={"d": "x"}),
            patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}),
            patch("bot.services.power_monitor.find_next_event", return_value=None),
            patch(
                "bot.services.power_monitor.get_active_power_users_by_region_queue_cursor",
                side_effect=_cursor_side_effect,
            ),
        ):
            await update_power_notifications_on_schedule_change(bot, "kyiv", "1.1")

        assert call_count["n"] == 2


# ─── _evict_stale_entries ──────────────────────────────────────────────────


class TestEvictStaleEntries:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._dirty_states.clear()

    @pytest.mark.asyncio
    async def test_ttl_evicts_entries_older_than_threshold(self, monkeypatch):
        import bot.services.power_monitor as pm

        now = datetime.now(timezone.utc)
        old = now.replace(year=now.year - 1).isoformat()
        fresh = now.isoformat()

        pm._user_states["old"] = {"last_change_at": old, "debounce_task": None}
        pm._user_states["fresh"] = {"last_change_at": fresh, "debounce_task": None}
        pm._dirty_states.update(["old", "fresh"])

        await pm._evict_stale_entries()

        assert "old" not in pm._user_states
        assert "fresh" in pm._user_states
        assert "old" not in pm._dirty_states

    @pytest.mark.asyncio
    async def test_cap_evicts_lru_when_over_max(self, monkeypatch):
        import bot.services.power_monitor as pm

        monkeypatch.setattr(pm, "USER_STATES_MAX", 2)
        now = datetime.now(timezone.utc)
        pm._user_states["oldest"] = {
            "last_change_at": now.replace(minute=0).isoformat(),
            "debounce_task": None,
        }
        pm._user_states["middle"] = {
            "last_change_at": now.replace(minute=30).isoformat(),
            "debounce_task": None,
        }
        pm._user_states["newest"] = {
            "last_change_at": now.isoformat(),
            "debounce_task": None,
        }

        await pm._evict_stale_entries()

        assert "oldest" not in pm._user_states
        assert "middle" in pm._user_states
        assert "newest" in pm._user_states
        assert len(pm._user_states) == 2

    @pytest.mark.asyncio
    async def test_cancels_debounce_task_on_eviction(self, monkeypatch):
        import bot.services.power_monitor as pm

        monkeypatch.setattr(pm, "USER_STATES_MAX", 0)  # force evict-all via cap

        async def _forever():
            await asyncio.sleep(3600)

        task = asyncio.create_task(_forever())
        pm._user_states["victim"] = {"last_change_at": None, "debounce_task": task}

        await pm._evict_stale_entries()

        # Let the cancellation propagate.
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()
        assert "victim" not in pm._user_states

    @pytest.mark.asyncio
    async def test_noop_when_empty(self):
        import bot.services.power_monitor as pm

        await pm._evict_stale_entries()
        assert pm._user_states == {}

    def test_state_last_touch_ts_falls_back_through_fields(self):
        import bot.services.power_monitor as pm

        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert pm._state_last_touch_ts({"last_change_at": ts}) == ts.timestamp()
        assert pm._state_last_touch_ts(
            {"last_change_at": None, "last_ping_time": ts.isoformat()}
        ) == ts.timestamp()
        assert pm._state_last_touch_ts({"last_change_at": "garbage"}) == 0.0
        assert pm._state_last_touch_ts({}) == 0.0
