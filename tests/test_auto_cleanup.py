from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteMessage
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession


class TestAutoCleanupMiddlewareHelpers:
    def test_as_private_chat_id(self):
        from bot.middlewares.auto_cleanup import _as_private_chat_id

        assert _as_private_chat_id(123) == 123
        assert _as_private_chat_id("456") == 456
        assert _as_private_chat_id(-100123) is None
        assert _as_private_chat_id("not-a-number") is None

    def test_extract_message_ids(self):
        from bot.middlewares.auto_cleanup import _extract_message_ids

        msg = MagicMock(spec=Message)
        msg.message_id = 10
        msg2 = MagicMock(spec=Message)
        msg2.message_id = 11

        assert _extract_message_ids(msg) == [10]
        assert _extract_message_ids([msg, msg2, object()]) == [10, 11]
        assert _extract_message_ids(True) == []


class TestAutoCleanupCommandMiddleware:
    async def test_passthrough_non_command(self):
        from bot.middlewares.auto_cleanup import AutoCleanupCommandMiddleware

        middleware = AutoCleanupCommandMiddleware()
        handler = AsyncMock(return_value="ok")
        event = MagicMock(spec=Message)
        event.text = "hello"

        result = await middleware(handler=handler, event=event, data={})

        assert result == "ok"
        handler.assert_awaited_once()

    async def test_queues_command_when_enabled(self):
        from bot.middlewares.auto_cleanup import AutoCleanupCommandMiddleware

        middleware = AutoCleanupCommandMiddleware()
        handler = AsyncMock(return_value="ok")
        event = MagicMock(spec=Message)
        event.text = "/start"
        event.message_id = 42
        event.chat.id = 777
        event.from_user.id = 555

        session = MagicMock(spec=AsyncSession)
        user = SimpleNamespace(id=9, notification_settings=SimpleNamespace(auto_delete_commands=True))

        with (
            patch("bot.middlewares.auto_cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.middlewares.auto_cleanup.queue_message_for_delete", AsyncMock()) as queue_mock,
        ):
            await middleware(handler=handler, event=event, data={"session": session})

        queue_mock.assert_awaited_once_with(
            user_id=9,
            chat_id=777,
            message_id=42,
            source="command",
        )

    async def test_queue_error_is_swallowed(self):
        from bot.middlewares.auto_cleanup import AutoCleanupCommandMiddleware

        middleware = AutoCleanupCommandMiddleware()
        handler = AsyncMock(return_value="ok")
        event = MagicMock(spec=Message)
        event.text = "/start"
        event.message_id = 42
        event.chat.id = 777
        event.from_user.id = 555

        session = MagicMock(spec=AsyncSession)
        user = SimpleNamespace(id=9, notification_settings=SimpleNamespace(auto_delete_commands=True))

        with (
            patch("bot.middlewares.auto_cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch(
                "bot.middlewares.auto_cleanup.queue_message_for_delete",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            result = await middleware(handler=handler, event=event, data={"session": session})

        assert result == "ok"


class TestAutoCleanupResponseMiddleware:
    async def test_skips_delete_message_method(self):
        from bot.middlewares.auto_cleanup import AutoCleanupResponseMiddleware

        middleware = AutoCleanupResponseMiddleware()
        make_request = AsyncMock(return_value=True)
        method = DeleteMessage(chat_id=1, message_id=10)

        with patch("bot.middlewares.auto_cleanup._queue_bot_messages", AsyncMock()) as queue_mock:
            result = await middleware(make_request=make_request, bot=MagicMock(), method=method)

        assert result is True
        queue_mock.assert_not_awaited()

    async def test_queues_response_messages(self):
        from bot.middlewares.auto_cleanup import AutoCleanupResponseMiddleware

        middleware = AutoCleanupResponseMiddleware()
        msg = MagicMock(spec=Message)
        msg.message_id = 77
        make_request = AsyncMock(return_value=msg)
        method = SimpleNamespace(chat_id=123)

        with patch("bot.middlewares.auto_cleanup._queue_bot_messages", AsyncMock()) as queue_mock:
            result = await middleware(make_request=make_request, bot=MagicMock(), method=method)

        assert result is msg
        queue_mock.assert_awaited_once_with(123, [77])

    async def test_queue_error_is_swallowed(self):
        from bot.middlewares.auto_cleanup import AutoCleanupResponseMiddleware

        middleware = AutoCleanupResponseMiddleware()
        msg = MagicMock(spec=Message)
        msg.message_id = 77
        make_request = AsyncMock(return_value=msg)
        method = SimpleNamespace(chat_id=123)

        with patch(
            "bot.middlewares.auto_cleanup._queue_bot_messages",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = await middleware(make_request=make_request, bot=MagicMock(), method=method)

        assert result is msg


@asynccontextmanager
async def _async_session_ctx(session: AsyncMock):
    yield session


class TestAutoCleanupService:
    async def test_queue_message_for_delete_uses_min_delay_and_commits(self):
        from bot.services.auto_cleanup import queue_message_for_delete

        session = AsyncMock()

        with (
            patch("bot.services.auto_cleanup.settings.AUTO_DELETE_DELAY_MINUTES", 120),
            patch(
                "bot.services.auto_cleanup.async_session",
                side_effect=lambda: _async_session_ctx(session),
            ),
            patch("bot.db.queries.enqueue_auto_delete", AsyncMock()) as enqueue_mock,
        ):
            await queue_message_for_delete(
                user_id=1,
                chat_id=2,
                message_id=3,
                source="command",
                delay_minutes=0,
            )

        session.commit.assert_awaited_once()
        kwargs = enqueue_mock.call_args.kwargs
        assert kwargs["user_id"] == 1
        assert kwargs["chat_id"] == 2
        assert kwargs["message_id"] == 3
        assert kwargs["source"] == "command"
        assert isinstance(kwargs["delete_at"], datetime)

    async def test_try_delete_handles_exceptions(self):
        from bot.services.auto_cleanup import _try_delete

        bot = AsyncMock()
        bot.delete_message = AsyncMock(return_value=True)
        assert await _try_delete(bot, chat_id=1, message_id=10) is True

        bot.delete_message = AsyncMock(
            side_effect=TelegramForbiddenError(method=MagicMock(), message="forbidden")
        )
        assert await _try_delete(bot, chat_id=1, message_id=10) is True

        bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="message to delete not found")
        )
        assert await _try_delete(bot, chat_id=1, message_id=10) is True

        bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="some other bad request")
        )
        assert await _try_delete(bot, chat_id=1, message_id=10) is False

        bot.delete_message = AsyncMock(side_effect=RuntimeError("boom"))
        assert await _try_delete(bot, chat_id=1, message_id=10) is False

    async def test_auto_cleanup_loop_processes_due_rows(self):
        from bot.services import auto_cleanup as mod

        session = AsyncMock()
        due_rows = [
            SimpleNamespace(id=1, chat_id="bad-chat", message_id=10),
            SimpleNamespace(id=2, chat_id="123", message_id=11),
        ]

        async def _remove(_session, ids):
            mod.stop_auto_cleanup()
            return len(ids)

        with (
            patch("bot.services.auto_cleanup.async_session", side_effect=lambda: _async_session_ctx(session)),
            patch("bot.services.auto_cleanup.get_due_auto_delete", AsyncMock(return_value=due_rows)),
            patch("bot.services.auto_cleanup._try_delete", AsyncMock(return_value=True)) as try_delete_mock,
            patch("bot.services.auto_cleanup.remove_auto_delete_entries", AsyncMock(side_effect=_remove)) as remove_mock,
            patch("bot.services.auto_cleanup.heartbeat.beat"),
            patch("bot.services.auto_cleanup.asyncio.sleep", AsyncMock()),
        ):
            mod._running = True
            await mod.auto_cleanup_loop(bot=MagicMock())

        assert try_delete_mock.await_count == 1
        _, kwargs = try_delete_mock.await_args
        assert kwargs["chat_id"] == 123
        assert kwargs["message_id"] == 11
        remove_mock.assert_awaited_once_with(session, [1, 2])
        session.commit.assert_awaited_once()

    async def test_stop_auto_cleanup(self):
        from bot.services import auto_cleanup as mod

        mod._running = True
        mod.stop_auto_cleanup()
        assert mod._running is False

    async def test_auto_cleanup_loop_logs_and_continues_on_query_error(self):
        from bot.services import auto_cleanup as mod

        session = AsyncMock()
        sleep_mock = AsyncMock(side_effect=[asyncio.CancelledError()])

        with (
            patch("bot.services.auto_cleanup.async_session", side_effect=lambda: _async_session_ctx(session)),
            patch("bot.services.auto_cleanup.get_due_auto_delete", AsyncMock(side_effect=RuntimeError("db failed"))),
            patch("bot.services.auto_cleanup.logger") as logger_mock,
            patch("bot.services.auto_cleanup.heartbeat.beat"),
            patch("bot.services.auto_cleanup.asyncio.sleep", sleep_mock),
        ):
            mod._running = True
            with pytest.raises(asyncio.CancelledError):
                await mod.auto_cleanup_loop(bot=MagicMock())

        logger_mock.exception.assert_called_once()
