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
