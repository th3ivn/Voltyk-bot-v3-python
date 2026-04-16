"""Tests for bot/db/queries/users.py — uses mocked AsyncSession."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    return session


def _scalars_first(value):
    scalars = MagicMock()
    scalars.first.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalars_all(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _rows_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


def _make_user(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=1,
        telegram_id="111",
        username="test",
        region="kyiv",
        queue="1.1",
        is_active=True,
        notification_settings=SimpleNamespace(id=10),
        channel_config=SimpleNamespace(id=11),
        power_tracking=SimpleNamespace(id=12),
        message_tracking=SimpleNamespace(id=13),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# create_or_update_user — missing relation backfill branches (99-120)
# ---------------------------------------------------------------------------


class TestCreateOrUpdateUserRelationBackfill:
    """When a user exists but is missing relations, they get created."""

    async def test_missing_notification_settings_creates_one(self):
        """Line 99-102: existing user without notification_settings → created."""
        from bot.db.queries.users import create_or_update_user

        session = _make_session()
        user = _make_user(notification_settings=None)
        session.execute.return_value = _scalars_first(user)

        result = await create_or_update_user(session, 111, "test", "kyiv", "1.1")

        assert result.notification_settings is not None
        assert session.add.called

    async def test_missing_channel_config_creates_one(self):
        """Line 105-108: existing user without channel_config → created."""
        from bot.db.queries.users import create_or_update_user

        session = _make_session()
        # Has notification_settings but missing channel_config
        user = _make_user(channel_config=None)
        session.execute.return_value = _scalars_first(user)

        result = await create_or_update_user(session, 111, "test", "kyiv", "1.1")

        assert result.channel_config is not None

    async def test_missing_power_tracking_creates_one(self):
        """Line 111-114: existing user without power_tracking → created."""
        from bot.db.queries.users import create_or_update_user

        session = _make_session()
        user = _make_user(power_tracking=None)
        session.execute.return_value = _scalars_first(user)

        result = await create_or_update_user(session, 111, "test", "kyiv", "1.1")

        assert result.power_tracking is not None

    async def test_missing_message_tracking_creates_one(self):
        """Line 117-120: existing user without message_tracking → created."""
        from bot.db.queries.users import create_or_update_user

        session = _make_session()
        user = _make_user(message_tracking=None)
        session.execute.return_value = _scalars_first(user)

        result = await create_or_update_user(session, 111, "test", "kyiv", "1.1")

        assert result.message_tracking is not None

    async def test_all_relations_missing_creates_all(self):
        """All relations None → all 4 created."""
        from bot.db.queries.users import create_or_update_user

        session = _make_session()
        user = _make_user(
            notification_settings=None,
            channel_config=None,
            power_tracking=None,
            message_tracking=None,
        )
        session.execute.return_value = _scalars_first(user)

        result = await create_or_update_user(session, 111, "test", "kyiv", "1.1")

        assert result.notification_settings is not None
        assert result.channel_config is not None
        assert result.power_tracking is not None
        assert result.message_tracking is not None


# ---------------------------------------------------------------------------
# get_distinct_region_queue_pairs
# ---------------------------------------------------------------------------


class TestGetDistinctRegionQueuePairs:
    async def test_returns_list_of_tuples(self):
        from bot.db.queries.users import get_distinct_region_queue_pairs

        session = _make_session()
        pairs = [("kyiv", "1.1"), ("lviv", "2.2")]
        session.execute.return_value = _rows_result(pairs)

        result = await get_distinct_region_queue_pairs(session)

        assert result == [("kyiv", "1.1"), ("lviv", "2.2")]

    async def test_returns_empty_when_no_active_users(self):
        from bot.db.queries.users import get_distinct_region_queue_pairs

        session = _make_session()
        session.execute.return_value = _rows_result([])

        result = await get_distinct_region_queue_pairs(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_active_user_ids_paginated
# ---------------------------------------------------------------------------


class TestGetActiveUserIdsPaginated:
    async def test_returns_id_telegram_id_tuples(self):
        from bot.db.queries.users import get_active_user_ids_paginated

        session = _make_session()
        rows = [(1, "111"), (2, "222")]
        session.execute.return_value = _rows_result(rows)

        result = await get_active_user_ids_paginated(session, limit=100, offset=0)

        assert result == [(1, "111"), (2, "222")]

    async def test_empty_when_no_users(self):
        from bot.db.queries.users import get_active_user_ids_paginated

        session = _make_session()
        session.execute.return_value = _rows_result([])

        result = await get_active_user_ids_paginated(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_active_user_ids_cursor
# ---------------------------------------------------------------------------


class TestGetActiveUserIdsCursor:
    async def test_returns_rows_after_cursor(self):
        from bot.db.queries.users import get_active_user_ids_cursor

        session = _make_session()
        rows = [(5, "555"), (6, "666")]
        session.execute.return_value = _rows_result(rows)

        result = await get_active_user_ids_cursor(session, limit=100, after_id=4)

        assert result == [(5, "555"), (6, "666")]

    async def test_empty_at_end_of_cursor(self):
        from bot.db.queries.users import get_active_user_ids_cursor

        session = _make_session()
        session.execute.return_value = _rows_result([])

        result = await get_active_user_ids_cursor(session, after_id=999)

        assert result == []


# ---------------------------------------------------------------------------
# get_all_active_users
# ---------------------------------------------------------------------------


class TestGetAllActiveUsers:
    async def test_returns_user_list(self):
        from bot.db.queries.users import get_all_active_users

        session = _make_session()
        users = [_make_user(id=1), _make_user(id=2)]
        session.execute.return_value = _scalars_all(users)

        result = await get_all_active_users(session)

        assert result == users

    async def test_returns_empty_list(self):
        from bot.db.queries.users import get_all_active_users

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_all_active_users(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_active_users_paginated
# ---------------------------------------------------------------------------


class TestGetActiveUsersPaginated:
    async def test_returns_user_list(self):
        from bot.db.queries.users import get_active_users_paginated

        session = _make_session()
        users = [_make_user(id=1), _make_user(id=2)]
        session.execute.return_value = _scalars_all(users)

        result = await get_active_users_paginated(session, limit=10, offset=0)

        assert result == users

    async def test_empty_page(self):
        from bot.db.queries.users import get_active_users_paginated

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_active_users_paginated(session, limit=10, offset=100)

        assert result == []


# ---------------------------------------------------------------------------
# get_users_with_channel
# ---------------------------------------------------------------------------


class TestGetUsersWithChannel:
    async def test_returns_users_with_active_channel(self):
        from bot.db.queries.users import get_users_with_channel

        session = _make_session()
        user = _make_user()
        session.execute.return_value = _scalars_all([user])

        result = await get_users_with_channel(session)

        assert result == [user]

    async def test_empty_when_no_channel_users(self):
        from bot.db.queries.users import get_users_with_channel

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_users_with_channel(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_user_by_channel_id
# ---------------------------------------------------------------------------


class TestGetUserByChannelId:
    async def test_returns_user_when_found(self):
        from bot.db.queries.users import get_user_by_channel_id

        session = _make_session()
        user = _make_user()
        scalars = MagicMock()
        scalars.first.return_value = user
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars
        session.execute.return_value = result_mock

        result = await get_user_by_channel_id(session, "-1001234567890")

        assert result is user

    async def test_returns_none_when_not_found(self):
        from bot.db.queries.users import get_user_by_channel_id

        session = _make_session()
        scalars = MagicMock()
        scalars.first.return_value = None
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars
        session.execute.return_value = result_mock

        result = await get_user_by_channel_id(session, "-1001234567890")

        assert result is None


# ---------------------------------------------------------------------------
# count_total_users
# ---------------------------------------------------------------------------


class TestCountTotalUsers:
    async def test_returns_total_count(self):
        from bot.db.queries.users import count_total_users

        session = _make_session()
        session.execute.return_value = _scalar_result(42)

        result = await count_total_users(session)

        assert result == 42

    async def test_returns_zero_when_scalar_none(self):
        """scalar() returns None → or 0 fallback."""
        from bot.db.queries.users import count_total_users

        session = _make_session()
        session.execute.return_value = _scalar_result(None)

        result = await count_total_users(session)

        assert result == 0


# ---------------------------------------------------------------------------
# get_recent_users
# ---------------------------------------------------------------------------


class TestGetRecentUsers:
    async def test_returns_user_list(self):
        from bot.db.queries.users import get_recent_users

        session = _make_session()
        users = [_make_user(id=10), _make_user(id=9)]
        session.execute.return_value = _scalars_all(users)

        result = await get_recent_users(session, limit=2)

        assert result == users

    async def test_returns_empty_when_no_users(self):
        from bot.db.queries.users import get_recent_users

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_recent_users(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_active_power_users_by_region_queue_cursor
# ---------------------------------------------------------------------------


class TestGetActivePowerUsersByRegionQueueCursor:
    """Tests for get_active_power_users_by_region_queue_cursor() — cursor pagination."""

    async def test_returns_users_for_region_queue(self):
        """Returns active users matching region/queue on first page."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        users = [_make_user(id=1, region="kyiv", queue="1"), _make_user(id=2, region="kyiv", queue="1")]
        session.execute.return_value = _scalars_all(users)

        result = await get_active_power_users_by_region_queue_cursor(session, region="kyiv", queue="1")

        assert result == users
        session.execute.assert_called_once()

    async def test_returns_empty_when_no_users(self):
        """No users matching criteria → empty list."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_active_power_users_by_region_queue_cursor(session, region="lviv", queue="2")

        assert result == []

    async def test_respects_after_id(self):
        """after_id filters users with id > after_id."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        users = [_make_user(id=10)]
        session.execute.return_value = _scalars_all(users)

        result = await get_active_power_users_by_region_queue_cursor(
            session, region="kyiv", queue="1", after_id=5
        )

        assert result == users
        session.execute.assert_called_once()

    async def test_respects_limit(self):
        """Returns at most `limit` items."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        users = [_make_user(id=i) for i in range(1, 4)]
        session.execute.return_value = _scalars_all(users)

        result = await get_active_power_users_by_region_queue_cursor(
            session, region="kyiv", queue="1", limit=3
        )

        assert len(result) == 3

    async def test_returns_list_type(self):
        """Return value is always a list."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_active_power_users_by_region_queue_cursor(session, region="x", queue="y")

        assert isinstance(result, list)

    async def test_cursor_second_page(self):
        """after_id=last batch id yields next page correctly."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        page2 = [_make_user(id=501)]
        session.execute.return_value = _scalars_all(page2)

        result = await get_active_power_users_by_region_queue_cursor(
            session, region="kyiv", queue="1", limit=500, after_id=500
        )

        assert result == page2

    async def test_different_regions_independent(self):
        """Two calls with different regions hit execute twice independently."""
        from bot.db.queries.users import get_active_power_users_by_region_queue_cursor

        session = _make_session()
        kyiv_users = [_make_user(id=1, region="kyiv", queue="1")]
        lviv_users = [_make_user(id=2, region="lviv", queue="1")]
        session.execute.side_effect = [_scalars_all(kyiv_users), _scalars_all(lviv_users)]

        r1 = await get_active_power_users_by_region_queue_cursor(session, region="kyiv", queue="1")
        r2 = await get_active_power_users_by_region_queue_cursor(session, region="lviv", queue="1")

        assert r1 == kyiv_users
        assert r2 == lviv_users
        assert session.execute.call_count == 2
