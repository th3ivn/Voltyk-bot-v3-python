"""Shared pytest fixtures for the Voltyk Bot test suite."""
from __future__ import annotations

import asyncio
import inspect
import os

# Set required environment variables BEFORE any bot modules are imported,
# so pydantic-settings can find BOT_TOKEN and not raise ValidationError.
os.environ.setdefault("BOT_TOKEN", "0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA0")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Simple mock ORM objects (avoid importing SQLAlchemy models in unit tests)
# ---------------------------------------------------------------------------

def make_notification_settings(**kwargs) -> SimpleNamespace:
    defaults = dict(
        notify_schedule_changes=True,
        notify_remind_off=True,
        notify_fact_off=True,
        notify_remind_on=True,
        notify_fact_on=True,
        remind_15m=True,
        remind_30m=False,
        remind_1h=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_channel_config(**kwargs) -> SimpleNamespace:
    defaults = dict(
        channel_id=-1001234567890,
        ch_notify_schedule=True,
        ch_remind_1h=False,
        ch_remind_30m=False,
        ch_remind_15m=True,
        ch_notify_fact_off=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_user(**kwargs) -> SimpleNamespace:
    defaults = dict(
        telegram_id="123456789",
        username="testuser",
        region="kyiv",
        queue="1.1",
        router_ip="192.168.1.1",
        is_active=True,
        notification_settings=make_notification_settings(),
        channel_config=make_channel_config(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture
def user():
    return make_user()


@pytest.fixture
def ns():
    return make_notification_settings()


@pytest.fixture
def cc():
    return make_channel_config()


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
    return bot


def pytest_pyfunc_call(pyfuncitem):
    """Fallback async runner when pytest-asyncio plugin is unavailable.

    Runs coroutine test functions in a dedicated event loop.
    If pytest-asyncio is installed, its own hook normally executes first.
    """
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        loop.run_until_complete(test_func(**kwargs))
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    return True
