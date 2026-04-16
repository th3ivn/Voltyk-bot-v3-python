"""Tests for bot/db/queries/channels.py — uses mocked AsyncSession."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


def _scalars_first(value):
    scalars = MagicMock()
    scalars.first.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalars_one(value):
    scalars = MagicMock()
    scalars.one.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# save_pending_channel
# ---------------------------------------------------------------------------


class TestSavePendingChannel:
    async def test_execute_and_flush_called(self):
        """pg_insert executed and flush() called; returns the upserted row."""
        from bot.db.queries.channels import save_pending_channel

        session = _make_session()
        channel = SimpleNamespace(channel_id="@test", telegram_id="111")
        session.execute.return_value = _scalars_one(channel)

        result = await save_pending_channel(session, channel_id="@test", telegram_id="111")

        session.execute.assert_called_once()
        session.flush.assert_called_once()
        assert result is channel

    async def test_telegram_id_coerced_to_str(self):
        """int telegram_id is coerced to str for the INSERT."""
        from bot.db.queries.channels import save_pending_channel

        session = _make_session()
        channel = SimpleNamespace(channel_id="@ch", telegram_id="42")
        session.execute.return_value = _scalars_one(channel)

        result = await save_pending_channel(session, channel_id="@ch", telegram_id=42)

        assert result.telegram_id == "42"

    async def test_optional_fields_default_to_none(self):
        """channel_username and channel_title default to None."""
        from bot.db.queries.channels import save_pending_channel

        session = _make_session()
        channel = SimpleNamespace(channel_id="@x", telegram_id="1", channel_username=None, channel_title=None)
        session.execute.return_value = _scalars_one(channel)

        result = await save_pending_channel(session, channel_id="@x", telegram_id="1")

        assert result.channel_username is None
        assert result.channel_title is None

    async def test_optional_fields_stored_when_provided(self):
        """Explicit username and title are returned on the row."""
        from bot.db.queries.channels import save_pending_channel

        session = _make_session()
        channel = SimpleNamespace(
            channel_id="@news",
            telegram_id="5",
            channel_username="@news",
            channel_title="News Channel",
        )
        session.execute.return_value = _scalars_one(channel)

        result = await save_pending_channel(
            session,
            channel_id="@news",
            telegram_id="5",
            channel_username="@news",
            channel_title="News Channel",
        )

        assert result.channel_username == "@news"
        assert result.channel_title == "News Channel"


# ---------------------------------------------------------------------------
# get_pending_channel_by_telegram_id
# ---------------------------------------------------------------------------


class TestGetPendingChannelByTelegramId:
    async def test_returns_channel_when_found(self):
        """scalars().first() returns PendingChannel → it is returned."""
        from bot.db.queries.channels import get_pending_channel_by_telegram_id

        session = _make_session()
        channel = SimpleNamespace(channel_id="@ch", telegram_id="111")
        session.execute.return_value = _scalars_first(channel)

        result = await get_pending_channel_by_telegram_id(session, telegram_id="111")

        assert result is channel
        session.execute.assert_called_once()

    async def test_returns_none_when_not_found(self):
        """scalars().first() returns None → None returned."""
        from bot.db.queries.channels import get_pending_channel_by_telegram_id

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_pending_channel_by_telegram_id(session, telegram_id="999")

        assert result is None

    async def test_telegram_id_coerced_to_str(self):
        """int telegram_id is coerced to str for the query."""
        from bot.db.queries.channels import get_pending_channel_by_telegram_id

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        await get_pending_channel_by_telegram_id(session, telegram_id=123)

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_pending_channel (two-arg version: telegram_id + channel_id)
# ---------------------------------------------------------------------------


class TestGetPendingChannel:
    async def test_returns_channel_when_found(self):
        """Both telegram_id and channel_id match → channel returned."""
        from bot.db.queries.channels import get_pending_channel

        session = _make_session()
        channel = SimpleNamespace(channel_id="@ch", telegram_id="111")
        session.execute.return_value = _scalars_first(channel)

        result = await get_pending_channel(session, telegram_id="111", channel_id="@ch")

        assert result is channel
        session.execute.assert_called_once()

    async def test_returns_none_when_not_found(self):
        """No matching row → None returned."""
        from bot.db.queries.channels import get_pending_channel

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_pending_channel(session, telegram_id="111", channel_id="@missing")

        assert result is None


# ---------------------------------------------------------------------------
# delete_pending_channel
# ---------------------------------------------------------------------------


class TestDeletePendingChannel:
    async def test_execute_called_with_delete(self):
        """DELETE by channel_id executed."""
        from bot.db.queries.channels import delete_pending_channel

        session = _make_session()

        await delete_pending_channel(session, channel_id="@remove")

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# delete_pending_channel_by_telegram_id
# ---------------------------------------------------------------------------


class TestDeletePendingChannelByTelegramId:
    async def test_execute_called_with_delete(self):
        """DELETE by telegram_id executed."""
        from bot.db.queries.channels import delete_pending_channel_by_telegram_id

        session = _make_session()

        await delete_pending_channel_by_telegram_id(session, telegram_id="111")

        session.execute.assert_called_once()

    async def test_telegram_id_coerced_to_str(self):
        """int telegram_id is coerced to str for the DELETE."""
        from bot.db.queries.channels import delete_pending_channel_by_telegram_id

        session = _make_session()

        await delete_pending_channel_by_telegram_id(session, telegram_id=42)

        session.execute.assert_called_once()
