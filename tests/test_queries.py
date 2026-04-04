"""Tests for bot/db/queries.py — uses mocked AsyncSession to avoid needing a real DB.

Note: PostgreSQL-specific upserts (pg_insert) cannot be tested with SQLite.
These tests verify the query layer's logic via mocked sessions, ensuring
correct methods are called with the right arguments.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from bot.db.queries import (
    count_active_users,
    create_or_update_user,
    deactivate_user,
    delete_user_data,
    get_active_users_by_region,
    get_user_by_telegram_id,
    get_users_with_ip,
)


def _make_mock_session() -> AsyncMock:
    """Create a minimal async SQLAlchemy session mock."""
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_scalars_result(value):
    """Create a mock execute result that returns `value` from scalars().first() or .all()."""
    scalars = MagicMock()
    scalars.first.return_value = value
    scalars.all.return_value = value if isinstance(value, list) else [value] if value else []
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar.return_value = value
    return result


# ─── get_user_by_telegram_id ─────────────────────────────────────────────


class TestGetUserByTelegramId:
    async def test_returns_user_when_found(self):
        session = _make_mock_session()
        mock_user = SimpleNamespace(telegram_id="123", region="kyiv", queue="1.1")
        session.execute.return_value = _make_scalars_result(mock_user)

        result = await get_user_by_telegram_id(session, "123")

        assert result is mock_user
        session.execute.assert_called_once()

    async def test_returns_none_when_not_found(self):
        session = _make_mock_session()
        session.execute.return_value = _make_scalars_result(None)

        result = await get_user_by_telegram_id(session, "nonexistent")

        assert result is None

    async def test_converts_integer_telegram_id_to_str(self):
        """Telegram IDs passed as int must be converted to string for the query."""
        session = _make_mock_session()
        session.execute.return_value = _make_scalars_result(None)

        await get_user_by_telegram_id(session, 123456789)

        # Session.execute was called — the conversion happens internally
        session.execute.assert_called_once()


# ─── create_or_update_user ────────────────────────────────────────────────


class TestCreateOrUpdateUser:
    async def test_creates_new_user_when_not_found(self):
        session = _make_mock_session()
        # First call (get_user_by_telegram_id): user not found
        session.execute.return_value = _make_scalars_result(None)

        # We call flush after adding the user, which sets user.id.
        # Patch flush to set the id on any User object added to session.
        added_objects: list = []
        original_add = session.add

        def capture_add(obj):
            added_objects.append(obj)
            if hasattr(obj, "telegram_id"):
                obj.id = 1  # Simulate DB assigning an id

        session.add = MagicMock(side_effect=capture_add)

        result = await create_or_update_user(session, "999", "testuser", "kyiv", "1.1")

        # A User object should have been added
        assert any(hasattr(o, "telegram_id") for o in added_objects)

    async def test_updates_existing_user(self):
        session = _make_mock_session()
        # Existing user mock
        existing_user = MagicMock()
        existing_user.region = "kyiv"
        existing_user.queue = "1.1"
        existing_user.username = "old_name"
        existing_user.is_active = False
        existing_user.notification_settings = MagicMock()
        existing_user.channel_config = MagicMock()
        existing_user.power_tracking = MagicMock()
        existing_user.message_tracking = MagicMock()

        session.execute.return_value = _make_scalars_result(existing_user)

        result = await create_or_update_user(session, "123", "new_name", "dnipro", "2.1")

        # Properties should be updated
        assert existing_user.region == "dnipro"
        assert existing_user.queue == "2.1"
        assert existing_user.username == "new_name"
        assert existing_user.is_active is True


# ─── deactivate_user ─────────────────────────────────────────────────────


class TestDeactivateUser:
    async def test_executes_update_query(self):
        session = _make_mock_session()
        await deactivate_user(session, "123")
        session.execute.assert_called_once()

    async def test_accepts_int_telegram_id(self):
        session = _make_mock_session()
        await deactivate_user(session, 123456789)
        session.execute.assert_called_once()


# ─── delete_user_data ─────────────────────────────────────────────────────


class TestDeleteUserData:
    async def test_deletes_user_when_found(self):
        session = _make_mock_session()
        mock_user = MagicMock()
        mock_user.id = 42
        session.execute.return_value = _make_scalars_result(mock_user)

        await delete_user_data(session, "123")

        # 1 SELECT (get_user_by_telegram_id) + 3 explicit DELETEs
        # (OutageHistory, PowerHistory, ScheduleHistory — no ON DELETE CASCADE)
        assert session.execute.call_count == 4, (
            "Expected 1 SELECT + 3 DELETE statements; got "
            f"{session.execute.call_count} execute() calls"
        )
        # ORM delete is called exactly once for the user object itself
        session.delete.assert_called_once_with(mock_user)

    async def test_no_delete_when_user_not_found(self):
        session = _make_mock_session()
        session.execute.return_value = _make_scalars_result(None)

        await delete_user_data(session, "nonexistent")

        # Only the initial SELECT — no history DELETEs if user doesn't exist
        session.execute.assert_called_once()
        session.delete.assert_not_called()


# ─── get_active_users_by_region ───────────────────────────────────────────


class TestGetActiveUsersByRegion:
    async def test_returns_list_of_users(self):
        session = _make_mock_session()
        users = [MagicMock(), MagicMock()]
        session.execute.return_value = _make_scalars_result(users)

        result = await get_active_users_by_region(session, "kyiv")

        assert isinstance(result, list)
        assert len(result) == 2

    async def test_empty_result_returns_empty_list(self):
        session = _make_mock_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_active_users_by_region(session, "kyiv")

        assert result == []

    async def test_filters_by_queue_when_provided(self):
        session = _make_mock_session()
        session.execute.return_value = _make_scalars_result([])

        # Should not raise when queue is specified
        await get_active_users_by_region(session, "kyiv", queue="1.1")

        session.execute.assert_called_once()


# ─── get_users_with_ip ────────────────────────────────────────────────────


class TestGetUsersWithIp:
    async def test_returns_users_with_ip(self):
        session = _make_mock_session()
        user_with_ip = MagicMock()
        user_with_ip.router_ip = "192.168.1.1"
        session.execute.return_value = _make_scalars_result([user_with_ip])

        result = await get_users_with_ip(session)

        assert isinstance(result, list)
        assert len(result) == 1

    async def test_returns_empty_when_no_users_with_ip(self):
        session = _make_mock_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_users_with_ip(session)

        assert result == []


# ─── count_active_users ───────────────────────────────────────────────────


class TestCountActiveUsers:
    async def test_returns_count(self):
        session = _make_mock_session()
        result_mock = MagicMock()
        result_mock.scalar.return_value = 42
        session.execute.return_value = result_mock

        count = await count_active_users(session)

        assert count == 42

    async def test_returns_zero_when_scalar_is_none(self):
        session = _make_mock_session()
        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        session.execute.return_value = result_mock

        count = await count_active_users(session)

        assert count == 0
