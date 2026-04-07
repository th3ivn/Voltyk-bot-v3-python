"""Tests for bot/handlers/admin/broadcast.py.

Coverage targets (current: 22%):
- admin_broadcast: not admin, already running, normal → enter waiting_for_text
- broadcast_text: not admin, no text, text too long, valid → preview
- broadcast_edit_text: not admin, normal → back to waiting_for_text
- broadcast_confirm_send: not admin, already running, normal → create_task
- broadcast_cancel_active: not admin, not running, running → set cancel
- broadcast_cancel: not admin, normal → clear + edit_text
- _run_broadcast: all sent, ForbiddenError (deactivate), RetryAfter+retry,
  RetryAfter exceeds retries, generic exception, cancel mid-batch, summary
- is_broadcast_running: task=None, task done, task running
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_broadcast_state() -> None:
    """Reset module-level broadcast globals between tests."""
    import bot.handlers.admin.broadcast as bcast

    bcast._active_broadcast = None
    bcast._broadcast_cancel = asyncio.Event()
    bcast._broadcast_lock = asyncio.Lock()


def _make_callback(user_id: int = 42, data: str = "") -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id)
    cb.data = data
    cb.bot = AsyncMock()
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    return cb


def _make_message(user_id: int = 42, text: str | None = "hello") -> MagicMock:
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=user_id)
    msg.text = text
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _make_state() -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"broadcast_text": "test msg"})
    return state


# ---------------------------------------------------------------------------
# is_broadcast_running
# ---------------------------------------------------------------------------


class TestIsBroadcastRunning:
    def setup_method(self):
        _reset_broadcast_state()

    def test_none_returns_false(self):
        from bot.handlers.admin.broadcast import is_broadcast_running

        assert is_broadcast_running() is False

    def test_done_task_returns_false(self):
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import is_broadcast_running

        task = MagicMock()
        task.done.return_value = True
        bcast._active_broadcast = task
        assert is_broadcast_running() is False

    def test_running_task_returns_true(self):
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import is_broadcast_running

        task = MagicMock()
        task.done.return_value = False
        bcast._active_broadcast = task
        assert is_broadcast_running() is True


# ---------------------------------------------------------------------------
# admin_broadcast
# ---------------------------------------------------------------------------


class TestAdminBroadcast:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_not_admin_denied(self):
        from bot.handlers.admin.broadcast import admin_broadcast

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await admin_broadcast(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")
        state.set_state.assert_not_awaited()

    async def test_broadcast_already_running(self):
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import admin_broadcast

        running_task = MagicMock()
        running_task.done.return_value = False
        bcast._active_broadcast = running_task

        cb = _make_callback(user_id=42)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await admin_broadcast(cb, state)

        cb.answer.assert_awaited_once_with("⚠️ Розсилка вже виконується", show_alert=True)
        state.set_state.assert_not_awaited()

    async def test_normal_enters_waiting_state(self):
        from bot.handlers.admin.broadcast import admin_broadcast

        cb = _make_callback(user_id=42)
        state = _make_state()
        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch("bot.handlers.admin.broadcast.get_broadcast_cancel_keyboard", return_value=MagicMock()),
        ):
            mock_settings.is_admin.return_value = True
            await admin_broadcast(cb, state)

        cb.answer.assert_awaited_once_with()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# broadcast_text
# ---------------------------------------------------------------------------


class TestBroadcastText:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_not_admin_clears_state(self):
        from bot.handlers.admin.broadcast import broadcast_text

        msg = _make_message(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_text(msg, state)

        state.clear.assert_awaited_once()
        msg.reply.assert_not_awaited()

    async def test_no_text_replies_error(self):
        from bot.handlers.admin.broadcast import broadcast_text

        msg = _make_message(user_id=42, text=None)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_text(msg, state)

        msg.reply.assert_awaited_once()
        assert "текст" in msg.reply.call_args[0][0].lower()

    async def test_text_too_long_replies_error(self):
        from bot.handlers.admin.broadcast import _BROADCAST_MAX_TEXT_LEN, broadcast_text

        msg = _make_message(user_id=42, text="x" * (_BROADCAST_MAX_TEXT_LEN + 1))
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_text(msg, state)

        msg.reply.assert_awaited_once()
        assert "довгий" in msg.reply.call_args[0][0].lower()

    async def test_valid_text_shows_preview(self):
        from bot.handlers.admin.broadcast import broadcast_text

        msg = _make_message(user_id=42, text="Тестове повідомлення")
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_text(msg, state)

        state.update_data.assert_awaited_once_with(broadcast_text="Тестове повідомлення")
        state.set_state.assert_awaited_once()
        msg.answer.assert_awaited_once()
        answer_text: str = msg.answer.call_args[0][0]
        assert "Попередній перегляд" in answer_text
        assert "Тестове повідомлення" in answer_text


# ---------------------------------------------------------------------------
# broadcast_edit_text
# ---------------------------------------------------------------------------


class TestBroadcastEditText:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_not_admin_denied(self):
        from bot.handlers.admin.broadcast import broadcast_edit_text

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_edit_text(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")
        state.set_state.assert_not_awaited()

    async def test_normal_returns_to_waiting(self):
        from bot.handlers.admin.broadcast import broadcast_edit_text

        cb = _make_callback(user_id=42)
        state = _make_state()
        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch("bot.handlers.admin.broadcast.get_broadcast_cancel_keyboard", return_value=MagicMock()),
        ):
            mock_settings.is_admin.return_value = True
            await broadcast_edit_text(cb, state)

        cb.answer.assert_awaited_once_with()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# broadcast_confirm_send
# ---------------------------------------------------------------------------


class TestBroadcastConfirmSend:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_not_admin_denied(self):
        from bot.handlers.admin.broadcast import broadcast_confirm_send

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_confirm_send(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_already_running(self):
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import broadcast_confirm_send

        running_task = MagicMock()
        running_task.done.return_value = False
        bcast._active_broadcast = running_task

        cb = _make_callback(user_id=42)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_confirm_send(cb, state)

        cb.answer.assert_awaited_once_with("⚠️ Розсилка вже виконується", show_alert=True)

    async def test_normal_creates_task(self):
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import broadcast_confirm_send

        cb = _make_callback(user_id=42)
        state = _make_state()

        created_task = MagicMock()
        created_task.done.return_value = False
        calls: list = []

        def _fake_create_task(coro, **kw):
            coro.close()  # prevent "coroutine never awaited" RuntimeWarning
            calls.append(coro)
            return created_task

        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch("bot.handlers.admin.broadcast.asyncio.create_task", side_effect=_fake_create_task),
        ):
            mock_settings.is_admin.return_value = True
            await broadcast_confirm_send(cb, state)

        assert len(calls) == 1
        assert bcast._active_broadcast is created_task
        cb.message.edit_text.assert_awaited_once()
        assert "розпочата" in cb.message.edit_text.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# broadcast_cancel_active
# ---------------------------------------------------------------------------


class TestBroadcastCancelActive:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_not_admin_denied(self):
        from bot.handlers.admin.broadcast import broadcast_cancel_active

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_cancel_active(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_not_running_info(self):
        from bot.handlers.admin.broadcast import broadcast_cancel_active

        cb = _make_callback(user_id=42)
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_cancel_active(cb)

        cb.answer.assert_awaited_once_with("ℹ️ Розсилка не активна")

    async def test_running_sets_cancel(self):
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import broadcast_cancel_active

        running_task = MagicMock()
        running_task.done.return_value = False
        bcast._active_broadcast = running_task

        cb = _make_callback(user_id=42)
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_cancel_active(cb)

        assert bcast._broadcast_cancel.is_set()
        cb.answer.assert_awaited_once_with("⏹ Зупиняємо розсилку...")


# ---------------------------------------------------------------------------
# broadcast_cancel
# ---------------------------------------------------------------------------


class TestBroadcastCancel:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_not_admin_denied(self):
        from bot.handlers.admin.broadcast import broadcast_cancel

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_cancel(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")
        state.clear.assert_not_awaited()

    async def test_normal_clears_and_edits(self):
        from bot.handlers.admin.broadcast import broadcast_cancel

        cb = _make_callback(user_id=42)
        state = _make_state()
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            await broadcast_cancel(cb, state)

        cb.answer.assert_awaited_once_with()
        state.clear.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        assert "скасовано" in cb.message.edit_text.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# _run_broadcast
# ---------------------------------------------------------------------------


def _mock_session_ctx(rows: list[tuple]) -> MagicMock:
    """Return a context manager mock that yields a session returning *rows*."""
    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


class TestRunBroadcast:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_all_sent_success(self):
        """Happy path: all messages sent, summary delivered to admin."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        rows = [(1, "101"), (2, "102")]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        # 2 users → 2 send_message calls + 1 summary
        assert bot.send_message.await_count == 3
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Надіслано: 2" in summary_text
        assert "Помилок: 0" in summary_text

    async def test_forbidden_error_deactivates_user(self):
        """TelegramForbiddenError → deactivate_user called, blocked counted."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        bot.send_message.side_effect = [
            TelegramForbiddenError(method=MagicMock(), message="Forbidden"),
            None,  # summary
        ]
        rows = [(1, "101")]

        session_ctx = MagicMock()
        session_mock = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session_mock)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.deactivate_user", AsyncMock()) as mock_deactivate,
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        mock_deactivate.assert_awaited_once()
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Заблокували" in summary_text

    async def test_retry_after_then_success(self):
        """TelegramRetryAfter on first attempt → sleep → success on retry."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        retry_exc = TelegramRetryAfter(method=MagicMock(), message="RetryAfter", retry_after=1)
        # First call → RetryAfter, second → success, then summary
        bot.send_message.side_effect = [retry_exc, None, None]
        rows = [(1, "101")]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        sleep_mock = AsyncMock()
        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", sleep_mock),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        # sleep called with retry_after+1 (=2) for the RetryAfter, then _SEND_DELAY_S
        retry_sleep_calls = [c for c in sleep_mock.call_args_list if c[0][0] == 2]
        assert len(retry_sleep_calls) == 1
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Надіслано: 1" in summary_text

    async def test_retry_after_exceeds_max_retries_counts_failed(self):
        """RetryAfter every attempt → failed after max_retries exhausted."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        retry_exc = TelegramRetryAfter(method=MagicMock(), message="RetryAfter", retry_after=1)
        # 4 RetryAfter (max_retries=3 means 4 attempts: 0,1,2,3) then summary
        bot.send_message.side_effect = [retry_exc, retry_exc, retry_exc, retry_exc, None]
        rows = [(1, "101")]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Помилок: 1" in summary_text

    async def test_generic_exception_counts_failed(self):
        """Unexpected exception → failed incremented, broadcast continues."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        bot.send_message.side_effect = [RuntimeError("network"), None]
        rows = [(1, "101")]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Помилок: 1" in summary_text

    async def test_cancel_mid_batch_stops_early(self):
        """Setting _broadcast_cancel mid-batch stops sending."""
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        rows = [(1, "101"), (2, "102"), (3, "103")]
        bcast._broadcast_cancel.set()  # cancelled before start

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(return_value=rows),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        # No messages sent (cancelled before first row)
        user_calls = [c for c in bot.send_message.call_args_list if c[0][0] != 99]
        assert len(user_calls) == 0
        # But summary should still be sent
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "зупинено" in summary_text.lower()

    async def test_progress_reported_every_1000(self):
        """Progress message sent to admin every _PROGRESS_EVERY messages."""
        from bot.handlers.admin.broadcast import _PROGRESS_EVERY, _run_broadcast

        bot = AsyncMock()
        # 1000 users → progress at 1000, then summary
        rows = [(i, str(1000 + i)) for i in range(1, _PROGRESS_EVERY + 1)]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        # calls to admin_id=99: progress + summary = 2
        admin_calls = [c for c in bot.send_message.call_args_list if c[0][0] == 99]
        assert len(admin_calls) == 2
        progress_text: str = admin_calls[0][0][1]
        assert "Прогрес" in progress_text
