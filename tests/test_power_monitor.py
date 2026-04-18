"""Tests for bot/services/power_monitor.py.

These tests focus on the pure/isolated parts of the power monitor service:
- _get_user_state: in-memory state management
- check_router_http: router reachability logic (mocked HTTP)
- _get_http_connector: lazy connector creation
- State machine invariants
- _format_exact_duration / _format_time: pure helpers
- _get_check_interval / _get_debounce_seconds: DB setting readers
- stop_power_monitor / save_states_on_shutdown: shutdown logic
- _save_all_user_states / _restore_user_states: state persistence
- _check_user_power: per-user state machine
- _check_all_ips: bulk check orchestration
- _handle_power_state_change: notification sender
- _send_daily_ping_error_alerts: daily ping-error alerts
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ─── Shared helpers ───────────────────────────────────────────────────────


def _make_method_mock() -> MagicMock:
    """Minimal aiogram Method mock (required by Telegram exception constructors)."""
    return MagicMock()


def _make_telegram_forbidden() -> TelegramForbiddenError:
    return TelegramForbiddenError(
        method=_make_method_mock(),
        message="Forbidden: bot was blocked by the user",
    )


def _make_telegram_bad_request() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=_make_method_mock(),
        message="Bad Request: message not found",
    )


def _make_mock_session() -> AsyncMock:
    """Return a minimal async SQLAlchemy session mock."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    # return_value must be a plain MagicMock: session.execute IS async (awaited),
    # but the Result it returns exposes synchronous .scalars()/.first() methods.
    # Using AsyncMock() as return_value would cause RuntimeWarning because calling
    # r.scalars() on an AsyncMock creates a never-awaited coroutine.
    session.execute = AsyncMock(return_value=MagicMock())
    return session


@asynccontextmanager
async def _mock_async_session(session: AsyncMock):
    """Async context manager that yields the given mock session."""
    yield session


def _patch_pm_async_session(mock_session: AsyncMock):
    """Patch bot.services.power_monitor.async_session to always yield mock_session."""
    return patch(
        "bot.services.power_monitor.async_session",
        side_effect=lambda: _mock_async_session(mock_session),
    )


def _make_pm_user(**kwargs) -> SimpleNamespace:
    """Create a mock user suitable for power-monitor tests."""
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


def _default_user_state() -> dict:
    """Return a fresh default user state dict."""
    return {
        "current_state": None,
        "last_change_at": None,
        "consecutive_checks": 0,
        "is_first_check": True,
        "pending_state": None,
        "pending_state_time": None,
        "original_change_time": None,
        "debounce_task": None,
        "instability_start": None,
        "switch_count": 0,
        "last_stable_state": None,
        "last_stable_at": None,
        "last_ping_time": None,
        "last_ping_success": None,
        "last_notification_at": None,
    }


# ─── _get_user_state ─────────────────────────────────────────────────────


class TestGetUserState:
    def setup_method(self):
        # Reset global state before each test
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def test_creates_new_state_for_unknown_user(self):
        from bot.services.power_monitor import _get_user_state

        state = _get_user_state("user_1")

        assert state is not None
        assert state["current_state"] is None
        assert state["consecutive_checks"] == 0
        assert state["is_first_check"] is True
        assert state["pending_state"] is None
        assert state["debounce_task"] is None
        assert state["switch_count"] == 0
        assert state["last_notification_at"] is None

    def test_returns_same_object_for_repeated_calls(self):
        from bot.services.power_monitor import _get_user_state

        state1 = _get_user_state("user_2")
        state2 = _get_user_state("user_2")

        assert state1 is state2

    def test_different_users_get_different_states(self):
        from bot.services.power_monitor import _get_user_state

        state_a = _get_user_state("user_a")
        state_b = _get_user_state("user_b")

        assert state_a is not state_b

    def test_state_mutations_persist_between_calls(self):
        from bot.services.power_monitor import _get_user_state

        state = _get_user_state("user_3")
        state["current_state"] = "power_off"
        state["consecutive_checks"] = 5

        state_again = _get_user_state("user_3")
        assert state_again["current_state"] == "power_off"
        assert state_again["consecutive_checks"] == 5

    def test_all_expected_keys_present(self):
        from bot.services.power_monitor import _get_user_state

        state = _get_user_state("user_4")
        expected_keys = {
            "current_state",
            "last_change_at",
            "consecutive_checks",
            "is_first_check",
            "pending_state",
            "pending_state_time",
            "original_change_time",
            "debounce_task",
            "instability_start",
            "switch_count",
            "last_stable_state",
            "last_stable_at",
            "last_ping_time",
            "last_ping_success",
            "last_notification_at",
        }
        assert expected_keys.issubset(state.keys())

    def test_clearing_state_dict_removes_user(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _get_user_state

        _get_user_state("user_5")
        assert "user_5" in pm._user_states

        del pm._user_states["user_5"]
        assert "user_5" not in pm._user_states


# ─── check_router_http ──────────────────────────────────────────────────


class TestCheckRouterHttp:
    async def test_returns_none_for_no_ip(self):
        from bot.services.power_monitor import check_router_http

        result = await check_router_http(None)

        assert result is None

    async def test_returns_none_for_empty_ip(self):
        from bot.services.power_monitor import check_router_http

        result = await check_router_http("")

        assert result is None

    async def test_returns_true_on_http_success(self):
        from bot.services.power_monitor import check_router_http

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.head = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_connector = MagicMock()

        with patch("bot.services.power_monitor._get_http_connector", return_value=mock_connector), \
             patch("aiohttp.ClientSession", return_value=mock_session):
            result = await check_router_http("8.8.8.8")

        assert result is True

    async def test_returns_false_on_connection_error(self):
        import aiohttp

        from bot.services.power_monitor import check_router_http

        mock_connector = MagicMock()

        with patch("bot.services.power_monitor._get_http_connector", return_value=mock_connector), \
             patch("aiohttp.ClientSession") as MockSession:
            mock_session_instance = MagicMock()
            mock_session_instance.head = MagicMock(side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("refused")
            ))
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value = mock_session_instance

            result = await check_router_http("192.168.1.1")

        assert result is False

    async def test_returns_false_on_timeout(self):
        import asyncio

        from bot.services.power_monitor import check_router_http

        mock_connector = MagicMock()

        with patch("bot.services.power_monitor._get_http_connector", return_value=mock_connector), \
             patch("aiohttp.ClientSession") as MockSession:
            mock_session_instance = MagicMock()
            mock_session_instance.head = MagicMock(side_effect=asyncio.TimeoutError())
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value = mock_session_instance

            result = await check_router_http("192.168.1.1")

        assert result is False

    async def test_parses_ip_with_port(self):
        """Router addresses with port (e.g. 192.168.1.1:8080) should use the specified port."""
        from bot.services.power_monitor import check_router_http

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.head = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_connector = MagicMock()

        with patch("bot.services.power_monitor._get_http_connector", return_value=mock_connector), \
             patch("aiohttp.ClientSession", return_value=mock_session):
            result = await check_router_http("8.8.8.8:8080")

        assert result is True

    async def test_returns_true_for_non_200_status(self):
        """Non-200 HTTP responses still mean the host is reachable (power is on)."""
        from bot.services.power_monitor import check_router_http

        mock_response = AsyncMock()
        mock_response.status = 403  # Forbidden, but host responded
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.head = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_connector = MagicMock()

        with patch("bot.services.power_monitor._get_http_connector", return_value=mock_connector), \
             patch("aiohttp.ClientSession", return_value=mock_session):
            result = await check_router_http("8.8.8.8")

        assert result is True

    @pytest.mark.parametrize("private_ip", [
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.1",
        "255.255.255.255",
    ])
    async def test_blocks_ssrf_ips(self, private_ip: str):
        """_check_router_http must return False for loopback/link-local/broadcast IPs (SSRF protection)."""
        from bot.services.power_monitor import check_router_http

        # aiohttp.ClientSession should never be called for SSRF-blocked IPs
        with patch("aiohttp.ClientSession") as MockSession:
            result = await check_router_http(private_ip)

        assert result is False, f"Expected False for blocked IP {private_ip!r}, got {result!r}"
        MockSession.assert_not_called()

    @pytest.mark.parametrize("private_ip", [
        "192.168.1.1",
        "10.0.0.1",
        "172.16.0.1",
    ])
    async def test_allows_rfc1918_private_ips(self, private_ip: str):
        """_is_ssrf_blocked must return False for RFC-1918 private IPs (typical home routers)."""
        from bot.services.power_monitor import _is_ssrf_blocked

        assert _is_ssrf_blocked(private_ip) is False, (
            f"RFC-1918 IP {private_ip!r} should NOT be blocked"
        )


# ─── _is_ssrf_blocked ────────────────────────────────────────────────────


class TestIsSsrfBlocked:
    @pytest.mark.parametrize("ip,expected", [
        ("127.0.0.1", True),
        ("127.255.255.255", True),
        ("169.254.169.254", True),
        ("169.254.0.1", True),
        ("0.0.0.0", True),
        ("255.255.255.255", True),
        ("240.0.0.1", True),
        ("192.168.1.1", False),
        ("10.0.0.1", False),
        ("172.16.0.1", False),
        ("8.8.8.8", False),
        ("1.1.1.1", False),
        ("router.example.com", False),  # Hostnames pass through
    ])
    def test_ssrf_blocked_classification(self, ip: str, expected: bool):
        from bot.services.power_monitor import _is_ssrf_blocked

        assert _is_ssrf_blocked(ip) is expected, f"Expected {expected} for {ip!r}"


# ─── _get_http_connector ─────────────────────────────────────────────────


class TestGetHttpConnector:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._http_connector = None

    def test_creates_connector_when_none(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _get_http_connector

        with patch("aiohttp.TCPConnector") as MockConnector:
            MockConnector.return_value = MagicMock(closed=False)
            connector = _get_http_connector()
            MockConnector.assert_called_once()
            assert connector is pm._http_connector

    def test_reuses_existing_open_connector(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _get_http_connector

        existing = MagicMock()
        existing.closed = False
        pm._http_connector = existing

        with patch("aiohttp.TCPConnector") as MockConnector:
            result = _get_http_connector()
            MockConnector.assert_not_called()  # Should not create a new one
            assert result is existing

    def test_creates_new_connector_when_existing_is_closed(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _get_http_connector

        closed_connector = MagicMock()
        closed_connector.closed = True
        pm._http_connector = closed_connector

        with patch("aiohttp.TCPConnector") as MockConnector:
            new_connector = MagicMock(closed=False)
            MockConnector.return_value = new_connector
            result = _get_http_connector()
            MockConnector.assert_called_once()
            assert result is new_connector


# ─── _format_exact_duration ───────────────────────────────────────────────


class TestFormatExactDuration:
    def test_zero_minutes_returns_less_than_minute(self):
        from bot.services.power_monitor import _format_exact_duration

        assert _format_exact_duration(0) == "менше хвилини"

    def test_one_minute(self):
        from bot.services.power_monitor import _format_exact_duration

        assert _format_exact_duration(1) == "1 хв"

    def test_thirty_minutes(self):
        from bot.services.power_monitor import _format_exact_duration

        assert _format_exact_duration(30) == "30 хв"

    def test_sixty_minutes_is_one_hour(self):
        from bot.services.power_monitor import _format_exact_duration

        assert _format_exact_duration(60) == "1 год"

    def test_ninety_minutes_is_one_hour_thirty(self):
        from bot.services.power_monitor import _format_exact_duration

        assert _format_exact_duration(90) == "1 год 30 хв"

    def test_one_hundred_fifty_minutes(self):
        from bot.services.power_monitor import _format_exact_duration

        assert _format_exact_duration(150) == "2 год 30 хв"


# ─── _format_time ─────────────────────────────────────────────────────────


class TestFormatTime:
    def test_valid_iso_string_returns_hhmm(self):
        from bot.services.power_monitor import _format_time

        assert _format_time("2024-01-15T14:30:00") == "14:30"

    def test_valid_iso_with_timezone_offset(self):
        from bot.services.power_monitor import _format_time

        assert _format_time("2024-01-15T09:05:00+02:00") == "09:05"

    def test_invalid_string_returns_unknown(self):
        from bot.services.power_monitor import _format_time

        assert _format_time("not-a-date") == "невідомо"

    def test_empty_string_returns_unknown(self):
        from bot.services.power_monitor import _format_time

        assert _format_time("") == "невідомо"


# ─── _get_check_interval ──────────────────────────────────────────────────


class TestGetCheckInterval:
    async def test_returns_db_value_when_valid_positive_int(self):
        from bot.services.power_monitor import _get_check_interval

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="30")):
            result = await _get_check_interval(mock_session)

        assert result == 30

    async def test_returns_default_when_no_setting(self):
        from bot.services.power_monitor import DEFAULT_CHECK_INTERVAL_S, _get_check_interval

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value=None)):
            result = await _get_check_interval(mock_session)

        assert result == DEFAULT_CHECK_INTERVAL_S

    async def test_returns_default_when_non_numeric(self):
        from bot.services.power_monitor import DEFAULT_CHECK_INTERVAL_S, _get_check_interval

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="abc")):
            result = await _get_check_interval(mock_session)

        assert result == DEFAULT_CHECK_INTERVAL_S

    async def test_returns_default_when_zero(self):
        from bot.services.power_monitor import DEFAULT_CHECK_INTERVAL_S, _get_check_interval

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="0")):
            result = await _get_check_interval(mock_session)

        assert result == DEFAULT_CHECK_INTERVAL_S

    async def test_returns_default_when_negative(self):
        from bot.services.power_monitor import DEFAULT_CHECK_INTERVAL_S, _get_check_interval

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="-5")):
            result = await _get_check_interval(mock_session)

        assert result == DEFAULT_CHECK_INTERVAL_S


# ─── _get_debounce_seconds ────────────────────────────────────────────────


class TestGetDebounceSeconds:
    async def test_returns_db_value_times_sixty(self):
        from bot.services.power_monitor import _get_debounce_seconds

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="10")):
            result = await _get_debounce_seconds(mock_session)

        assert result == 600  # 10 * 60

    async def test_accepts_zero_returns_zero(self):
        from bot.services.power_monitor import _get_debounce_seconds

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="0")):
            result = await _get_debounce_seconds(mock_session)

        assert result == 0

    async def test_returns_default_when_no_setting(self):
        from bot.services.power_monitor import DEFAULT_DEBOUNCE_S, _get_debounce_seconds

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value=None)):
            result = await _get_debounce_seconds(mock_session)

        assert result == DEFAULT_DEBOUNCE_S

    async def test_returns_default_when_non_numeric(self):
        from bot.services.power_monitor import DEFAULT_DEBOUNCE_S, _get_debounce_seconds

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="bad")):
            result = await _get_debounce_seconds(mock_session)

        assert result == DEFAULT_DEBOUNCE_S

    async def test_returns_default_when_negative(self):
        from bot.services.power_monitor import DEFAULT_DEBOUNCE_S, _get_debounce_seconds

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="-1")):
            result = await _get_debounce_seconds(mock_session)

        assert result == DEFAULT_DEBOUNCE_S


# ─── stop_power_monitor ───────────────────────────────────────────────────


class TestStopPowerMonitor:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._running = True

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._running = False

    def test_sets_running_false(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import stop_power_monitor

        stop_power_monitor()

        assert pm._running is False

    def test_cancels_pending_debounce_tasks(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import stop_power_monitor

        mock_task = MagicMock()
        mock_task.done.return_value = False
        pm._user_states["123"] = {**_default_user_state(), "debounce_task": mock_task}

        stop_power_monitor()

        mock_task.cancel.assert_called_once()

    def test_skips_already_done_tasks(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import stop_power_monitor

        mock_task = MagicMock()
        mock_task.done.return_value = True
        pm._user_states["123"] = {**_default_user_state(), "debounce_task": mock_task}

        stop_power_monitor()

        mock_task.cancel.assert_not_called()

    def test_idempotent_when_already_stopped(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import stop_power_monitor

        pm._running = False
        stop_power_monitor()  # Should not raise

        assert pm._running is False

    def test_handles_empty_user_states(self):
        from bot.services.power_monitor import stop_power_monitor

        stop_power_monitor()  # Should not raise with no states


# ─── save_states_on_shutdown ──────────────────────────────────────────────


class TestSaveStatesOnShutdown:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._http_connector = None

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._http_connector = None

    async def test_delegates_to_save_all_user_states(self):
        from bot.services.power_monitor import save_states_on_shutdown

        with patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock) as mock_save:
            await save_states_on_shutdown()

        mock_save.assert_called_once()

    async def test_closes_http_connector_on_shutdown(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = MagicMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        with patch("bot.services.power_monitor._save_all_user_states", new_callable=AsyncMock):
            await save_states_on_shutdown()

        mock_connector.close.assert_called_once()
        assert pm._http_connector is None


# ─── _save_all_user_states ────────────────────────────────────────────────


class TestSaveAllUserStates:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._dirty_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._dirty_states.clear()

    async def test_empty_states_makes_no_db_call(self):
        from bot.services.power_monitor import _save_all_user_states

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.batch_upsert_user_power_states",
                new_callable=AsyncMock,
            ) as mock_batch:
                await _save_all_user_states()

        mock_batch.assert_not_called()

    async def test_non_empty_calls_batch_upsert_with_correct_row(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        pm._user_states["111"] = {**_default_user_state(), "current_state": "on"}
        pm._dirty_states.add("111")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.batch_upsert_user_power_states",
                new_callable=AsyncMock,
            ) as mock_batch:
                await _save_all_user_states()

        mock_batch.assert_called_once()
        rows = mock_batch.call_args[0][1]
        assert len(rows) == 1
        assert rows[0]["telegram_id"] == "111"
        assert rows[0]["current_state"] == "on"

    async def test_last_notification_iso_string_converted_to_datetime(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        pm._user_states["222"] = {
            **_default_user_state(),
            "last_notification_at": "2024-01-15T14:30:00+02:00",
        }
        pm._dirty_states.add("222")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.batch_upsert_user_power_states",
                new_callable=AsyncMock,
            ) as mock_batch:
                await _save_all_user_states()

        rows = mock_batch.call_args[0][1]
        assert isinstance(rows[0]["last_notification_at"], datetime)

    async def test_multiple_users_all_included_in_rows(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        pm._user_states["aaa"] = {**_default_user_state(), "current_state": "on"}
        pm._user_states["bbb"] = {**_default_user_state(), "current_state": "off"}
        pm._dirty_states.add("aaa")
        pm._dirty_states.add("bbb")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.batch_upsert_user_power_states",
                new_callable=AsyncMock,
            ) as mock_batch:
                await _save_all_user_states()

        rows = mock_batch.call_args[0][1]
        tids = {r["telegram_id"] for r in rows}
        assert tids == {"aaa", "bbb"}

    async def test_handles_db_error_gracefully(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        pm._user_states["333"] = {**_default_user_state(), "current_state": "off"}
        pm._dirty_states.add("333")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.batch_upsert_user_power_states",
                AsyncMock(side_effect=Exception("DB error")),
            ):
                await _save_all_user_states()  # Should not raise


# ─── _restore_user_states ─────────────────────────────────────────────────


class TestRestoreUserStates:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def _make_row(self, telegram_id: str = "111", **kwargs) -> SimpleNamespace:
        defaults = dict(
            telegram_id=telegram_id,
            current_state="on",
            pending_state=None,
            pending_state_time=None,
            last_stable_state="on",
            last_stable_at=None,
            instability_start=None,
            switch_count=0,
            last_notification_at=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    async def test_restores_rows_into_user_states(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restore_user_states

        row = self._make_row("111", current_state="on")
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_recent_user_power_states",
                AsyncMock(return_value=[row]),
            ):
                await _restore_user_states()

        assert "111" in pm._user_states
        assert pm._user_states["111"]["current_state"] == "on"

    async def test_sets_is_first_check_false(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restore_user_states

        row = self._make_row("222")
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_recent_user_power_states",
                AsyncMock(return_value=[row]),
            ):
                await _restore_user_states()

        assert pm._user_states["222"]["is_first_check"] is False

    async def test_sets_debounce_task_none(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restore_user_states

        row = self._make_row("333")
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_recent_user_power_states",
                AsyncMock(return_value=[row]),
            ):
                await _restore_user_states()

        assert pm._user_states["333"]["debounce_task"] is None

    async def test_handles_naive_last_notification_at(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restore_user_states

        naive_dt = datetime(2024, 1, 15, 14, 30, 0)  # tzinfo=None
        row = self._make_row("444", last_notification_at=naive_dt)
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_recent_user_power_states",
                AsyncMock(return_value=[row]),
            ):
                await _restore_user_states()

        stored = pm._user_states["444"]["last_notification_at"]
        assert stored is not None
        # Naive dt should have been given KYIV_TZ and serialised to ISO with tz info
        assert "+" in stored or stored.endswith("Z")

    async def test_handles_aware_last_notification_at(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restore_user_states

        aware_dt = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        row = self._make_row("555", last_notification_at=aware_dt)
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_recent_user_power_states",
                AsyncMock(return_value=[row]),
            ):
                await _restore_user_states()

        assert pm._user_states["555"]["last_notification_at"] == aware_dt.isoformat()

    async def test_handles_db_error_gracefully(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restore_user_states

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_recent_user_power_states",
                AsyncMock(side_effect=Exception("DB error")),
            ):
                await _restore_user_states()  # Should not raise

        assert len(pm._user_states) == 0


# ─── _check_user_power ────────────────────────────────────────────────────


class TestCheckUserPower:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        for state in list(pm._user_states.values()):
            task = state.get("debounce_task")
            if task and not task.done():
                task.cancel()
        pm._user_states.clear()

    async def test_returns_early_when_no_router_ip(self):
        """No router IP → check_router_http returns None → user skipped silently."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="111", router_ip=None)

        await _check_user_power(bot_mock, user)

        assert "111" not in pm._user_states

    async def test_first_check_no_db_record_seeds_state_without_notification(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        # power_tracking.power_state is None → no prior DB record
        user = _make_pm_user(telegram_id="222")

        mock_session = _make_mock_session()
        # No DB user found
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        assert pm._user_states["222"]["current_state"] == "on"
        assert pm._user_states["222"]["is_first_check"] is False
        bot_mock.send_message.assert_not_called()

    async def test_first_check_with_db_record_restores_state_without_notification(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(
            telegram_id="333",
            power_tracking=SimpleNamespace(
                power_state="off",
                power_changed_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=KYIV_TZ),
            ),
        )

        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        # current_state restored from DB record ("off"), NOT overwritten by new ping
        assert pm._user_states["333"]["current_state"] == "off"
        assert pm._user_states["333"]["is_first_check"] is False
        bot_mock.send_message.assert_not_called()

    async def test_state_unchanged_resets_consecutive_checks(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="444")

        pm._user_states["444"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "consecutive_checks": 5,
        }

        await _check_user_power(bot_mock, user, is_available=True)

        assert pm._user_states["444"]["consecutive_checks"] == 0

    async def test_flapping_cancels_pending_debounce_task(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="555")

        mock_task = MagicMock()
        mock_task.done.return_value = False

        # Current state is "on", pending is "off" — now back to "on" → cancel
        pm._user_states["555"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "pending_state": "off",
            "debounce_task": mock_task,
        }

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        mock_task.cancel.assert_called_once()
        assert pm._user_states["555"]["pending_state"] is None

    async def test_new_state_change_sets_pending_and_creates_debounce_task(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="666")

        pm._user_states["666"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_setting",
                AsyncMock(return_value="5"),
            ):
                await _check_user_power(bot_mock, user, is_available=False)

        assert pm._user_states["666"]["pending_state"] == "off"
        task = pm._user_states["666"]["debounce_task"]
        assert task is not None
        # Clean up the real asyncio task
        task.cancel()

    async def test_same_pending_state_is_noop(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="777")

        # Already waiting for "off" — receiving "off" again should be silent
        pm._user_states["777"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "pending_state": "off",
        }

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=False)

        # pending_state must remain unchanged
        assert pm._user_states["777"]["pending_state"] == "off"


# ─── _check_all_ips ───────────────────────────────────────────────────────


class TestCheckAllIps:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_skips_if_lock_already_held(self):
        from bot.services.power_monitor import _check_all_ips, _check_all_ips_lock

        bot_mock = AsyncMock()
        async with _check_all_ips_lock:
            with patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                new_callable=AsyncMock,
            ) as mock_get_users:
                await _check_all_ips(bot_mock)

        mock_get_users.assert_not_called()

    async def test_empty_user_list_is_noop(self):
        from bot.services.power_monitor import _check_all_ips

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                AsyncMock(return_value=[]),
            ):
                with patch(
                    "bot.services.power_monitor._check_user_power",
                    new_callable=AsyncMock,
                ) as mock_check:
                    await _check_all_ips(bot_mock)

        mock_check.assert_not_called()

    async def test_each_unique_ip_pinged_once(self):
        from bot.services.power_monitor import _check_all_ips

        bot_mock = AsyncMock()
        user1 = _make_pm_user(telegram_id="111", router_ip="1.2.3.4")
        user2 = _make_pm_user(telegram_id="222", router_ip="1.2.3.4")  # same IP
        user3 = _make_pm_user(telegram_id="333", router_ip="5.6.7.8")  # different IP

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                AsyncMock(return_value=[user1, user2, user3]),
            ):
                with patch(
                    "bot.services.power_monitor.check_router_http",
                    AsyncMock(return_value=True),
                ) as mock_ping:
                    with patch("bot.services.power_monitor._check_user_power", new_callable=AsyncMock):
                        await _check_all_ips(bot_mock)

        assert mock_ping.call_count == 2

    async def test_evicts_stale_user_states(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_all_ips

        pm._user_states["999"] = {**_default_user_state(), "current_state": "on"}

        bot_mock = AsyncMock()
        user1 = _make_pm_user(telegram_id="111", router_ip="1.2.3.4")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                AsyncMock(return_value=[user1]),
            ):
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=True)):
                    with patch("bot.services.power_monitor._check_user_power", new_callable=AsyncMock):
                        await _check_all_ips(bot_mock)

        assert "999" not in pm._user_states

    async def test_cancels_debounce_task_for_evicted_users(self):
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_all_ips

        mock_task = MagicMock()
        mock_task.done.return_value = False
        pm._user_states["888"] = {**_default_user_state(), "debounce_task": mock_task}

        bot_mock = AsyncMock()
        user1 = _make_pm_user(telegram_id="111", router_ip="1.2.3.4")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                AsyncMock(return_value=[user1]),
            ):
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=True)):
                    with patch("bot.services.power_monitor._check_user_power", new_callable=AsyncMock):
                        await _check_all_ips(bot_mock)

        mock_task.cancel.assert_called_once()


# ─── _handle_power_state_change ──────────────────────────────────────────


class TestHandlePowerStateChange:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def _fresh_user(self, telegram_id: str = "111", **kwargs) -> SimpleNamespace:
        return _make_pm_user(telegram_id=telegram_id, **kwargs)

    async def test_sends_notification_to_user(self):
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        sent_msg = SimpleNamespace(message_id=42)
        bot_mock.send_message.return_value = sent_msg

        user = _make_pm_user(telegram_id="111")
        user_state = _default_user_state()
        fresh_user = self._fresh_user("111")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_called_once()

    async def test_skips_notification_when_cooldown_active(self):
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="222")
        user_state = {
            **_default_user_state(),
            "last_notification_at": datetime.now(KYIV_TZ).isoformat(),
        }
        fresh_user = self._fresh_user("222")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_not_called()

    async def test_returns_early_when_user_not_in_db(self):
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="333")
        user_state = _default_user_state()

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=None)):
                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_not_called()

    async def test_handles_telegram_forbidden_error_deactivates_user(self):
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.side_effect = _make_telegram_forbidden()

        user = _make_pm_user(telegram_id="444")
        user_state = _default_user_state()
        fresh_user = self._fresh_user("444")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch(
                                "bot.services.power_monitor.deactivate_user",
                                new_callable=AsyncMock,
                            ) as mock_deactivate:
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        mock_deactivate.assert_called_once()

    async def test_handles_telegram_bad_request_without_crash(self):
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.side_effect = _make_telegram_bad_request()

        user = _make_pm_user(telegram_id="555")
        user_state = _default_user_state()
        fresh_user = self._fresh_user("555")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            # Should not raise
                            await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

    async def test_formats_duration_text_from_power_result(self):
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        sent_msg = SimpleNamespace(message_id=10)
        bot_mock.send_message.return_value = sent_msg

        user = _make_pm_user(telegram_id="666")
        user_state = _default_user_state()
        fresh_user = self._fresh_user("666")

        power_result = {"duration_minutes": 90.0, "power_changed_at": None}

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch(
                    "bot.services.power_monitor.change_power_state_and_get_duration",
                    AsyncMock(return_value=power_result),
                ):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

        call_args = bot_mock.send_message.call_args
        message_text = call_args[0][1]
        assert "1 год 30 хв" in message_text


# ─── _send_daily_ping_error_alerts ───────────────────────────────────────


class TestSendDailyPingErrorAlerts:
    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def _make_alert(self, telegram_id: str = "111", router_ip: str = "8.8.8.8", last_alert_at=None) -> SimpleNamespace:
        return SimpleNamespace(
            telegram_id=telegram_id,
            router_ip=router_ip,
            last_alert_at=last_alert_at,
        )

    async def test_skips_alert_sent_less_than_24h_ago(self):
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        # last_alert_at only 1 hour ago — should be skipped (< 24h threshold)
        from datetime import timedelta
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        alert = self._make_alert(last_alert_at=recent_time)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                await _send_daily_ping_error_alerts(bot_mock)

        bot_mock.send_message.assert_not_called()

    async def test_skips_alert_when_router_is_now_alive(self):
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        # last_alert_at is old enough (2 days ago)
        old_time = datetime.now(timezone.utc).replace(microsecond=0)
        old_time = old_time.replace(year=old_time.year - 1)
        alert = self._make_alert(last_alert_at=old_time)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                # Router is now alive → deactivate and skip
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=True)):
                    with patch(
                        "bot.services.power_monitor.deactivate_ping_error_alert",
                        new_callable=AsyncMock,
                    ) as mock_deactivate:
                        await _send_daily_ping_error_alerts(bot_mock)

        bot_mock.send_message.assert_not_called()
        mock_deactivate.assert_called_once_with(mock_session, alert.telegram_id)

    async def test_sends_alert_when_router_unreachable_24h_plus(self):
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        sent_msg = SimpleNamespace(message_id=99)
        bot_mock.send_message.return_value = sent_msg

        old_time = datetime.now(timezone.utc).replace(year=2020, microsecond=0)
        alert = self._make_alert(last_alert_at=old_time)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=False)):
                    with patch("bot.services.power_monitor.update_ping_error_alert_time", new_callable=AsyncMock):
                        await _send_daily_ping_error_alerts(bot_mock)

        bot_mock.send_message.assert_called_once()

    async def test_sends_alert_for_null_last_alert_at(self):
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)

        # last_alert_at is None → first alert ever
        alert = self._make_alert(last_alert_at=None)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=False)):
                    with patch("bot.services.power_monitor.update_ping_error_alert_time", new_callable=AsyncMock):
                        await _send_daily_ping_error_alerts(bot_mock)

        bot_mock.send_message.assert_called_once()

    async def test_handles_forbidden_error_deactivates_alert(self):
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        bot_mock.send_message.side_effect = _make_telegram_forbidden()

        old_time = datetime.now(timezone.utc).replace(year=2020, microsecond=0)
        alert = self._make_alert(last_alert_at=old_time)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=False)):
                    with patch(
                        "bot.services.power_monitor.deactivate_ping_error_alert",
                        new_callable=AsyncMock,
                    ) as mock_deactivate_alert, patch(
                        "bot.services.power_monitor.deactivate_user",
                        new_callable=AsyncMock,
                    ) as mock_deactivate_user:
                        await _send_daily_ping_error_alerts(bot_mock)

        mock_deactivate_alert.assert_called_once()
        mock_deactivate_user.assert_called_once_with(mock_session, alert.telegram_id)

    async def test_handles_db_fetch_error_gracefully(self):
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(side_effect=Exception("DB error")),
            ):
                await _send_daily_ping_error_alerts(bot_mock)  # Should not raise

        bot_mock.send_message.assert_not_called()


# ─── Additional _handle_power_state_change branches ──────────────────────


class TestHandlePowerStateChangeMoreBranches:
    """Extra branch coverage for _handle_power_state_change (lines 238-423)."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_db_exception_fresh_user_none_returns_early(self):
        """Lines 238-241: exception before fresh_user assigned → early return."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="100")
        user_state = _default_user_state()

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_user_by_telegram_id",
                AsyncMock(side_effect=RuntimeError("DB exploded")),
            ):
                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_not_called()

    async def test_naive_cooldown_datetime_adds_tz(self):
        """Line 249: naive ISO string gets KYIV_TZ applied; elapsed >> cooldown → notify."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="101")
        user_state = {
            **_default_user_state(),
            "last_notification_at": "2020-01-01T00:00:00",  # naive, very old
        }
        fresh_user = _make_pm_user(telegram_id="101")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_called()

    async def test_cooldown_invalid_string_exception_swallowed(self):
        """Lines 257-258: fromisoformat raises → exception caught, notification still sent."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="102")
        user_state = {
            **_default_user_state(),
            "last_notification_at": "NOT-A-VALID-ISO-DATE",
        }
        fresh_user = _make_pm_user(telegram_id="102")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        # Should not raise; notification sent
        bot_mock.send_message.assert_called()

    async def test_power_changed_at_naive_str_adds_utc(self):
        """Lines 267-269, 272-273: naive ISO str → parsed, tzinfo=None → UTC added."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="103")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="103")
        power_result = {"duration_minutes": 5.0, "power_changed_at": "2024-01-15T10:00:00"}

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=power_result)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

    async def test_power_changed_at_naive_datetime_adds_utc(self):
        """Lines 271, 272-273: naive datetime object → not str branch → UTC added."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="104")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="104")
        power_result = {
            "duration_minutes": 5.0,
            "power_changed_at": datetime(2024, 1, 15, 10, 0),  # naive datetime
        }

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=power_result)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

    async def test_is_scheduled_outage_sets_flag(self):
        """Line 291: find_next_event returns power_on → is_scheduled_outage=True."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="105")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="105")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"data": "x"})):
                            with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                                with patch(
                                    "bot.services.power_monitor.find_next_event",
                                    return_value={"type": "power_on", "time": "2024-01-15T10:00:00"},
                                ):
                                    with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                        await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        call_text = bot_mock.send_message.call_args[0][1]
        assert "Світло має з'явитися" in call_text

    async def test_schedule_fetch_exception_caught(self):
        """Lines 292-293: fetch_schedule_data raises → logged, notification still sent."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="106")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="106")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch(
                            "bot.services.power_monitor.fetch_schedule_data",
                            AsyncMock(side_effect=RuntimeError("schedule failed")),
                        ):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_called()

    async def test_off_scheduled_outage_schedule_text(self):
        """Line 299: new_state=off + scheduled outage → schedule text with appearance time."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="107")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="107")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "a"})):
                            with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                                with patch(
                                    "bot.services.power_monitor.find_next_event",
                                    return_value={"type": "power_on", "time": "2024-01-15T10:00:00"},
                                ):
                                    with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                        await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        call_text = bot_mock.send_message.call_args[0][1]
        assert "Світло має з'явитися" in call_text

    async def test_on_state_next_power_off_with_endtime(self):
        """Lines 304-307: new_state=on, next power_off with endTime → time range text."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="108")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="108")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "a"})):
                            with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                                with patch(
                                    "bot.services.power_monitor.find_next_event",
                                    return_value={
                                        "type": "power_off",
                                        "time": "2024-01-15T10:00:00",
                                        "endTime": "2024-01-15T12:00:00",
                                    },
                                ):
                                    with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                        await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

        call_text = bot_mock.send_message.call_args[0][1]
        assert "Наступне планове" in call_text
        assert " - " in call_text

    async def test_on_state_next_power_off_without_endtime(self):
        """Lines 308-309: new_state=on, next power_off without endTime → start only text."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=1)
        user = _make_pm_user(telegram_id="109")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="109")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "a"})):
                            with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                                with patch(
                                    "bot.services.power_monitor.find_next_event",
                                    return_value={"type": "power_off", "time": "2024-01-15T10:00:00"},
                                ):
                                    with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                        await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

        call_text = bot_mock.send_message.call_args[0][1]
        assert "Наступне планове" in call_text

    async def test_notify_fact_off_false_skips_bot_message(self):
        """Line 339: notify_fact_off=False → send_to_bot=False → no message."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="110")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="110",
            notification_settings=SimpleNamespace(notify_fact_off=False, notify_fact_on=True),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        bot_mock.send_message.assert_not_called()

    async def test_notify_fact_on_false_skips_bot_message(self):
        """Line 341: notify_fact_on=False → send_to_bot=False → no message."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="111111")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="111111",
            notification_settings=SimpleNamespace(notify_fact_off=True, notify_fact_on=False),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

        bot_mock.send_message.assert_not_called()

    async def test_channel_send_happy_path_persists_ids(self):
        """Lines 359-376, 407, 409: channel send → ch_msg_id persisted."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock(side_effect=[
            SimpleNamespace(message_id=42),
            SimpleNamespace(message_id=99),
        ])

        user = _make_pm_user(telegram_id="1120000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1120000",
            channel_config=SimpleNamespace(
                channel_id="9990000",
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            ),
        )

        pt_mock = MagicMock()
        cc_mock = MagicMock()
        db_user_mock = MagicMock()
        db_user_mock.power_tracking = pt_mock
        db_user_mock.channel_config = cc_mock

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user_mock

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        assert bot_mock.send_message.call_count == 2
        assert pt_mock.ch_power_message_id == 99
        assert cc_mock.last_power_message_id == 99

    async def test_channel_send_forbidden(self):
        """Lines 377-378: channel Forbidden → logged, no crash."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock(side_effect=[
            SimpleNamespace(message_id=42),
            _make_telegram_forbidden(),
        ])

        user = _make_pm_user(telegram_id="1130000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1130000",
            channel_config=SimpleNamespace(
                channel_id="8880000",
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            ),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

    async def test_channel_send_generic_exception(self):
        """Lines 379-380: generic exception during channel send → logged."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock(side_effect=[
            SimpleNamespace(message_id=42),
            RuntimeError("network"),
        ])

        user = _make_pm_user(telegram_id="1140000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1140000",
            channel_config=SimpleNamespace(
                channel_id="7770000",
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            ),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

    async def test_channel_notify_fact_off_false(self):
        """Line 361: ch_notify_fact_off=False → channel not sent for off state."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=42)

        user = _make_pm_user(telegram_id="1150000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1150000",
            channel_config=SimpleNamespace(
                channel_id="6660000",
                ch_notify_fact_off=False,
                ch_notify_fact_on=True,
                channel_paused=False,
            ),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        assert bot_mock.send_message.call_count == 1

    async def test_channel_paused_skips_send(self):
        """Line 365: channel_paused=True → channel not sent."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=42)

        user = _make_pm_user(telegram_id="1160000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1160000",
            channel_config=SimpleNamespace(
                channel_id="5550000",
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=True,
            ),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        assert bot_mock.send_message.call_count == 1

    async def test_channel_str_channel_id_fallback(self):
        """Lines 372-373: non-numeric channel_id stays as string."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock(side_effect=[
            SimpleNamespace(message_id=42),
            SimpleNamespace(message_id=99),
        ])

        user = _make_pm_user(telegram_id="1170000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1170000",
            channel_config=SimpleNamespace(
                channel_id="@mychannel",
                ch_notify_fact_off=True,
                ch_notify_fact_on=True,
                channel_paused=False,
            ),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

        assert bot_mock.send_message.call_count == 2

    async def test_session2_persist_exception_logged(self):
        """Lines 413-414: session 2 commit raises → exception logged, no crash."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=42)

        user = _make_pm_user(telegram_id="1180000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(telegram_id="1180000")

        mock_session = _make_mock_session()
        mock_session.commit.side_effect = RuntimeError("commit failed")

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                await _handle_power_state_change(bot_mock, user, "off", "on", user_state)

    async def test_channel_notify_fact_on_false(self):
        """Line 363: ch_notify_fact_on=False → channel not sent for on state."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        bot_mock.send_message.return_value = SimpleNamespace(message_id=42)

        user = _make_pm_user(telegram_id="1170000")
        user_state = _default_user_state()
        fresh_user = _make_pm_user(
            telegram_id="1170000",
            channel_config=SimpleNamespace(
                channel_id="7770000",
                ch_notify_fact_off=True,
                ch_notify_fact_on=False,  # channel off for "on" state
                channel_paused=False,
            ),
        )

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_user_by_telegram_id", AsyncMock(return_value=fresh_user)):
                with patch("bot.services.power_monitor.change_power_state_and_get_duration", AsyncMock(return_value=None)):
                    with patch("bot.services.power_monitor.add_power_history", AsyncMock()):
                        with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                            with patch("bot.services.power_monitor.deactivate_ping_error_alert", AsyncMock()):
                                # new_state="on" → ch_notify_fact_on=False → channel skipped
                                await _handle_power_state_change(bot_mock, user, "on", "off", user_state)

        # Only the user message sent, not the channel
        assert bot_mock.send_message.call_count == 1

    async def test_outer_exception_caught(self):
        """Lines 422-423: exception escaping all inner try/except → outer except."""
        from bot.services.power_monitor import _handle_power_state_change

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="400400")
        user_state = _default_user_state()

        # Patch datetime.now to raise — it's the first line in the outer try,
        # so the exception goes directly to the outer except (422-423).
        # getattr(user, "telegram_id", "?") in the logger still works since user is normal.
        mock_dt = MagicMock()
        mock_dt.now.side_effect = RuntimeError("datetime crash")

        with patch("bot.services.power_monitor.datetime", mock_dt):
            # Should not raise — outer except catches it
            await _handle_power_state_change(bot_mock, user, "off", "on", user_state)


# ─── Additional _check_user_power branches ───────────────────────────────


class TestCheckUserPowerMoreBranches:
    """Extra branch coverage for _check_user_power (lines 480-601)."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        for state in list(pm._user_states.values()):
            task = state.get("debounce_task")
            if task and not task.done():
                task.cancel()
        pm._user_states.clear()

    async def test_first_check_db_user_with_tracking_persists_state(self):
        """Lines 480-482: first check, no DB record, db_user found → state written."""
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2001")  # power_tracking.power_state = None

        db_pt = SimpleNamespace(power_state=None, power_changed_at=None)
        db_user = SimpleNamespace(power_tracking=db_pt)

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        assert db_pt.power_state == "on"

    async def test_first_check_db_session_exception_logged(self):
        """Lines 483-484: DB exception on first check initial state write → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2002")

        mock_session = _make_mock_session()
        mock_session.execute.side_effect = RuntimeError("DB error")

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        # State is still seeded in memory
        assert pm._user_states["2002"]["current_state"] == "on"

    async def test_flap_cancel_with_db_user_clears_pending(self):
        """Lines 513-515: flapping, db_user found → pending cleared in DB."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2003")

        mock_task = MagicMock()
        mock_task.done.return_value = False

        pm._user_states["2003"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "pending_state": "off",
            "debounce_task": mock_task,
        }

        db_pt = SimpleNamespace(pending_power_state="off", pending_power_change_at=None)
        db_user = SimpleNamespace(power_tracking=db_pt)

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        assert db_pt.pending_power_state is None

    async def test_flap_cancel_db_exception_logged(self):
        """Lines 516-517: flapping, DB session raises → exception logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2004")

        mock_task = MagicMock()
        mock_task.done.return_value = False

        pm._user_states["2004"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "pending_state": "off",
            "debounce_task": mock_task,
        }

        mock_session = _make_mock_session()
        mock_session.execute.side_effect = RuntimeError("DB error")

        with _patch_pm_async_session(mock_session):
            await _check_user_power(bot_mock, user, is_available=True)

        # pending_state cleared in memory despite DB error
        assert pm._user_states["2004"]["pending_state"] is None

    async def test_new_state_cancels_existing_task(self):
        """Lines 528-529: existing debounce task cancelled when new state arrives."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2005")

        existing_task = MagicMock()
        existing_task.done.return_value = False

        # pending_state="on" (same as current, non-None), new_state="off"
        pm._user_states["2005"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "pending_state": "on",
            "debounce_task": existing_task,
        }

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                await _check_user_power(bot_mock, user, is_available=False)

        existing_task.cancel.assert_called_once()
        # switch_count incremented (pending was not None)
        assert pm._user_states["2005"]["switch_count"] >= 1
        # Clean up created task
        new_task = pm._user_states["2005"]["debounce_task"]
        if new_task and not new_task.done():
            new_task.cancel()

    async def test_switch_count_incremented_when_pending_not_none(self):
        """Lines 539-540: switch_count incremented when pending_state was already set."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2006")

        pm._user_states["2006"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
            "pending_state": "on",  # non-None, but != new_state "off"
            "switch_count": 3,
            "debounce_task": None,
        }

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                await _check_user_power(bot_mock, user, is_available=False)

        assert pm._user_states["2006"]["switch_count"] == 4
        task = pm._user_states["2006"]["debounce_task"]
        if task and not task.done():
            task.cancel()

    async def test_persist_pending_with_db_user(self):
        """Lines 555-557: new state change, db_user found → pending state written to DB."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2007")

        pm._user_states["2007"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        db_pt = SimpleNamespace(pending_power_state=None, pending_power_change_at=None)
        db_user = SimpleNamespace(power_tracking=db_pt)

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = db_user

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                await _check_user_power(bot_mock, user, is_available=False)

        assert db_pt.pending_power_state == "off"
        task = pm._user_states["2007"]["debounce_task"]
        if task and not task.done():
            task.cancel()

    async def test_persist_pending_db_exception_logged(self):
        """Lines 558-559: DB exception on pending persist → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2008")

        pm._user_states["2008"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        # First execute call raises (persist pending); second for debounce
        mock_session = _make_mock_session()
        mock_session.execute.side_effect = RuntimeError("DB write failed")

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                await _check_user_power(bot_mock, user, is_available=False)

        # State machine still proceeds — task created
        assert pm._user_states["2008"]["pending_state"] == "off"
        task = pm._user_states["2008"]["debounce_task"]
        if task and not task.done():
            task.cancel()

    async def test_debounce_fetch_exception_uses_default(self):
        """Lines 565-567: _get_debounce_seconds raises → DEFAULT_DEBOUNCE_S used."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2009")

        pm._user_states["2009"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()

        async def mock_session_factory():
            yield mock_session

        # Make _get_debounce_seconds raise by raising in async_session context
        call_count = [0]

        @asynccontextmanager
        async def failing_session():
            call_count[0] += 1
            if call_count[0] >= 2:  # second async_session call (debounce fetch) fails
                raise RuntimeError("DB down")
            yield mock_session

        with patch("bot.services.power_monitor.async_session", side_effect=failing_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="5")):
                await _check_user_power(bot_mock, user, is_available=False)

        task = pm._user_states["2009"]["debounce_task"]
        if task and not task.done():
            task.cancel()

    async def test_debounce_zero_uses_min_stabilization(self):
        """Lines 569-570: debounce_s=0 → replaced with POWER_MIN_STABILIZATION_S."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2010")

        pm._user_states["2010"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="0")):
                await _check_user_power(bot_mock, user, is_available=False)

        assert pm._user_states["2010"]["pending_state"] == "off"
        task = pm._user_states["2010"]["debounce_task"]
        if task and not task.done():
            task.cancel()

    async def test_confirm_state_runs_and_calls_handle(self):
        """Lines 579-591: _confirm_state task runs → state updated → handle called."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2011")

        pm._user_states["2011"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", AsyncMock()):
                    with patch(
                        "bot.services.power_monitor._handle_power_state_change",
                        AsyncMock(),
                    ) as mock_handle:
                        await _check_user_power(bot_mock, user, is_available=False)
                        task = pm._user_states.get("2011", {}).get("debounce_task")
                        if task:
                            await task

        mock_handle.assert_called_once()

    async def test_confirm_state_cancelled_silently(self):
        """Lines 592-593: CancelledError in _confirm_state → caught silently."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2012")

        pm._user_states["2012"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()

        import asyncio

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                # sleep raises CancelledError → caught at 592-593
                with patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError())):
                    await _check_user_power(bot_mock, user, is_available=False)
                    task = pm._user_states.get("2012", {}).get("debounce_task")
                    if task:
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

    async def test_confirm_state_exception_logged(self):
        """Lines 594-595: exception in _confirm_state → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2013")

        pm._user_states["2013"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", AsyncMock()):
                    with patch(
                        "bot.services.power_monitor._handle_power_state_change",
                        AsyncMock(side_effect=RuntimeError("handle error")),
                    ):
                        await _check_user_power(bot_mock, user, is_available=False)
                        task = pm._user_states.get("2013", {}).get("debounce_task")
                        if task:
                            await task  # exception caught at 594-595

    async def test_outer_exception_caught(self):
        """Lines 600-601: check_router_http raises → outer except catches it."""
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="2099")

        # check_router_http raising with is_available=None propagates to outer except
        with patch(
            "bot.services.power_monitor.check_router_http",
            AsyncMock(side_effect=RuntimeError("ping crash")),
        ):
            # Should not raise
            await _check_user_power(bot_mock, user)


# ─── _check_all_ips exception ────────────────────────────────────────────


class TestCheckAllIpsException:
    """Lines 667-669: exception in _check_all_ips body → caught and logged."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_exception_in_check_all_ips_caught(self):
        """Lines 667-669: get_users_with_ip raises → exception caught."""
        from bot.services.power_monitor import _check_all_ips

        bot_mock = AsyncMock()

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_users_with_ip_cursor",
                AsyncMock(side_effect=RuntimeError("DB down")),
            ):
                with patch("bot.services.power_monitor.sentry_sdk") as mock_sentry:
                    await _check_all_ips(bot_mock)

        mock_sentry.capture_exception.assert_called_once()


# ─── _save_user_state_to_db ───────────────────────────────────────────────


class TestSaveUserStateToDb:
    """Full coverage of _save_user_state_to_db (lines 677-701)."""

    async def test_happy_path_calls_upsert(self):
        """Lines 677-700: valid state → upsert_user_power_state called."""
        from bot.services.power_monitor import _save_user_state_to_db

        state = {**_default_user_state(), "current_state": "on"}

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.upsert_user_power_state",
                AsyncMock(),
            ) as mock_upsert:
                await _save_user_state_to_db("123", state)

        mock_upsert.assert_called_once()
        assert mock_upsert.call_args[0][1] == "123"

    async def test_with_valid_iso_last_notification_at(self):
        """Lines 680-683: valid ISO string → converted to datetime."""
        from bot.services.power_monitor import _save_user_state_to_db

        state = {
            **_default_user_state(),
            "last_notification_at": "2024-01-15T10:00:00+02:00",
        }

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.upsert_user_power_state", AsyncMock()) as mock_upsert:
                await _save_user_state_to_db("456", state)

        last_notif = mock_upsert.call_args[1]["last_notification_at"]
        assert isinstance(last_notif, datetime)

    async def test_with_invalid_iso_string_silently_ignored(self):
        """Lines 683-684: invalid ISO → fromisoformat raises → last_notif_dt stays None."""
        from bot.services.power_monitor import _save_user_state_to_db

        state = {
            **_default_user_state(),
            "last_notification_at": "not-a-date",
        }

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.upsert_user_power_state", AsyncMock()) as mock_upsert:
                await _save_user_state_to_db("789", state)

        last_notif = mock_upsert.call_args[1]["last_notification_at"]
        assert last_notif is None

    async def test_db_exception_logged(self):
        """Lines 700-701: upsert raises → outer except catches."""
        from bot.services.power_monitor import _save_user_state_to_db

        state = {**_default_user_state(), "current_state": "off"}

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.upsert_user_power_state",
                AsyncMock(side_effect=RuntimeError("DB fail")),
            ):
                # Should not raise
                await _save_user_state_to_db("999", state)


# ─── _save_all_user_states missing lines ─────────────────────────────────


class TestSaveAllUserStatesMissingLines:
    """Line 718-719: fromisoformat exception (pass) path."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._dirty_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._dirty_states.clear()

    async def test_invalid_iso_last_notification_at_silently_ignored(self):
        """Lines 718-719: invalid last_notification_at → fromisoformat raises → pass."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _save_all_user_states

        pm._user_states["xyz"] = {
            **_default_user_state(),
            "current_state": "on",
            "last_notification_at": "not-an-iso-date",
        }
        pm._dirty_states.add("xyz")

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.batch_upsert_user_power_states",
                AsyncMock(),
            ) as mock_batch:
                await _save_all_user_states()

        mock_batch.assert_called_once()
        rows = mock_batch.call_args[0][1]
        assert rows[0]["last_notification_at"] is None


# ─── _restart_pending_debounce_tasks ─────────────────────────────────────


class TestRestartPendingDebounceTasks:
    """Coverage for _restart_pending_debounce_tasks (lines 785-851)."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        for state in list(pm._user_states.values()):
            task = state.get("debounce_task")
            if task and not task.done():
                task.cancel()
        pm._user_states.clear()

    async def test_no_pending_states_does_nothing(self):
        """Lines 785-793: no pending states → loop body skipped."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["no_pending"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": None,
        }

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="5")):
                await _restart_pending_debounce_tasks(bot_mock)

        assert pm._user_states["no_pending"]["debounce_task"] is None

    async def test_debounce_fetch_exception_uses_default(self):
        """Lines 789-791: _get_debounce_seconds raises → DEFAULT_DEBOUNCE_S used."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["pend_exc"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": None,
        }

        bot_mock = AsyncMock()

        @asynccontextmanager
        async def failing_session():
            raise RuntimeError("DB down")
            yield  # pragma: no cover

        with patch("bot.services.power_monitor.async_session", side_effect=failing_session):
            await _restart_pending_debounce_tasks(bot_mock)

        task = pm._user_states["pend_exc"]["debounce_task"]
        if task and not task.done():
            task.cancel()

    async def test_pending_with_datetime_calculates_remaining(self):
        """Lines 802-807: pending_state_time is datetime → elapsed calculated."""
        from zoneinfo import ZoneInfo

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        KYIV_TZ_local = ZoneInfo("Europe/Kyiv")
        # pending_state_time 10 minutes ago, debounce=300s → remaining ~240s
        past_time = datetime.now(KYIV_TZ_local).replace(microsecond=0)
        from datetime import timedelta
        past_time = past_time - timedelta(minutes=10)

        pm._user_states["pend_dt"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": past_time,
            "original_change_time": past_time,
        }

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="5")):
                await _restart_pending_debounce_tasks(bot_mock)

        task = pm._user_states["pend_dt"]["debounce_task"]
        assert task is not None
        if not task.done():
            task.cancel()

    async def test_confirm_restored_runs_handle_when_fresh_user_found(self):
        """Lines 822-839: _confirm_restored task runs → get_user_by_telegram_id → handle called."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["pend_run"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": None,
        }

        fresh_user = _make_pm_user(telegram_id="pend_run")
        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", AsyncMock()):
                    with patch(
                        "bot.services.power_monitor.get_user_by_telegram_id",
                        AsyncMock(return_value=fresh_user),
                    ):
                        with patch(
                            "bot.services.power_monitor._handle_power_state_change",
                            AsyncMock(),
                        ) as mock_handle:
                            await _restart_pending_debounce_tasks(bot_mock)
                            task = pm._user_states.get("pend_run", {}).get("debounce_task")
                            if task:
                                await task

        mock_handle.assert_called_once()

    async def test_confirm_restored_skips_when_fresh_user_none(self):
        """Lines 840-841: _confirm_restored, get_user_by_telegram_id returns None → skipped."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["pend_no_user"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": None,
        }

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", AsyncMock()):
                    with patch(
                        "bot.services.power_monitor.get_user_by_telegram_id",
                        AsyncMock(return_value=None),
                    ):
                        with patch(
                            "bot.services.power_monitor._handle_power_state_change",
                            AsyncMock(),
                        ) as mock_handle:
                            await _restart_pending_debounce_tasks(bot_mock)
                            task = pm._user_states.get("pend_no_user", {}).get("debounce_task")
                            if task:
                                await task

        mock_handle.assert_not_called()

    async def test_confirm_restored_pending_changed_skips(self):
        """Lines 827-828: pending_state changed after task created → task returns early."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["pend_changed"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": None,
        }

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        async def mock_sleep(duration):
            # Change pending_state mid-sleep to trigger early return
            if "pend_changed" in pm._user_states:
                pm._user_states["pend_changed"]["pending_state"] = None

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", new=mock_sleep):
                    with patch(
                        "bot.services.power_monitor._handle_power_state_change",
                        AsyncMock(),
                    ) as mock_handle:
                        await _restart_pending_debounce_tasks(bot_mock)
                        task = pm._user_states.get("pend_changed", {}).get("debounce_task")
                        if task:
                            await task

        mock_handle.assert_not_called()

    async def test_confirm_restored_cancelled_silently(self):
        """Lines 842-843: CancelledError in _confirm_restored → caught silently."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["pend_cancel"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": None,
        }

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError())):
                    await _restart_pending_debounce_tasks(bot_mock)
                    task = pm._user_states.get("pend_cancel", {}).get("debounce_task")
                    if task:
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

    async def test_confirm_restored_exception_logged(self):
        """Lines 844-845: exception in _confirm_restored → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        pm._user_states["pend_exc2"] = {
            **_default_user_state(),
            "current_state": "on",
            "pending_state": "off",
            "pending_state_time": None,
        }

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                with patch("asyncio.sleep", AsyncMock()):
                    with patch(
                        "bot.services.power_monitor.get_user_by_telegram_id",
                        AsyncMock(side_effect=RuntimeError("DB error in restore")),
                    ):
                        await _restart_pending_debounce_tasks(bot_mock)
                        task = pm._user_states.get("pend_exc2", {}).get("debounce_task")
                        if task:
                            await task  # exception caught at 844-845

    async def test_naive_pending_state_time_adds_tz(self):
        """Line 805: pending_state_time is naive datetime → tzinfo added."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _restart_pending_debounce_tasks

        bot_mock = AsyncMock()
        # Naive datetime — tzinfo is None → line 805 executes
        naive_dt = datetime(2024, 1, 15, 10, 0)
        pm._user_states["pend_naive"] = {
            **_default_user_state(),
            "pending_state": "off",
            "pending_state_time": naive_dt,
            "current_state": "on",
            "debounce_task": None,
        }

        with patch("asyncio.sleep", AsyncMock()):
            with patch("bot.services.power_monitor._handle_power_state_change", AsyncMock()):
                await _restart_pending_debounce_tasks(bot_mock)
                task = pm._user_states.get("pend_naive", {}).get("debounce_task")
                if task:
                    await task


# ─── power_monitor_loop ──────────────────────────────────────────────────


class TestPowerMonitorLoop:
    """Coverage for power_monitor_loop (lines 857-906)."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()
        pm._running = False

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._running = False
        pm._user_states.clear()

    async def test_basic_loop_starts_and_stops(self):
        """Lines 857-906: loop runs one iteration then stops."""

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()
        sleep_count = [0]

        async def mock_sleep(t):
            sleep_count[0] += 1
            if sleep_count[0] >= 1:
                pm._running = False

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
                        with _patch_pm_async_session(mock_session):
                            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                                with patch("asyncio.sleep", new=mock_sleep):
                                    await power_monitor_loop(bot_mock)

        assert not pm._running

    async def test_loop_initial_check_timeout(self):
        """Lines 870-873: initial asyncio.wait_for raises TimeoutError → logged."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()

        async def mock_wait_for(coro, timeout):
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()

        async def mock_sleep(t):
            pm._running = False

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
                        with _patch_pm_async_session(mock_session):
                            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                                with patch("asyncio.wait_for", new=mock_wait_for):
                                    with patch("asyncio.sleep", new=mock_sleep):
                                        await power_monitor_loop(bot_mock)

    async def test_loop_initial_check_exception(self):
        """Lines 872-873: initial check raises non-timeout exception → logged."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()

        async def mock_wait_for(coro, timeout):
            if hasattr(coro, "close"):
                coro.close()
            raise RuntimeError("initial check failed")

        async def mock_sleep(t):
            pm._running = False

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
                        with _patch_pm_async_session(mock_session):
                            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                                with patch("asyncio.wait_for", new=mock_wait_for):
                                    with patch("asyncio.sleep", new=mock_sleep):
                                        await power_monitor_loop(bot_mock)

    async def test_loop_interval_db_exception_uses_default(self):
        """Lines 883-885: interval DB read raises → DEFAULT_CHECK_INTERVAL_S used."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()
        sleep_count = [0]

        async def mock_sleep(t):
            sleep_count[0] += 1
            if sleep_count[0] >= 1:
                pm._running = False

        @asynccontextmanager
        async def failing_session():
            raise RuntimeError("DB interval fail")
            yield  # pragma: no cover

        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
                        with patch("bot.services.power_monitor.async_session", side_effect=failing_session):
                            with patch("asyncio.sleep", new=mock_sleep):
                                await power_monitor_loop(bot_mock)

    async def test_loop_check_timeout(self):
        """Lines 894-895: loop iteration asyncio.wait_for timeout → logged."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()
        sleep_count = [0]

        async def mock_sleep(t):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                pm._running = False

        call_count = [0]
        async def mock_wait_for(coro, timeout):
            call_count[0] += 1
            if call_count[0] >= 2:  # second wait_for (loop iteration) times out
                if hasattr(coro, "close"):
                    coro.close()
                raise asyncio.TimeoutError()
            return await coro

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
                        with _patch_pm_async_session(mock_session):
                            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                                with patch("asyncio.wait_for", new=mock_wait_for):
                                    with patch("asyncio.sleep", new=mock_sleep):
                                        await power_monitor_loop(bot_mock)

    async def test_loop_check_exception_with_sentry(self):
        """Lines 896-900: loop check raises exception → logged + sentry capture."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()
        sleep_count = [0]

        async def mock_sleep(t):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                pm._running = False

        call_count = [0]
        async def mock_wait_for(coro, timeout):
            call_count[0] += 1
            if call_count[0] >= 2:
                if hasattr(coro, "close"):
                    coro.close()
                raise RuntimeError("check failed")
            return await coro

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
                        with _patch_pm_async_session(mock_session):
                            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                                with patch("asyncio.wait_for", new=mock_wait_for):
                                    with patch("asyncio.sleep", new=mock_sleep):
                                        with patch("bot.services.power_monitor.sentry_sdk") as mock_sentry:
                                            await power_monitor_loop(bot_mock)

        mock_sentry.capture_exception.assert_called()

    async def test_loop_periodic_save_triggered(self):
        """Lines 902-906: periodic save triggered when time threshold exceeded."""

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import power_monitor_loop

        bot_mock = AsyncMock()

        # Return base_time first, then base_time+120 to trigger save (save_interval=60)
        time_values = iter([100.0, 200.0, 200.0])
        mock_loop = MagicMock()
        mock_loop.time.side_effect = lambda: next(time_values, 200.0)

        sleep_count = [0]

        async def mock_sleep(t):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:  # stop after second sleep (one full loop iteration)
                pm._running = False

        mock_session = _make_mock_session()
        with patch("bot.services.power_monitor._restore_user_states", AsyncMock()):
            with patch("bot.services.power_monitor._restart_pending_debounce_tasks", AsyncMock()):
                with patch("bot.services.power_monitor._check_all_ips", AsyncMock()):
                    with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()) as mock_save:
                        with _patch_pm_async_session(mock_session):
                            with patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="1")):
                                with patch("asyncio.sleep", new=mock_sleep):
                                    with patch("asyncio.get_running_loop", return_value=mock_loop):
                                        await power_monitor_loop(bot_mock)

        mock_save.assert_called()


# ─── save_states_on_shutdown exceptions ──────────────────────────────────


class TestSaveStatesOnShutdownExceptions:
    """Lines 933-937: CancelledError and Exception paths for connector close."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._http_connector = None

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._http_connector = None

    async def test_connector_close_cancelled_error_reraises(self):
        """Lines 933-935: shield raises CancelledError → await close_task, reraise."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = MagicMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
            with patch("asyncio.shield", AsyncMock(side_effect=asyncio.CancelledError())):
                with pytest.raises(asyncio.CancelledError):
                    await save_states_on_shutdown()

        mock_connector.close.assert_awaited()

    async def test_connector_close_generic_exception_logged(self):
        """Lines 936-937: shield raises generic Exception → logged, no crash."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import save_states_on_shutdown

        mock_connector = MagicMock()
        mock_connector.closed = False
        mock_connector.close = AsyncMock()
        pm._http_connector = mock_connector

        with patch("bot.services.power_monitor._save_all_user_states", AsyncMock()):
            with patch("asyncio.shield", AsyncMock(side_effect=RuntimeError("close failed"))):
                await save_states_on_shutdown()  # Should not raise


# ─── daily_ping_error_loop ────────────────────────────────────────────────


class TestDailyPingErrorLoop:
    """Coverage for daily_ping_error_loop (lines 946-956)."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._running = False

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._running = False

    async def test_loop_runs_and_sends_alerts(self):
        """Lines 946-951: loop runs, sleep returns, alerts sent, then stops."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot_mock = AsyncMock()
        pm._running = True
        send_call_count = [0]

        async def mock_send(b):
            send_call_count[0] += 1
            pm._running = False  # stop after first alert

        with patch("asyncio.sleep", AsyncMock()):  # return immediately
            with patch("bot.services.power_monitor._send_daily_ping_error_alerts", new=mock_send):
                await daily_ping_error_loop(bot_mock)

        assert send_call_count[0] == 1

    async def test_loop_exits_on_running_false_after_sleep(self):
        """Lines 949-950: _running=False after sleep → break (before send)."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot_mock = AsyncMock()
        pm._running = True

        async def mock_sleep(t):
            pm._running = False  # cleared during sleep

        with patch("asyncio.sleep", new=mock_sleep):
            with patch("bot.services.power_monitor._send_daily_ping_error_alerts", AsyncMock()) as mock_alerts:
                await daily_ping_error_loop(bot_mock)

        mock_alerts.assert_not_called()

    async def test_loop_cancelled_error_breaks(self):
        """Lines 952-953: asyncio.CancelledError in sleep → break."""
        import asyncio

        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot_mock = AsyncMock()
        pm._running = True

        with patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError())):
            await daily_ping_error_loop(bot_mock)

        # CancelledError breaks the loop; _running is unchanged (still True from setup)
        assert pm._running is True

    async def test_loop_exception_sleeps_and_retries(self):
        """Lines 954-956: exception → logged → sleep(60) → next iteration."""
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import daily_ping_error_loop

        bot_mock = AsyncMock()
        pm._running = True
        sleep_calls = []

        async def mock_sleep(t):
            sleep_calls.append(t)
            if len(sleep_calls) >= 2:  # after retry sleep(60), stop
                pm._running = False

        async def mock_send_raises(_bot):
            raise RuntimeError("alert error")

        with patch("asyncio.sleep", new=mock_sleep):
            with patch(
                "bot.services.power_monitor._send_daily_ping_error_alerts",
                new=mock_send_raises,
            ):
                await daily_ping_error_loop(bot_mock)

        assert 60 in sleep_calls  # retry sleep after exception


# ─── _send_daily_ping_error_alerts missing lines ─────────────────────────


class TestSendDailyPingErrorAlertsMoreBranches:
    """Lines 976, 1027-1030: additional branches in _send_daily_ping_error_alerts."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def _make_alert(self, telegram_id="111", router_ip="8.8.8.8", last_alert_at=None):
        return SimpleNamespace(
            telegram_id=telegram_id,
            router_ip=router_ip,
            last_alert_at=last_alert_at,
        )

    async def test_naive_last_alert_at_adds_utc(self):
        """Line 976: naive last_alert_at → tzinfo added, elapsed checked."""
        from datetime import timedelta

        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        # Naive datetime, only 1 hour ago → elapsed < 86400 → skip
        naive_recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        alert = self._make_alert(last_alert_at=naive_recent)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                await _send_daily_ping_error_alerts(bot_mock)

        bot_mock.send_message.assert_not_called()

    async def test_send_generic_exception_logged(self):
        """Lines 1027-1028: generic exception in retry_bot_call → logged."""
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock(return_value=None)
        old_time = datetime.now(timezone.utc).replace(year=2020, microsecond=0)
        alert = self._make_alert(last_alert_at=old_time)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                with patch("bot.services.power_monitor.check_router_http", AsyncMock(return_value=False)):
                    with patch(
                        "bot.services.power_monitor.retry_bot_call",
                        AsyncMock(side_effect=RuntimeError("network error")),
                    ):
                        # Should not raise — exception logged, not re-raised
                        await _send_daily_ping_error_alerts(bot_mock)

    async def test_outer_per_alert_exception_logged(self):
        """Lines 1029-1030: exception in per-alert processing → outer except catches."""
        from bot.services.power_monitor import _send_daily_ping_error_alerts

        bot_mock = AsyncMock()
        old_time = datetime.now(timezone.utc).replace(year=2020, microsecond=0)
        alert = self._make_alert(last_alert_at=old_time)

        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.get_active_ping_error_alerts_cursor",
                AsyncMock(return_value=[alert]),
            ):
                with patch(
                    "bot.services.power_monitor.check_router_http",
                    AsyncMock(side_effect=RuntimeError("ping crash")),
                ):
                    # Should not raise — outer per-alert except catches it
                    await _send_daily_ping_error_alerts(bot_mock)


# ─── update_power_notifications_on_schedule_change ───────────────────────


def _make_upnsc_user(
    telegram_id="3001",
    current_state="off",
    bot_msg_id=None,
    alert_off_id=None,
    alert_on_id=None,
    ch_msg_id=None,
    power_changed_at=None,
    channel_config=None,
):
    """Build a mock user for update_power_notifications_on_schedule_change tests."""
    pt = SimpleNamespace(
        power_state=current_state,
        bot_power_message_id=bot_msg_id,
        alert_off_message_id=alert_off_id,
        alert_on_message_id=alert_on_id,
        ch_power_message_id=ch_msg_id,
        power_changed_at=power_changed_at,
    )
    return SimpleNamespace(
        telegram_id=telegram_id,
        id=1,
        region="kyiv",
        queue="1.1",
        power_tracking=pt,
        channel_config=channel_config,
    )


class TestUpdatePowerNotificationsOnScheduleChange:
    """Full coverage for update_power_notifications_on_schedule_change (1044-1237)."""

    def _mock_session_with_users(self, users):
        """Return mock session whose execute yields the given users list."""
        mock_session = _make_mock_session()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = users
        mock_session.execute = AsyncMock(return_value=result_mock)
        return mock_session

    async def test_fetch_schedule_data_returns_none_returns_early(self):
        """Lines 1046-1047: fetch_schedule_data returns falsy → return immediately."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value=None)):
                await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_not_called()

    async def test_fetch_schedule_exception_returns_early(self):
        """Lines 1050-1052: fetch_schedule_data raises → logged, return."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        with _patch_pm_async_session(mock_session):
            with patch(
                "bot.services.power_monitor.fetch_schedule_data",
                AsyncMock(side_effect=RuntimeError("schedule fail")),
            ):
                await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_not_called()

    async def test_users_fetch_exception_returns_early(self):
        """Lines 1070-1072: DB session for users raises → logged, return."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()
        mock_session.execute.side_effect = RuntimeError("DB users fail")

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch("bot.services.power_monitor.find_next_event", return_value=None):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_not_called()

    async def test_user_without_power_tracking_skipped(self):
        """Lines 1079-1080: user.power_tracking is None → continue."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = SimpleNamespace(telegram_id="3001", power_tracking=None, channel_config=None)
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch("bot.services.power_monitor.find_next_event", return_value=None):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_not_called()

    async def test_user_state_not_off_or_on_skipped(self):
        """Lines 1090-1091: current_state not in (off, on) → continue."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3002", current_state="pending", bot_msg_id=5)
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch("bot.services.power_monitor.find_next_event", return_value=None):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_not_called()

    async def test_bot_msg_id_fallback_off_state(self):
        """Lines 1086-1087: bot_power_message_id=None, off → alert_off_message_id used."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3003",
            current_state="off",
            bot_msg_id=None,
            alert_off_id=77,
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "2024-01-15T10:00:00"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_called_once()
        call_kwargs = bot_mock.edit_message_text.call_args[1]
        assert call_kwargs["message_id"] == 77

    async def test_bot_msg_id_fallback_on_state(self):
        """Lines 1088-1089: bot_power_message_id=None, on → alert_on_message_id used."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3004",
            current_state="on",
            bot_msg_id=None,
            alert_on_id=88,
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "2024-01-15T10:00:00"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_called_once()
        call_kwargs = bot_mock.edit_message_text.call_args[1]
        assert call_kwargs["message_id"] == 88

    async def test_next_event_power_off_on_state_with_endtime(self):
        """Lines 1093-1098: current=on, next power_off with endTime → range schedule line."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3005", current_state="on", bot_msg_id=10)
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "T10", "endTime": "T12"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        call_text = bot_mock.edit_message_text.call_args[1]["text"]
        assert "Наступне планове" in call_text
        assert " - " in call_text

    async def test_next_event_power_off_on_state_no_endtime(self):
        """Line 1099: current=on, next power_off without endTime → start-only."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3006", current_state="on", bot_msg_id=10)
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        call_text = bot_mock.edit_message_text.call_args[1]["text"]
        assert "Наступне планове" in call_text

    async def test_next_event_power_on_off_state(self):
        """Lines 1100-1103: current=off, next power_on → appearance time schedule line."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3007", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        call_text = bot_mock.edit_message_text.call_args[1]["text"]
        assert "з'явитися" in call_text

    async def test_no_matching_next_event_schedule_line_none(self):
        """Lines 1104-1105: no matching event → new_schedule_line=None → no edit."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3008", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "T10"},  # wrong type for off state
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_not_called()

    async def test_edit_off_message_with_power_changed_at(self):
        """Lines 1111-1126: edit for off state with power_changed_at set."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3009",
            current_state="off",
            bot_msg_id=10,
            power_changed_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "2024-01-15T12:00:00"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_called_once()
        text = bot_mock.edit_message_text.call_args[1]["text"]
        assert "Світло зникло" in text

    async def test_edit_off_message_naive_power_changed_at(self):
        """Lines 1114-1115: power_changed_at naive → UTC added."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3010",
            current_state="off",
            bot_msg_id=10,
            power_changed_at=datetime(2024, 1, 15, 10, 0),  # naive
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "2024-01-15T12:00:00"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_called_once()

    async def test_edit_on_message_success(self):
        """Lines 1127-1132: edit for on state succeeds."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3011",
            current_state="on",
            bot_msg_id=20,
            power_changed_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "2024-01-15T14:00:00"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_called_once()
        text = bot_mock.edit_message_text.call_args[1]["text"]
        assert "з'явилося" in text

    async def test_edit_bot_message_not_modified_ignored(self):
        """Lines 1141-1142: TelegramBadRequest 'not modified' → silently ignored."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3012", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message is not modified",
            )
        )
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_edit_bot_message_not_found_clears_id(self):
        """Lines 1143-1156: 'message to edit not found' → DB clear of message IDs."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3013", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )

        db_pt = MagicMock()
        db_user_mock = MagicMock()
        db_user_mock.power_tracking = db_pt

        call_count = [0]

        @asynccontextmanager
        async def multi_session():
            call_count[0] += 1
            session = _make_mock_session()
            if call_count[0] >= 2:  # second session for DB clear
                session.execute.return_value.scalars.return_value.first.return_value = db_user_mock
            else:
                result_mock = MagicMock()
                result_mock.scalars.return_value.all.return_value = [user]
                session.execute = AsyncMock(return_value=result_mock)
            yield session

        with patch("bot.services.power_monitor.async_session", side_effect=multi_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        assert db_pt.bot_power_message_id is None

    async def test_edit_bot_message_not_found_db_clear_exception(self):
        """Lines 1157-1162: 'not found', DB clear raises → logged."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3014", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )

        call_count = [0]

        @asynccontextmanager
        async def multi_session():
            call_count[0] += 1
            session = _make_mock_session()
            if call_count[0] == 1:
                result_mock = MagicMock()
                result_mock.scalars.return_value.all.return_value = [user]
                session.execute = AsyncMock(return_value=result_mock)
            else:
                session.execute.side_effect = RuntimeError("DB clear fail")
            yield session

        with patch("bot.services.power_monitor.async_session", side_effect=multi_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_edit_bot_message_bad_request_other(self):
        """Lines 1163-1166: other TelegramBadRequest message → debug logged."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3015", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: some other error",
            )
        )
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_edit_bot_message_generic_exception(self):
        """Lines 1167-1168: generic exception during edit → debug logged."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3016", current_state="off", bot_msg_id=10)
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(side_effect=RuntimeError("network"))
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_channel_edit_from_ch_power_message_id(self):
        """Line 1170: ch_msg_id from pt.ch_power_message_id."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3017",
            current_state="off",
            bot_msg_id=10,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="9001", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        assert bot_mock.edit_message_text.call_count == 2

    async def test_channel_edit_from_last_power_message_id(self):
        """Line 1171: ch_msg_id from cc.last_power_message_id when pt.ch_power_message_id is None."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3018",
            current_state="off",
            bot_msg_id=10,
            ch_msg_id=None,
            channel_config=SimpleNamespace(channel_id="9002", last_power_message_id=66),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        assert bot_mock.edit_message_text.call_count == 2

    async def test_channel_edit_str_channel_id(self):
        """Lines 1177-1178: non-numeric channel_id → fallback to string."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3019",
            current_state="off",
            bot_msg_id=10,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="@mychannel", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        assert bot_mock.edit_message_text.call_count == 2
        # Second call (channel) uses string channel_id
        ch_call = bot_mock.edit_message_text.call_args_list[1]
        assert ch_call[1]["chat_id"] == "@mychannel"

    async def test_channel_edit_on_state_with_power_changed_at(self):
        """Lines 1182-1203: channel edit for on state with power_changed_at."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3020",
            current_state="on",
            bot_msg_id=10,
            ch_msg_id=55,
            power_changed_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            channel_config=SimpleNamespace(channel_id="9003", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "T14"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        assert bot_mock.edit_message_text.call_count == 2

    async def test_channel_edit_not_modified_ignored(self):
        """Lines 1212-1213: channel edit 'not modified' → silently ignored."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3021",
            current_state="off",
            bot_msg_id=None,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="9004", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message is not modified",
            )
        )
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_channel_edit_not_found_clears_ids(self):
        """Lines 1214-1231: channel 'not found' → clears last_power_message_id."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3022",
            current_state="off",
            bot_msg_id=None,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="9005", last_power_message_id=55),
        )
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )

        db_cc = MagicMock()
        db_pt = MagicMock()
        db_user_mock = MagicMock()
        db_user_mock.channel_config = db_cc
        db_user_mock.power_tracking = db_pt

        call_count = [0]

        @asynccontextmanager
        async def multi_session():
            call_count[0] += 1
            session = _make_mock_session()
            if call_count[0] == 1:
                result_mock = MagicMock()
                result_mock.scalars.return_value.all.return_value = [user]
                session.execute = AsyncMock(return_value=result_mock)
            else:
                session.execute.return_value.scalars.return_value.first.return_value = db_user_mock
            yield session

        with patch("bot.services.power_monitor.async_session", side_effect=multi_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        assert db_cc.last_power_message_id is None
        assert db_pt.ch_power_message_id is None

    async def test_channel_edit_not_found_db_clear_exception(self):
        """Lines 1226-1231: channel 'not found', DB clear raises → logged."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3023",
            current_state="off",
            bot_msg_id=None,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="9006", last_power_message_id=55),
        )
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )

        call_count = [0]

        @asynccontextmanager
        async def multi_session():
            call_count[0] += 1
            session = _make_mock_session()
            if call_count[0] == 1:
                result_mock = MagicMock()
                result_mock.scalars.return_value.all.return_value = [user]
                session.execute = AsyncMock(return_value=result_mock)
            else:
                session.execute.side_effect = RuntimeError("DB clear fail")
            yield session

        with patch("bot.services.power_monitor.async_session", side_effect=multi_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_channel_edit_bad_request_other(self):
        """Lines 1232-1235: channel other TelegramBadRequest → debug logged."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3024",
            current_state="off",
            bot_msg_id=None,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="9007", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: something else",
            )
        )
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_channel_edit_generic_exception(self):
        """Lines 1236-1239: generic exception during channel edit → debug logged."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3025",
            current_state="off",
            bot_msg_id=None,
            ch_msg_id=55,
            channel_config=SimpleNamespace(channel_id="9008", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(side_effect=RuntimeError("channel fail"))
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

    async def test_channel_naive_power_changed_at(self):
        """Lines 1185-1186: channel section naive power_changed_at → UTC added."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3026",
            current_state="off",
            bot_msg_id=None,
            ch_msg_id=55,
            power_changed_at=datetime(2024, 1, 15, 10, 0),  # naive
            channel_config=SimpleNamespace(channel_id="9009", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        bot_mock.edit_message_text.assert_called_once()

    async def test_bot_message_power_changed_at_exception_swallowed(self):
        """Lines 1119-1120: exception in power_changed_at datetime processing → swallowed."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        # Set power_changed_at to a string — accessing .tzinfo raises AttributeError
        user = _make_upnsc_user(
            telegram_id="3027",
            current_state="off",
            bot_msg_id=55,
            power_changed_at="not-a-datetime",
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        # Should not raise — exception at 1119 swallowed
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        # edit_message_text still called (with default time_str="" and duration_text="—")
        bot_mock.edit_message_text.assert_called_once()

    async def test_edit_bot_message_not_found_on_state_clears_alert_on_id(self):
        """Line 1154: 'not found' for on-state user → alert_on_message_id cleared."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(telegram_id="3028", current_state="on", bot_msg_id=11)
        bot_mock = AsyncMock()
        bot_mock.edit_message_text = AsyncMock(
            side_effect=TelegramBadRequest(
                method=_make_method_mock(),
                message="Bad Request: message to edit not found",
            )
        )

        db_pt = MagicMock()
        db_user_mock = MagicMock()
        db_user_mock.power_tracking = db_pt

        call_count = [0]

        @asynccontextmanager
        async def multi_session():
            call_count[0] += 1
            session = _make_mock_session()
            if call_count[0] >= 2:
                session.execute.return_value.scalars.return_value.first.return_value = db_user_mock
            else:
                result_mock = MagicMock()
                result_mock.scalars.return_value.all.return_value = [user]
                session.execute = AsyncMock(return_value=result_mock)
            yield session

        with patch("bot.services.power_monitor.async_session", side_effect=multi_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_off", "time": "T20"},
                    ):
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        # For "on" state, alert_on_message_id (not alert_off) is cleared
        assert db_pt.alert_on_message_id is None
        assert db_pt.bot_power_message_id is None

    async def test_channel_message_power_changed_at_exception_swallowed(self):
        """Lines 1190-1191: exception in channel power_changed_at datetime processing → swallowed."""
        from bot.services.power_monitor import update_power_notifications_on_schedule_change

        user = _make_upnsc_user(
            telegram_id="3029",
            current_state="off",
            bot_msg_id=None,  # no bot message
            ch_msg_id=66,
            power_changed_at="not-a-datetime",  # triggers AttributeError on .tzinfo
            channel_config=SimpleNamespace(channel_id="8880000", last_power_message_id=None),
        )
        bot_mock = AsyncMock()
        mock_session = self._mock_session_with_users([user])

        with _patch_pm_async_session(mock_session):
            with patch("bot.services.power_monitor.fetch_schedule_data", AsyncMock(return_value={"d": "x"})):
                with patch("bot.services.power_monitor.parse_schedule_for_queue", return_value={}):
                    with patch(
                        "bot.services.power_monitor.find_next_event",
                        return_value={"type": "power_on", "time": "T10"},
                    ):
                        # Should not raise — exception at 1190 swallowed
                        await update_power_notifications_on_schedule_change(bot_mock, "kyiv", "1.1")

        # edit_message_text called for the channel (with default time_str="" and duration_text="—")
        bot_mock.edit_message_text.assert_called_once()


# ─── Timeout branches (lines 622, 674-675) ─────────────────────────────────


class TestCheckAllIpsCursorTimeout:
    """power_monitor.py:674-675: cursor query TimeoutError → logs and returns."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    async def test_cursor_timeout_aborts_ping_cycle(self):
        import asyncio
        from bot.services.power_monitor import _check_all_ips

        bot_mock = AsyncMock()
        mock_session = _make_mock_session()

        async def _timeout_cursor(session, limit, after_id):
            raise asyncio.TimeoutError()

        check_mock = AsyncMock()

        with _patch_pm_async_session(mock_session), \
             patch("bot.services.power_monitor.get_users_with_ip_cursor", _timeout_cursor), \
             patch("bot.services.power_monitor._check_user_power", check_mock), \
             patch("bot.services.power_monitor.logger") as mock_logger:
            await _check_all_ips(bot_mock)

        check_mock.assert_not_called()
        mock_logger.error.assert_called()


class TestDebounceConfirmTimeout:
    """power_monitor.py:622: _handle_power_state_change timeout → logs error."""

    def setup_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

    def teardown_method(self):
        import bot.services.power_monitor as pm
        for state in list(pm._user_states.values()):
            task = state.get("debounce_task")
            if task and not task.done():
                task.cancel()
        pm._user_states.clear()

    async def test_handle_state_change_timeout_logged(self):
        import asyncio
        import bot.services.power_monitor as pm
        from bot.services.power_monitor import _check_user_power

        bot_mock = AsyncMock()
        user = _make_pm_user(telegram_id="timeout_user_42")

        pm._user_states["timeout_user_42"] = {
            **_default_user_state(),
            "current_state": "on",
            "is_first_check": False,
        }

        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        async def _immediate_sleep(_):
            pass

        async def _timeout_handler(*args, **kwargs):
            raise asyncio.TimeoutError()

        with _patch_pm_async_session(mock_session), \
             patch("bot.services.power_monitor.get_setting", AsyncMock(return_value="0")), \
             patch("asyncio.sleep", side_effect=_immediate_sleep), \
             patch("bot.services.power_monitor._handle_power_state_change", _timeout_handler), \
             patch("bot.services.power_monitor.logger") as mock_logger:
            await _check_user_power(bot_mock, user, is_available=False)
            task = pm._user_states.get("timeout_user_42", {}).get("debounce_task")
            if task:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (asyncio.TimeoutError, Exception):
                    pass

        mock_logger.error.assert_called()
