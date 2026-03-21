"""Tests for bot/services/power_monitor.py.

These tests focus on the pure/isolated parts of the power monitor service:
- _get_user_state: in-memory state management
- _check_router_http: router reachability logic (mocked HTTP)
- _get_http_connector: lazy connector creation
- State machine invariants

Heavy integration tests (full _handle_power_state_change flow) require a live
DB and Telegram bot — those are documented as integration test candidates.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


# ─── _check_router_http ──────────────────────────────────────────────────


class TestCheckRouterHttp:
    async def test_returns_none_for_no_ip(self):
        from bot.services.power_monitor import _check_router_http

        result = await _check_router_http(None)

        assert result is None

    async def test_returns_none_for_empty_ip(self):
        from bot.services.power_monitor import _check_router_http

        result = await _check_router_http("")

        assert result is None

    async def test_returns_true_on_http_success(self):
        from bot.services.power_monitor import _check_router_http

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
            result = await _check_router_http("192.168.1.1")

        assert result is True

    async def test_returns_false_on_connection_error(self):
        import aiohttp
        from bot.services.power_monitor import _check_router_http

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

            result = await _check_router_http("192.168.1.1")

        assert result is False

    async def test_returns_false_on_timeout(self):
        import asyncio
        from bot.services.power_monitor import _check_router_http

        mock_connector = MagicMock()

        with patch("bot.services.power_monitor._get_http_connector", return_value=mock_connector), \
             patch("aiohttp.ClientSession") as MockSession:
            mock_session_instance = MagicMock()
            mock_session_instance.head = MagicMock(side_effect=asyncio.TimeoutError())
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value = mock_session_instance

            result = await _check_router_http("192.168.1.1")

        assert result is False

    async def test_parses_ip_with_port(self):
        """Router addresses with port (e.g. 192.168.1.1:8080) should use the specified port."""
        from bot.services.power_monitor import _check_router_http

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
            result = await _check_router_http("192.168.1.1:8080")

        assert result is True

    async def test_returns_true_for_non_200_status(self):
        """Non-200 HTTP responses still mean the host is reachable (power is on)."""
        from bot.services.power_monitor import _check_router_http

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
            result = await _check_router_http("192.168.1.1")

        assert result is True


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
