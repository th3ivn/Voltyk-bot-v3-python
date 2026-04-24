"""Tests for bot/db/queries/settings.py — uses mocked AsyncSession."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


def _scalars_first(value):
    scalars = MagicMock()
    scalars.first.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# get_setting
# ---------------------------------------------------------------------------


class TestGetSetting:
    async def test_returns_value_when_found(self):
        """Found Setting row → its .value is returned."""
        from bot.db.queries.settings import get_setting

        session = _make_session()
        session.execute.return_value = _scalars_first(SimpleNamespace(key="foo", value="bar"))

        result = await get_setting(session, key="foo")

        assert result == "bar"
        session.execute.assert_called_once()

    async def test_returns_none_when_not_found(self):
        """No matching row → None returned."""
        from bot.db.queries.settings import get_setting

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_setting(session, key="missing")

        assert result is None

    async def test_returns_empty_string_value(self):
        """Setting with value='' is returned as empty string, not None."""
        from bot.db.queries.settings import get_setting

        session = _make_session()
        session.execute.return_value = _scalars_first(SimpleNamespace(key="k", value=""))

        result = await get_setting(session, key="k")

        assert result == ""


# ---------------------------------------------------------------------------
# set_setting
# ---------------------------------------------------------------------------


class TestSetSetting:
    async def test_execute_called_with_upsert(self):
        """pg_insert ON CONFLICT DO UPDATE executed."""
        from bot.db.queries.settings import set_setting

        session = _make_session()

        await set_setting(session, key="theme", value="dark")

        session.execute.assert_called_once()

    async def test_different_keys_each_call_execute(self):
        """Each set_setting call issues one execute regardless of key."""
        from bot.db.queries.settings import set_setting

        session = _make_session()

        await set_setting(session, key="a", value="1")
        await set_setting(session, key="b", value="2")

        assert session.execute.call_count == 2


# ---------------------------------------------------------------------------
# delete_setting
# ---------------------------------------------------------------------------


class TestDeleteSetting:
    async def test_execute_called(self):
        from bot.db.queries.settings import delete_setting

        session = _make_session()
        await delete_setting(session, key="foo")

        session.execute.assert_called_once()

    async def test_no_op_on_missing_key_does_not_raise(self):
        """delete_setting is idempotent — deleting a nonexistent row is a
        no-op at the SQL level (DELETE returns rowcount=0)."""
        from bot.db.queries.settings import delete_setting

        session = _make_session()
        # Simulate "no row affected" by not raising — SQLAlchemy handles
        # this naturally; our query should not care about the result.
        await delete_setting(session, key="never-existed")

        session.execute.assert_called_once()
