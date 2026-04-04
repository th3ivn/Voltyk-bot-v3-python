"""Tests for database URL preparation and SSL behavior."""
from __future__ import annotations

import ssl

from bot.db import session as db_session


def test_prepare_database_url_keeps_tls_verification_enabled_by_default(monkeypatch):
    monkeypatch.setattr(db_session.settings, "DB_SSL_INSECURE_SKIP_VERIFY", False)

    clean_url, connect_args = db_session._prepare_database_url(
        "postgresql://u:p@db.example.com:5432/app?sslmode=require"
    )

    assert clean_url.startswith("postgresql+asyncpg://")
    assert "sslmode=" not in clean_url
    assert "ssl" in connect_args
    ssl_ctx = connect_args["ssl"]
    assert isinstance(ssl_ctx, ssl.SSLContext)
    assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED


def test_prepare_database_url_can_disable_tls_verification_when_explicitly_requested(monkeypatch):
    monkeypatch.setattr(db_session.settings, "DB_SSL_INSECURE_SKIP_VERIFY", True)

    _, connect_args = db_session._prepare_database_url(
        "postgresql://u:p@db.example.com:5432/app?sslmode=require"
    )

    ssl_ctx = connect_args["ssl"]
    assert isinstance(ssl_ctx, ssl.SSLContext)
    assert ssl_ctx.verify_mode == ssl.CERT_NONE
    assert ssl_ctx.check_hostname is False
