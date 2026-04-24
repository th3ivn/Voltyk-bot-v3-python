"""Unit tests for bot/app.py bootstrap logic."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp.test_utils import make_mocked_request

from bot import app
from bot.utils import heartbeat


@pytest.fixture(autouse=True)
def _reset_heartbeat():
    heartbeat.reset()
    yield
    heartbeat.reset()


def test_create_dispatcher_uses_memory_storage_when_redis_url_empty(monkeypatch):
    monkeypatch.setattr(app.settings, "REDIS_URL", "")
    monkeypatch.setattr(app.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(app, "register_all_handlers", lambda _dp: None)

    dp = app.create_dispatcher()

    assert isinstance(dp.storage, MemoryStorage)


def test_create_dispatcher_uses_redis_storage_when_configured(monkeypatch):
    fake_redis_storage = MemoryStorage()

    monkeypatch.setattr(app.settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(app, "register_all_handlers", lambda _dp: None)
    monkeypatch.setattr(app.RedisStorage, "from_url", lambda _url: fake_redis_storage)

    dp = app.create_dispatcher()

    assert dp.storage is fake_redis_storage


def test_create_dispatcher_falls_back_to_memory_storage_on_redis_init_error(monkeypatch):
    monkeypatch.setattr(app.settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(app.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(app, "register_all_handlers", lambda _dp: None)

    def _boom(_url):
        raise RuntimeError("redis init failed")

    monkeypatch.setattr(app.RedisStorage, "from_url", _boom)

    dp = app.create_dispatcher()

    assert isinstance(dp.storage, MemoryStorage)


def test_create_dispatcher_raises_in_production_when_redis_url_empty(monkeypatch):
    monkeypatch.setattr(app.settings, "REDIS_URL", "")
    monkeypatch.setattr(app.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(app, "register_all_handlers", lambda _dp: None)

    with pytest.raises(RuntimeError, match="REDIS_URL is required in production"):
        app.create_dispatcher()


def test_create_dispatcher_raises_in_production_when_redis_init_fails(monkeypatch):
    monkeypatch.setattr(app.settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(app.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(app, "register_all_handlers", lambda _dp: None)

    def _boom(_url):
        raise RuntimeError("redis init failed")

    monkeypatch.setattr(app.RedisStorage, "from_url", _boom)

    with pytest.raises(RuntimeError, match="Cannot configure Redis FSM storage in production"):
        app.create_dispatcher()


def _make_error_event(exc: BaseException) -> object:
    return SimpleNamespace(exception=exc, update=SimpleNamespace())


@pytest.mark.asyncio
async def test_global_error_handler_swallows_message_not_modified(monkeypatch):
    capture = MagicMock()
    monkeypatch.setattr(app.sentry_sdk, "capture_exception", capture)
    exc = TelegramBadRequest(
        method=MagicMock(),
        message="Bad Request: message is not modified",
    )
    await app._global_error_handler(_make_error_event(exc))
    capture.assert_not_called()


@pytest.mark.asyncio
async def test_global_error_handler_swallows_forbidden(monkeypatch):
    capture = MagicMock()
    monkeypatch.setattr(app.sentry_sdk, "capture_exception", capture)
    exc = TelegramForbiddenError(method=MagicMock(), message="bot was blocked")
    await app._global_error_handler(_make_error_event(exc))
    capture.assert_not_called()


@pytest.mark.asyncio
async def test_global_error_handler_captures_unexpected(monkeypatch):
    capture = MagicMock()
    monkeypatch.setattr(app.sentry_sdk, "capture_exception", capture)
    exc = RuntimeError("boom")
    await app._global_error_handler(_make_error_event(exc))
    capture.assert_called_once_with(exc)


def test_create_dispatcher_registers_global_error_handler(monkeypatch):
    monkeypatch.setattr(app.settings, "REDIS_URL", "")
    monkeypatch.setattr(app.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(app, "register_all_handlers", lambda _dp: None)

    dp = app.create_dispatcher()

    # The errors router holds the registered handler — at least one.
    assert dp.errors.handlers, "global error handler was not registered"


# ─── _is_token_authorized ─────────────────────────────────────────────────


class TestIsTokenAuthorized:
    """HMAC-timing-safe token check used by /health, /ready, /metrics."""

    def _req(self, *, auth: str | None = None, query_token: str | None = None):
        headers = {"Authorization": auth} if auth else None
        qs = f"?token={query_token}" if query_token else ""
        return make_mocked_request("GET", f"/health{qs}", headers=headers)

    def test_empty_configured_token_disables_auth(self):
        assert app._is_token_authorized(self._req(), "") is True

    def test_bearer_header_match(self):
        req = self._req(auth="Bearer secret-token")
        assert app._is_token_authorized(req, "secret-token") is True

    def test_bearer_header_case_insensitive(self):
        req = self._req(auth="bearer secret-token")
        assert app._is_token_authorized(req, "secret-token") is True

    def test_bearer_header_mismatch(self):
        req = self._req(auth="Bearer wrong-token")
        assert app._is_token_authorized(req, "secret-token") is False

    def test_query_param_match(self):
        req = self._req(query_token="secret-token")
        assert app._is_token_authorized(req, "secret-token") is True

    def test_query_param_mismatch(self):
        req = self._req(query_token="wrong")
        assert app._is_token_authorized(req, "secret-token") is False

    def test_missing_credentials_when_required(self):
        assert app._is_token_authorized(self._req(), "secret-token") is False


# ─── _health_handler (liveness — heartbeat only) ──────────────────────────


class TestHealthHandler:
    async def test_returns_200_when_no_tasks_registered(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "")
        resp = await app._health_handler(make_mocked_request("GET", "/health"))
        assert resp.status == 200

    async def test_returns_200_when_task_is_fresh(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "")
        heartbeat.register("demo")
        resp = await app._health_handler(make_mocked_request("GET", "/health"))
        assert resp.status == 200

    async def test_returns_503_when_task_is_stale(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "")
        monkeypatch.setattr(app.settings, "BG_TASK_STALE_THRESHOLD_S", 1)
        heartbeat.register("demo")
        heartbeat._beats["demo"] = time.monotonic() - 600.0
        resp = await app._health_handler(make_mocked_request("GET", "/health"))
        assert resp.status == 503
        text = resp.text or ""
        assert "demo" in text

    async def test_rejects_missing_token(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "required")
        resp = await app._health_handler(make_mocked_request("GET", "/health"))
        assert resp.status == 401


# ─── _ready_handler (readiness — DB + Redis) ──────────────────────────────


class TestReadyHandler:
    async def test_returns_200_when_both_healthy(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "")

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        fake_engine = MagicMock()
        fake_engine.connect = lambda: mock_conn

        monkeypatch.setattr(app, "engine", fake_engine)
        monkeypatch.setattr(app.chart_cache, "is_usable", lambda: True)
        monkeypatch.setattr(app.chart_cache, "ping", AsyncMock())

        resp = await app._ready_handler(make_mocked_request("GET", "/ready"))
        assert resp.status == 200

    async def test_returns_503_on_db_failure(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "")

        def _boom():
            raise Exception("connection refused")

        fake_engine = MagicMock()
        fake_engine.connect = _boom

        monkeypatch.setattr(app, "engine", fake_engine)
        monkeypatch.setattr(app.chart_cache, "is_usable", lambda: False)

        resp = await app._ready_handler(make_mocked_request("GET", "/ready"))
        assert resp.status == 503

    async def test_returns_503_on_redis_failure(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "")

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        fake_engine = MagicMock()
        fake_engine.connect = lambda: mock_conn

        monkeypatch.setattr(app, "engine", fake_engine)
        monkeypatch.setattr(app.chart_cache, "is_usable", lambda: True)
        monkeypatch.setattr(
            app.chart_cache, "ping", AsyncMock(side_effect=Exception("redis down"))
        )

        resp = await app._ready_handler(make_mocked_request("GET", "/ready"))
        assert resp.status == 503

    async def test_rejects_missing_token(self, monkeypatch):
        monkeypatch.setattr(app.settings, "HEALTHCHECK_TOKEN", "required")
        resp = await app._ready_handler(make_mocked_request("GET", "/ready"))
        assert resp.status == 401


# ─── _metrics_handler ─────────────────────────────────────────────────────


class TestMetricsHandler:
    async def test_returns_metrics_body(self, monkeypatch):
        monkeypatch.setattr(app.settings, "METRICS_TOKEN", "")
        resp = await app._metrics_handler(make_mocked_request("GET", "/metrics"))
        assert resp.status == 200

    async def test_rejects_missing_token(self, monkeypatch):
        monkeypatch.setattr(app.settings, "METRICS_TOKEN", "required")
        resp = await app._metrics_handler(make_mocked_request("GET", "/metrics"))
        assert resp.status == 401


# ─── _admin_notify_cooldown_ok ────────────────────────────────────────────


class TestAdminNotifyCooldown:
    async def test_disabled_when_cooldown_is_zero(self, monkeypatch):
        monkeypatch.setattr(app.settings, "ADMIN_NOTIFY_COOLDOWN_S", 0)
        assert await app._admin_notify_cooldown_ok("startup") is True

    async def test_first_notice_passes_and_records(self, monkeypatch):
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()

        def _session_ctor():
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        monkeypatch.setattr(app, "async_session", _session_ctor)
        gs = AsyncMock(return_value=None)
        ss = AsyncMock()
        monkeypatch.setattr(app, "get_setting", gs)
        monkeypatch.setattr(app, "set_setting", ss)

        assert await app._admin_notify_cooldown_ok("startup") is True
        gs.assert_awaited_once()
        ss.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_suppressed_when_recent_notice_exists(self, monkeypatch):
        monkeypatch.setattr(app.settings, "ADMIN_NOTIFY_COOLDOWN_S", 600)
        recent = str(int(time.time()) - 1)

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()

        def _session_ctor():
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        monkeypatch.setattr(app, "async_session", _session_ctor)
        monkeypatch.setattr(app, "get_setting", AsyncMock(return_value=recent))
        ss = AsyncMock()
        monkeypatch.setattr(app, "set_setting", ss)

        assert await app._admin_notify_cooldown_ok("startup") is False
        ss.assert_not_awaited()

    async def test_corrupt_timestamp_treated_as_epoch(self, monkeypatch):
        """Better to over-notify once than suppress forever on bad data."""
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()

        def _session_ctor():
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        monkeypatch.setattr(app, "async_session", _session_ctor)
        monkeypatch.setattr(app, "get_setting", AsyncMock(return_value="not-a-number"))
        monkeypatch.setattr(app, "set_setting", AsyncMock())

        assert await app._admin_notify_cooldown_ok("startup") is True

    async def test_db_error_allows_notice_as_safety_net(self, monkeypatch):
        def _boom():
            raise Exception("db down")

        monkeypatch.setattr(app, "async_session", _boom)
        assert await app._admin_notify_cooldown_ok("startup") is True


# ─── _run_migrations ──────────────────────────────────────────────────────


class TestRunMigrations:
    async def test_successful_upgrade(self, monkeypatch):
        called = MagicMock()
        monkeypatch.setattr(app.alembic_command, "upgrade", called)
        await app._run_migrations()
        called.assert_called_once()

    async def test_failure_wrapped_and_reraised(self, monkeypatch):
        """Silent data corruption risk — Alembic failure must abort startup."""
        def _boom(_cfg, _rev):
            raise RuntimeError("bad migration")

        monkeypatch.setattr(app.alembic_command, "upgrade", _boom)
        captured = MagicMock()
        monkeypatch.setattr(app.sentry_sdk, "capture_exception", captured)

        with pytest.raises(RuntimeError, match="Alembic migration failed"):
            await app._run_migrations()

        captured.assert_called_once()


# ─── _track_bg_task ───────────────────────────────────────────────────────


class TestTrackBgTask:
    async def test_cancelled_task_removed_without_logging(self, monkeypatch):
        captured = MagicMock()
        monkeypatch.setattr(app.sentry_sdk, "capture_exception", captured)

        async def _forever():
            await asyncio.sleep(100)

        task = asyncio.create_task(_forever(), name="demo")
        app._track_bg_task(task)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Let the done_callback run
        await asyncio.sleep(0)

        captured.assert_not_called()
        assert task not in app._bg_tasks

    async def test_crashed_task_is_captured_and_removed(self, monkeypatch):
        captured = MagicMock()
        monkeypatch.setattr(app.sentry_sdk, "capture_exception", captured)

        async def _crash():
            raise RuntimeError("boom")

        task = asyncio.create_task(_crash(), name="demo")
        app._track_bg_task(task)
        await asyncio.sleep(0.05)

        captured.assert_called_once()
        assert task not in app._bg_tasks


# ─── _restart_with_backoff ────────────────────────────────────────────────


class TestRestartWithBackoff:
    async def test_clean_exit_does_not_restart(self):
        calls = 0

        async def _factory():
            nonlocal calls
            calls += 1

        await app._restart_with_backoff(_factory, name="demo")
        assert calls == 1

    async def test_cancellation_returns_cleanly(self):
        async def _factory():
            raise asyncio.CancelledError()

        await app._restart_with_backoff(_factory, name="demo")

    async def test_restarts_after_crash(self, monkeypatch):
        calls = 0

        async def _factory():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("boom")

        monkeypatch.setattr(app.asyncio, "sleep", AsyncMock())
        await app._restart_with_backoff(
            _factory, name="demo", max_retries=5, base_delay=0.01
        )
        assert calls == 3

    async def test_gives_up_after_max_retries(self, monkeypatch):
        calls = 0

        async def _factory():
            nonlocal calls
            calls += 1
            raise RuntimeError("always fails")

        monkeypatch.setattr(app.asyncio, "sleep", AsyncMock())
        await app._restart_with_backoff(
            _factory, name="demo", max_retries=3, base_delay=0.01
        )
        # Initial run + 3 retries = 4 attempts
        assert calls == 4

    async def test_respects_stop_flag(self, monkeypatch):
        """When _bg_restart_enabled is False (shutdown in progress), the loop
        exits even if the coroutine is still failing."""
        calls = 0

        async def _factory():
            nonlocal calls
            calls += 1
            raise RuntimeError("boom")

        monkeypatch.setattr(app, "_bg_restart_enabled", False)
        await app._restart_with_backoff(
            _factory, name="demo", max_retries=10, base_delay=0.01
        )
        assert calls == 0


# ─── create_bot ───────────────────────────────────────────────────────────


class TestCreateBot:
    def test_returns_configured_bot(self, monkeypatch):
        monkeypatch.setattr(app.settings, "BOT_TOKEN", "123456:TEST-token-value-0000")
        bot = app.create_bot()
        assert bot is not None
        assert bot.token == "123456:TEST-token-value-0000"


# ─── _probe_interrupted_broadcast ─────────────────────────────────────────


class TestProbeInterruptedBroadcast:
    async def test_no_snapshot_is_noop(self, monkeypatch):
        """No prior interrupted broadcast → don't message anyone."""
        bot = AsyncMock()

        async def _none():
            return None

        monkeypatch.setattr(
            "bot.handlers.admin.broadcast.load_interrupted_broadcast", _none
        )
        await app._probe_interrupted_broadcast(bot)

        bot.send_message.assert_not_called()

    async def test_snapshot_without_admin_id_is_noop(self, monkeypatch):
        """Defensive — malformed snapshot without admin_id shouldn't crash."""
        bot = AsyncMock()

        async def _snap():
            return {"last_id": 1}

        monkeypatch.setattr(
            "bot.handlers.admin.broadcast.load_interrupted_broadcast", _snap
        )
        await app._probe_interrupted_broadcast(bot)

        bot.send_message.assert_not_called()

    async def test_snapshot_sends_resume_prompt(self, monkeypatch):
        bot = AsyncMock()

        snapshot = {
            "admin_id": 99,
            "last_id": 500,
            "sent": 500,
            "failed": 2,
            "blocked": 1,
        }

        async def _snap():
            return snapshot

        monkeypatch.setattr(
            "bot.handlers.admin.broadcast.load_interrupted_broadcast", _snap
        )
        await app._probe_interrupted_broadcast(bot)

        bot.send_message.assert_awaited_once()
        args, kwargs = bot.send_message.call_args
        assert args[0] == 99
        assert "Перервана розсилка" in args[1]
        assert kwargs.get("reply_markup") is not None

    async def test_send_failure_is_swallowed(self, monkeypatch):
        """A failed notification must not crash startup."""
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Exception("telegram down"))

        async def _snap():
            return {"admin_id": 99, "last_id": 1, "sent": 1, "failed": 0, "blocked": 0}

        monkeypatch.setattr(
            "bot.handlers.admin.broadcast.load_interrupted_broadcast", _snap
        )
        # Must not raise
        await app._probe_interrupted_broadcast(bot)
