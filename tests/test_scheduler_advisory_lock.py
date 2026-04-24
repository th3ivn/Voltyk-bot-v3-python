"""Tests for scheduler advisory-lock wrapper + skip paths."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.scheduler import (
    _check_all_schedules,
    _scheduler_advisory_lock,
    flush_pending_notifications,
)

# ─── _scheduler_advisory_lock ─────────────────────────────────────────────


async def test_advisory_lock_acquired_yields_true():
    session = MagicMock()
    # Three execute() calls: SET LOCAL idle_in_tx = 0, SET LOCAL stmt_timeout = 0, pg_try_advisory
    result = MagicMock()
    result.scalar = MagicMock(return_value=True)
    session.execute = AsyncMock(return_value=result)

    async with _scheduler_advisory_lock(session, 42) as acquired:
        assert acquired is True
    assert session.execute.await_count == 3
    # The lock-holding tx must disable idle_in_transaction_session_timeout
    # so Postgres does not release the advisory lock after 60s of idleness
    # while the critical section runs on separate sessions.
    sql_texts = [str(call.args[0]) for call in session.execute.await_args_list]
    assert any("idle_in_transaction_session_timeout = 0" in s for s in sql_texts)
    assert any("statement_timeout = 0" in s for s in sql_texts)
    assert any("pg_try_advisory_xact_lock" in s for s in sql_texts)


async def test_advisory_lock_contention_yields_false():
    session = MagicMock()
    result = MagicMock()
    result.scalar = MagicMock(return_value=False)
    session.execute = AsyncMock(return_value=result)

    async with _scheduler_advisory_lock(session, 42) as acquired:
        assert acquired is False


async def test_advisory_lock_unsupported_backend_yields_true():
    """Sqlite/non-pg DB errors should fall through to 'proceed as uncontested'."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=Exception("no such function"))

    async with _scheduler_advisory_lock(session, 42) as acquired:
        assert acquired is True


# ─── _check_all_schedules skip path ───────────────────────────────────────


async def test_check_all_schedules_skips_when_lock_held():
    """When pg_try_advisory_xact_lock returns False, no downstream work runs."""
    bot = MagicMock()
    locked_inner = AsyncMock()

    with (
        patch(
            "bot.services.scheduler.check_source_repo_updated",
            AsyncMock(return_value=(True, "deadbeef")),
        ),
        patch("bot.services.scheduler.async_session") as mock_session_ctor,
        patch(
            "bot.services.scheduler._check_all_schedules_locked",
            locked_inner,
        ),
    ):
        # async_session() returns an async context manager
        mock_session = MagicMock()
        result = MagicMock()
        result.scalar = MagicMock(return_value=False)  # lock held by someone else
        mock_session.execute = AsyncMock(return_value=result)

        mock_session_ctor.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctor.return_value.__aexit__ = AsyncMock(return_value=None)

        await _check_all_schedules(bot, 60)

    locked_inner.assert_not_called()


async def test_check_all_schedules_proceeds_when_lock_acquired():
    bot = MagicMock()
    locked_inner = AsyncMock()

    with (
        patch(
            "bot.services.scheduler.check_source_repo_updated",
            AsyncMock(return_value=(True, "deadbeef")),
        ),
        patch("bot.services.scheduler.async_session") as mock_session_ctor,
        patch(
            "bot.services.scheduler._check_all_schedules_locked",
            locked_inner,
        ),
    ):
        mock_session = MagicMock()
        result = MagicMock()
        result.scalar = MagicMock(return_value=True)
        mock_session.execute = AsyncMock(return_value=result)

        mock_session_ctor.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctor.return_value.__aexit__ = AsyncMock(return_value=None)

        await _check_all_schedules(bot, 60)

    locked_inner.assert_awaited_once()


# ─── flush_pending_notifications skip path ────────────────────────────────


async def test_flush_pending_notifications_skips_when_lock_held():
    bot = MagicMock()
    flush_inner = AsyncMock()

    with (
        patch("bot.services.scheduler.async_session") as mock_session_ctor,
        patch(
            "bot.services.scheduler._flush_pending_notifications_locked",
            flush_inner,
        ),
    ):
        mock_session = MagicMock()
        result = MagicMock()
        result.scalar = MagicMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=result)

        mock_session_ctor.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctor.return_value.__aexit__ = AsyncMock(return_value=None)

        await flush_pending_notifications(bot)

    flush_inner.assert_not_called()


async def test_flush_pending_notifications_proceeds_when_lock_acquired():
    bot = MagicMock()
    flush_inner = AsyncMock()

    with (
        patch("bot.services.scheduler.async_session") as mock_session_ctor,
        patch(
            "bot.services.scheduler._flush_pending_notifications_locked",
            flush_inner,
        ),
    ):
        mock_session = MagicMock()
        result = MagicMock()
        result.scalar = MagicMock(return_value=True)
        mock_session.execute = AsyncMock(return_value=result)

        mock_session_ctor.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctor.return_value.__aexit__ = AsyncMock(return_value=None)

        await flush_pending_notifications(bot)

    flush_inner.assert_awaited_once()


# Ensure pytest-asyncio runs these as async functions
@pytest.fixture(autouse=True)
def _asyncio_mode():
    pass
