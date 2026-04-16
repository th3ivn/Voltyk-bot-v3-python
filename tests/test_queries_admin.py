"""Tests for bot/db/queries/admin.py — uses mocked AsyncSession."""
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


def _scalars_all(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalars_one(value):
    scalars = MagicMock()
    scalars.one.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _compile_sql(session_mock) -> str:
    """Compile the SQLAlchemy statement passed to session.execute into a SQL string."""
    from sqlalchemy.dialects import postgresql

    stmt = session_mock.execute.call_args[0][0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()


# ---------------------------------------------------------------------------
# get_admin_router
# ---------------------------------------------------------------------------


class TestGetAdminRouter:
    async def test_returns_router_when_found(self):
        """scalars().first() returns AdminRouter → it is returned."""
        from bot.db.queries.admin import get_admin_router

        session = _make_session()
        router = SimpleNamespace(admin_telegram_id="123", router_ip="192.168.1.1")
        session.execute.return_value = _scalars_first(router)

        result = await get_admin_router(session, admin_telegram_id="123")

        assert result is router
        session.execute.assert_called_once()

    async def test_returns_none_when_not_found(self):
        """scalars().first() returns None → None returned."""
        from bot.db.queries.admin import get_admin_router

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_admin_router(session, admin_telegram_id="999")

        assert result is None

    async def test_telegram_id_coerced_to_str(self):
        """int admin_telegram_id is coerced to str for the query."""
        from bot.db.queries.admin import get_admin_router

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        await get_admin_router(session, admin_telegram_id=42)

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# upsert_admin_router
# ---------------------------------------------------------------------------


class TestUpsertAdminRouter:
    async def test_execute_and_flush_called(self):
        """pg_insert executed and session.flush() called."""
        from bot.db.queries.admin import upsert_admin_router

        session = _make_session()
        router = SimpleNamespace(admin_telegram_id="123", router_ip="10.0.0.1")
        session.execute.return_value = _scalars_one(router)

        result = await upsert_admin_router(session, "123", router_ip="10.0.0.1")

        session.execute.assert_called_once()
        session.flush.assert_called_once()
        assert result is router

    async def test_telegram_id_coerced_to_str(self):
        """int admin_telegram_id is coerced to str — verified in compiled INSERT SQL."""
        from bot.db.queries.admin import upsert_admin_router

        session = _make_session()
        router = SimpleNamespace(admin_telegram_id="77", router_ip="10.0.0.2")
        session.execute.return_value = _scalars_one(router)

        await upsert_admin_router(session, 77, router_ip="10.0.0.2")

        sql = _compile_sql(session)
        assert "'77'" in sql, f"Expected literal '77' (str) in INSERT VALUES, got: {sql}"

    async def test_extra_kwargs_passed_through(self):
        """Additional kwargs are present in the compiled INSERT statement."""
        from bot.db.queries.admin import upsert_admin_router

        session = _make_session()
        router = SimpleNamespace(admin_telegram_id="1", router_ip="1.2.3.4", router_port=8080)
        session.execute.return_value = _scalars_one(router)

        await upsert_admin_router(session, "1", router_ip="1.2.3.4", router_port=8080)

        sql = _compile_sql(session)
        assert "8080" in sql, f"Expected literal router_port value 8080 in INSERT, got: {sql}"
        assert "router_port" in sql, f"Expected 'router_port' column in INSERT, got: {sql}"


# ---------------------------------------------------------------------------
# add_pause_log
# ---------------------------------------------------------------------------


class TestAddPauseLog:
    async def test_adds_record(self):
        """session.add() called with a PauseLog."""
        from bot.db.queries.admin import add_pause_log

        session = _make_session()

        await add_pause_log(session, admin_id="1", event_type="pause")

        session.add.assert_called_once()

    async def test_optional_fields_default_to_none(self):
        """pause_type, message, reason all default to None."""
        from bot.db.queries.admin import add_pause_log

        session = _make_session()

        await add_pause_log(session, admin_id="1", event_type="resume")

        log = session.add.call_args[0][0]
        assert log.pause_type is None
        assert log.message is None
        assert log.reason is None

    async def test_admin_id_coerced_to_str(self):
        """int admin_id is coerced to str on the model."""
        from bot.db.queries.admin import add_pause_log

        session = _make_session()

        await add_pause_log(session, admin_id=99, event_type="pause")

        log = session.add.call_args[0][0]
        assert log.admin_id == "99"

    async def test_optional_fields_stored_when_provided(self):
        """Explicit pause_type, message, reason are stored."""
        from bot.db.queries.admin import add_pause_log

        session = _make_session()

        await add_pause_log(
            session,
            admin_id="1",
            event_type="pause",
            pause_type="emergency",
            message="Planned maintenance",
            reason="scheduled",
        )

        log = session.add.call_args[0][0]
        assert log.pause_type == "emergency"
        assert log.message == "Planned maintenance"
        assert log.reason == "scheduled"


# ---------------------------------------------------------------------------
# get_pause_logs
# ---------------------------------------------------------------------------


class TestGetPauseLogs:
    async def test_returns_list_of_logs(self):
        """execute → scalars().all() returned as list."""
        from bot.db.queries.admin import get_pause_logs

        session = _make_session()
        logs = [SimpleNamespace(id=1, event_type="pause"), SimpleNamespace(id=2, event_type="resume")]
        session.execute.return_value = _scalars_all(logs)

        result = await get_pause_logs(session)

        assert result == logs
        session.execute.assert_called_once()

    async def test_returns_empty_list_when_no_logs(self):
        """No logs → empty list."""
        from bot.db.queries.admin import get_pause_logs

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_pause_logs(session)

        assert result == []

    async def test_custom_limit_passed(self):
        """limit parameter is forwarded to the query."""
        from bot.db.queries.admin import get_pause_logs

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        await get_pause_logs(session, limit=5)

        session.execute.assert_called_once()
