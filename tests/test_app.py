"""Unit tests for bot/app.py bootstrap logic."""
from __future__ import annotations

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from bot import app


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
