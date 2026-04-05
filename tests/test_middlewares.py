"""Tests for bot/middlewares/db.py, maintenance.py, and throttle.py."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(return_value: object = "ok") -> AsyncMock:
    return AsyncMock(return_value=return_value)


def _make_failing_handler(exc: Exception) -> AsyncMock:
    handler = AsyncMock(side_effect=exc)
    return handler


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@asynccontextmanager
async def _mock_async_session_ctx(session: AsyncMock):
    yield session


# ===========================================================================
# DbSessionMiddleware
# ===========================================================================


class TestDbSessionMiddleware:
    """Tests for bot/middlewares/db.py — DbSessionMiddleware."""

    def setup_method(self):
        import bot.middlewares.db  # ensure module is loaded before patching

        self.session = _make_mock_session()
        self.patcher = patch(
            "bot.middlewares.db.async_session",
            side_effect=lambda: _mock_async_session_ctx(self.session),
        )
        self.patcher.start()
        from bot.middlewares.db import DbSessionMiddleware

        self.middleware = DbSessionMiddleware()

    def teardown_method(self):
        self.patcher.stop()

    async def test_injects_session_into_data(self):
        """data['session'] is set before the handler runs."""
        captured: dict = {}

        async def _handler(event, data):
            captured.update(data)
            return "result"

        event = MagicMock()
        data: dict = {}
        await self.middleware(handler=_handler, event=event, data=data)
        assert captured["session"] is self.session

    async def test_commits_on_success(self):
        """session.commit() is called after a successful handler."""
        handler = _make_handler("ok")
        event = MagicMock()
        await self.middleware(handler=handler, event=event, data={})
        self.session.commit.assert_awaited_once()

    async def test_returns_handler_result(self):
        """Middleware returns whatever the handler returns."""
        handler = _make_handler(42)
        event = MagicMock()
        result = await self.middleware(handler=handler, event=event, data={})
        assert result == 42

    async def test_rollback_on_handler_exception(self):
        """When handler raises, session.rollback() is called and original exception is re-raised."""
        original_exc = ValueError("handler error")
        handler = _make_failing_handler(original_exc)
        event = MagicMock()
        with pytest.raises(ValueError, match="handler error"):
            await self.middleware(handler=handler, event=event, data={})
        self.session.rollback.assert_awaited_once()

    async def test_rollback_failure_still_raises_original(self):
        """When both handler AND rollback raise, original exception is re-raised."""
        original_exc = RuntimeError("original")
        self.session.rollback.side_effect = Exception("rollback failed")
        handler = _make_failing_handler(original_exc)
        event = MagicMock()
        with pytest.raises(RuntimeError, match="original"):
            await self.middleware(handler=handler, event=event, data={})

    async def test_rollback_failure_logs_error(self):
        """logger.error is called when rollback fails."""
        original_exc = RuntimeError("original")
        rollback_exc = Exception("rollback failed")
        self.session.rollback.side_effect = rollback_exc
        handler = _make_failing_handler(original_exc)
        event = MagicMock()
        with patch("bot.middlewares.db.logger") as mock_logger:
            with pytest.raises(RuntimeError):
                await self.middleware(handler=handler, event=event, data={})
            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args
            assert "rollback" in call_args[0][0].lower()
            assert call_args[1].get("exc_info") is rollback_exc


# ===========================================================================
# MaintenanceMiddleware
# ===========================================================================


class TestMaintenanceMiddleware:
    """Tests for bot/middlewares/maintenance.py — MaintenanceMiddleware."""

    def setup_method(self):
        import bot.middlewares.maintenance as mod  # ensure module is loaded

        # Reset module-level state before each test
        mod._maintenance_mode = False
        mod._maintenance_message = "🔧 Бот тимчасово недоступний. Спробуйте пізніше."
        from bot.middlewares.maintenance import MaintenanceMiddleware

        self.middleware = MaintenanceMiddleware()
        self.mod = mod

    async def test_passthrough_when_not_in_maintenance(self):
        """Handler is called normally when maintenance mode is off."""
        handler = _make_handler("result")
        event = MagicMock()
        result = await self.middleware(handler=handler, event=event, data={})
        handler.assert_awaited_once_with(event, {})
        assert result == "result"

    async def test_blocks_message_in_maintenance(self):
        """Non-admin Message in maintenance → reply with message, handler NOT called."""
        from aiogram.types import Message

        self.mod._maintenance_mode = True
        user = SimpleNamespace(id=999)
        event = MagicMock(spec=Message)
        event.from_user = user
        event.reply = AsyncMock()
        handler = _make_handler("should not run")
        with patch("bot.middlewares.maintenance.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            result = await self.middleware(handler=handler, event=event, data={})
        event.reply.assert_awaited_once_with(self.mod._maintenance_message)
        handler.assert_not_awaited()
        assert result is None

    async def test_blocks_callback_in_maintenance(self):
        """Non-admin CallbackQuery in maintenance → answer with alert, handler NOT called."""
        from aiogram.types import CallbackQuery

        self.mod._maintenance_mode = True
        user = SimpleNamespace(id=999)
        event = MagicMock(spec=CallbackQuery)
        event.from_user = user
        event.answer = AsyncMock()
        handler = _make_handler("should not run")
        with patch("bot.middlewares.maintenance.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            result = await self.middleware(handler=handler, event=event, data={})
        event.answer.assert_awaited_once_with(self.mod._maintenance_message, show_alert=True)
        handler.assert_not_awaited()
        assert result is None

    async def test_admin_bypass_message(self):
        """Admin Message in maintenance mode → handler IS called."""
        from aiogram.types import Message

        self.mod._maintenance_mode = True
        user = SimpleNamespace(id=1)
        event = MagicMock(spec=Message)
        event.from_user = user
        handler = _make_handler("admin ok")
        with patch("bot.middlewares.maintenance.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            result = await self.middleware(handler=handler, event=event, data={})
        handler.assert_awaited_once()
        assert result == "admin ok"

    async def test_admin_bypass_callback(self):
        """Admin CallbackQuery in maintenance mode → handler IS called."""
        from aiogram.types import CallbackQuery

        self.mod._maintenance_mode = True
        user = SimpleNamespace(id=1)
        event = MagicMock(spec=CallbackQuery)
        event.from_user = user
        handler = _make_handler("admin ok")
        with patch("bot.middlewares.maintenance.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            result = await self.middleware(handler=handler, event=event, data={})
        handler.assert_awaited_once()
        assert result == "admin ok"

    def test_set_maintenance_mode_toggles(self):
        """set_maintenance_mode(True) → is_maintenance_mode() returns True."""
        from bot.middlewares.maintenance import is_maintenance_mode, set_maintenance_mode

        set_maintenance_mode(True)
        assert is_maintenance_mode() is True
        set_maintenance_mode(False)
        assert is_maintenance_mode() is False

    def test_set_maintenance_mode_custom_message(self):
        """set_maintenance_mode(True, 'custom') → get_maintenance_message() returns 'custom'."""
        from bot.middlewares.maintenance import get_maintenance_message, set_maintenance_mode

        set_maintenance_mode(True, "custom msg")
        assert get_maintenance_message() == "custom msg"

    async def test_returns_none_for_unknown_event_type(self):
        """Non-Message, non-CallbackQuery event in maintenance → returns None."""
        self.mod._maintenance_mode = True
        event = MagicMock()  # not a Message or CallbackQuery instance
        # Ensure isinstance checks fail
        event.__class__ = object
        handler = _make_handler("should not run")
        # Patch settings (user_id will be None since event is not Message/CallbackQuery)
        with patch("bot.middlewares.maintenance.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            result = await self.middleware(handler=handler, event=event, data={})
        handler.assert_not_awaited()
        assert result is None


# ===========================================================================
# ThrottleMiddleware
# ===========================================================================


class TestThrottleMiddleware:
    """Tests for bot/middlewares/throttle.py — ThrottleMiddleware."""

    def setup_method(self):
        import bot.middlewares.throttle  # ensure module is loaded

        from bot.middlewares.throttle import ThrottleMiddleware

        self.ThrottleMiddleware = ThrottleMiddleware
        self.middleware = ThrottleMiddleware(rate_limit=0.5)

    async def test_first_call_passes_through(self):
        """First call from a user is not throttled."""
        user = SimpleNamespace(id=10)
        handler = _make_handler("first")
        data = {"event_from_user": user}
        result = await self.middleware(handler=handler, event=MagicMock(), data=data)
        handler.assert_awaited_once()
        assert result == "first"

    async def test_second_call_within_limit_throttled(self):
        """Immediate second call from same user returns None."""
        user = SimpleNamespace(id=20)
        handler = _make_handler("ok")
        data = {"event_from_user": user}
        event = MagicMock()
        # First call — passes
        await self.middleware(handler=handler, event=event, data=data)
        # Second call immediately — throttled
        handler2 = _make_handler("throttled")
        result = await self.middleware(handler=handler2, event=event, data=data)
        handler2.assert_not_awaited()
        assert result is None

    async def test_call_after_limit_passes(self):
        """Call after rate_limit has elapsed passes through."""
        user = SimpleNamespace(id=30)
        handler1 = _make_handler("first")
        handler2 = _make_handler("second")
        data = {"event_from_user": user}
        event = MagicMock()

        with patch("bot.middlewares.throttle.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            self.middleware = self.ThrottleMiddleware(rate_limit=0.5)
            await self.middleware(handler=handler1, event=event, data=data)

            # Advance time past rate_limit
            mock_time.monotonic.return_value = 1000.6
            result = await self.middleware(handler=handler2, event=event, data=data)

        handler2.assert_awaited_once()
        assert result == "second"

    async def test_no_user_passes_through(self):
        """No event_from_user in data → handler called."""
        handler = _make_handler("no user")
        data: dict = {}
        result = await self.middleware(handler=handler, event=MagicMock(), data=data)
        handler.assert_awaited_once()
        assert result == "no user"

    async def test_different_users_independent(self):
        """Throttling user A does not affect user B."""
        user_a = SimpleNamespace(id=100)
        user_b = SimpleNamespace(id=200)
        event = MagicMock()

        handler_a1 = _make_handler("a1")
        handler_a2 = _make_handler("a2")
        handler_b = _make_handler("b")

        # First call for user A
        await self.middleware(handler=handler_a1, event=event, data={"event_from_user": user_a})
        # Immediate second call for user A — throttled
        result_a2 = await self.middleware(handler=handler_a2, event=event, data={"event_from_user": user_a})
        # First call for user B — passes through
        result_b = await self.middleware(handler=handler_b, event=event, data={"event_from_user": user_b})

        assert result_a2 is None
        assert result_b == "b"
        handler_b.assert_awaited_once()

    async def test_returns_handler_result(self):
        """Return value from handler is propagated."""
        user = SimpleNamespace(id=50)
        handler = _make_handler({"key": "value"})
        data = {"event_from_user": user}
        result = await self.middleware(handler=handler, event=MagicMock(), data=data)
        assert result == {"key": "value"}

    async def test_ttl_eviction(self):
        """After cleanup interval, stale entries are removed."""
        from bot.middlewares import throttle as throttle_mod

        with patch("bot.middlewares.throttle.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            middleware = self.ThrottleMiddleware(rate_limit=0.5)
            # Seed a stale entry older than _ENTRY_TTL
            stale_time = mock_time.monotonic.return_value - throttle_mod._ENTRY_TTL - 40
            middleware._last_call[999] = stale_time
            middleware._last_cleanup = 1000.0 - throttle_mod._CLEANUP_INTERVAL - 1  # trigger cleanup

            # Advance time past cleanup interval
            mock_time.monotonic.return_value = 1000.0 + throttle_mod._CLEANUP_INTERVAL + 1
            user = SimpleNamespace(id=888)
            handler = _make_handler("after cleanup")
            await middleware(handler=handler, event=MagicMock(), data={"event_from_user": user})

        # Stale entry for uid 999 should have been evicted
        assert 999 not in middleware._last_call

    async def test_max_entries_eviction(self):
        """When dict exceeds _MAX_ENTRIES, oldest entries are evicted."""
        from bot.middlewares import throttle as throttle_mod

        with patch("bot.middlewares.throttle.time") as mock_time:
            mock_time.monotonic.return_value = 5000.0
            middleware = self.ThrottleMiddleware(rate_limit=0.5)
            # Fill dict beyond _MAX_ENTRIES with recent timestamps
            for i in range(throttle_mod._MAX_ENTRIES + 10):
                middleware._last_call[i] = 5000.0 - i  # uid 0 is newest, uid N is oldest
            # The oldest entries have the smallest timestamps (largest i value)
            middleware._last_cleanup = 5000.0 - throttle_mod._CLEANUP_INTERVAL - 1

            # Trigger cleanup by advancing time
            mock_time.monotonic.return_value = 5000.0 + throttle_mod._CLEANUP_INTERVAL + 1
            # Use a timestamp recent enough to survive TTL eviction
            for i in range(throttle_mod._MAX_ENTRIES + 10):
                middleware._last_call[i] = 5000.0 + throttle_mod._CLEANUP_INTERVAL

            user = SimpleNamespace(id=99999999)
            handler = _make_handler("after cap eviction")
            await middleware(handler=handler, event=MagicMock(), data={"event_from_user": user})

        # After eviction, dict should be at or below _MAX_ENTRIES + 1 (the new entry)
        assert len(middleware._last_call) <= throttle_mod._MAX_ENTRIES + 1
