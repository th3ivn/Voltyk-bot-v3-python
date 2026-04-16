"""Unit tests for DATABASE_URL normalization and SSL behavior."""
from __future__ import annotations

import ssl

from bot.db import session


def test_prepare_database_url_enables_verified_ssl_by_default(monkeypatch):
    monkeypatch.setattr(session.settings, "DB_SSL_INSECURE_SKIP_VERIFY", False)
    url, connect_args = session._prepare_database_url(
        "postgresql://u:p@example.com:5432/db?sslmode=require&channel_binding=require"
    )

    assert url.startswith("postgresql+asyncpg://")
    assert "sslmode=" not in url
    assert "channel_binding=" not in url
    assert "ssl" in connect_args
    assert connect_args["ssl"].verify_mode != ssl.CERT_NONE
    assert connect_args["ssl"].check_hostname is True


def test_prepare_database_url_can_disable_ssl_verification_explicitly(monkeypatch):
    monkeypatch.setattr(session.settings, "DB_SSL_INSECURE_SKIP_VERIFY", True)
    _url, connect_args = session._prepare_database_url(
        "postgresql://u:p@example.com:5432/db?sslmode=require"
    )

    assert connect_args["ssl"].verify_mode == ssl.CERT_NONE
    assert connect_args["ssl"].check_hostname is False


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


class TestGetSession:
    async def test_yields_session(self):
        """get_session() yields the session from async_session() context manager."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.db.session.async_session", return_value=session_ctx):
            gen = session.get_session()
            yielded = await gen.__anext__()

        assert yielded is mock_session

    async def test_context_manager_entered_and_exited(self):
        """__aenter__ and __aexit__ are both called during the generator lifecycle."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.db.session.async_session", return_value=session_ctx):
            gen = session.get_session()
            await gen.__anext__()
            try:
                await gen.aclose()
            except StopAsyncIteration:
                pass

        session_ctx.__aenter__.assert_awaited_once()
        session_ctx.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# check_db_connectivity
# ---------------------------------------------------------------------------


class TestCheckDbConnectivity:
    async def test_executes_select_1(self):
        """check_db_connectivity() opens a connection and runs SELECT 1."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = AsyncMock()
        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = conn_ctx

        with patch("bot.db.session.engine", mock_engine):
            await session.check_db_connectivity()

        mock_conn.execute.assert_awaited_once()
        executed_stmt = str(mock_conn.execute.call_args[0][0])
        assert "SELECT" in executed_stmt.upper()

    async def test_propagates_exception_on_failure(self):
        """If the DB is unreachable, the exception propagates to the caller."""
        from unittest.mock import AsyncMock, MagicMock, patch

        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(side_effect=OSError("connection refused"))
        conn_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = conn_ctx

        raised = False
        with patch("bot.db.session.engine", mock_engine):
            try:
                await session.check_db_connectivity()
            except OSError:
                raised = True

        assert raised
