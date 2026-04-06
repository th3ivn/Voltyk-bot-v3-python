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
    session.execute = AsyncMock()
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

    def teardown_method(self):
        import bot.services.power_monitor as pm
        pm._user_states.clear()

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
                "bot.services.power_monitor.get_users_with_ip",
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
                "bot.services.power_monitor.get_users_with_ip",
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
                "bot.services.power_monitor.get_users_with_ip",
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
                "bot.services.power_monitor.get_users_with_ip",
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
                "bot.services.power_monitor.get_users_with_ip",
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
                "bot.services.power_monitor.get_active_ping_error_alerts",
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
                "bot.services.power_monitor.get_active_ping_error_alerts",
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
                "bot.services.power_monitor.get_active_ping_error_alerts",
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
                "bot.services.power_monitor.get_active_ping_error_alerts",
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
                "bot.services.power_monitor.get_active_ping_error_alerts",
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
                "bot.services.power_monitor.get_active_ping_error_alerts",
                AsyncMock(side_effect=Exception("DB error")),
            ):
                await _send_daily_ping_error_alerts(bot_mock)  # Should not raise

        bot_mock.send_message.assert_not_called()
