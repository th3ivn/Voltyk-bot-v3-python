"""Tests for bot/handlers/admin/broadcast.py.

Covered scenarios:
- admin_broadcast: not admin, already running, normal → enter waiting_for_text
- broadcast_text: not admin, no text, text too long, valid → preview
- broadcast_edit_text: not admin, normal → back to waiting_for_text
- broadcast_confirm_send: not admin, already running, normal → create_task
- broadcast_cancel_active: not admin, not running, running → set cancel flag
- broadcast_cancel: not admin, normal → clear + edit_text
- _run_broadcast: all sent, ForbiddenError (deactivate), RetryAfter + retry,
  RetryAfter exceeds retries, generic exception, cancellation handling,
  progress reporting, summary
- is_broadcast_running: task=None, task done, task running
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Message

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
    cb.message = MagicMock(spec=Message)
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
        """Cancellation mid-batch: first message sent, then cancel stops further sends."""
        import bot.handlers.admin.broadcast as bcast
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        rows = [(1, "101"), (2, "102"), (3, "103")]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        send_count = 0

        async def _send_and_cancel(user_id, text, **kw):
            nonlocal send_count
            send_count += 1
            if send_count == 1:
                # Cancel after the very first successful send
                bcast._broadcast_cancel.set()

        bot.send_message.side_effect = _send_and_cancel

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

        # Only 1 user message sent (cancelled after first), then summary to admin
        user_calls = [c for c in bot.send_message.call_args_list if c[0][0] != 99]
        assert len(user_calls) == 1
        # Summary must indicate cancellation
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "зупинено" in summary_text.lower()

    async def test_progress_reported_every_n(self):
        """Progress message sent to admin at every _PROGRESS_EVERY boundary.

        Uses a patched threshold of 3 to keep the test fast while still
        verifying the exact cadence of progress reporting.
        """
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        progress_every = 3
        rows = [(i, str(1000 + i)) for i in range(1, progress_every + 1)]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast._PROGRESS_EVERY", progress_every),
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

        # calls to admin_id=99: 1 progress (at row 3) + 1 summary = 2
        admin_calls = [c for c in bot.send_message.call_args_list if c[0][0] == 99]
        assert len(admin_calls) == 2
        progress_text: str = admin_calls[0][0][1]
        assert "Прогрес" in progress_text

    async def test_deactivate_user_exception_is_swallowed(self):
        """Lines 187-188: if deactivate_user itself raises, warning is logged and broadcast continues."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        bot.send_message.side_effect = [
            TelegramForbiddenError(method=MagicMock(), message="Forbidden"),
            None,  # summary
        ]
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
            patch(
                "bot.handlers.admin.broadcast.deactivate_user",
                AsyncMock(side_effect=RuntimeError("db down")),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            # Should not raise — exception swallowed
            await _run_broadcast(bot, "msg", 99)

        # Summary still sent despite the deactivation failure
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Заблокували" in summary_text

    async def test_progress_send_exception_is_swallowed(self):
        """Lines 211-212: if progress send_message fails, exception is logged and broadcast continues."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        progress_every = 2
        rows = [(1, "101"), (2, "102")]

        send_calls = 0

        async def _send(chat_id, text, **kw):
            nonlocal send_calls
            send_calls += 1
            if chat_id == 99 and "Прогрес" in text:
                raise RuntimeError("send failed")

        bot.send_message.side_effect = _send

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast._PROGRESS_EVERY", progress_every),
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=[rows, []]),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            # Should not raise — swallowed by except block
            await _run_broadcast(bot, "msg", 99)

        # Summary still sent after the failed progress message
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Надіслано: 2" in summary_text

    async def test_cancelled_error_stops_broadcast_gracefully(self):
        """Lines 216-217: asyncio.CancelledError from cursor raises → broadcast logs and ends."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=asyncio.CancelledError()),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        # Summary still sent to admin; no user messages sent
        assert bot.send_message.await_count >= 1
        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Надіслано: 0" in summary_text

    async def test_outer_exception_increments_failed_and_sends_summary(self):
        """Lines 218-220: unexpected outer exception → failed+1, summary sent."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_active_user_ids_cursor",
                AsyncMock(side_effect=RuntimeError("outer boom")),
            ),
            patch("bot.handlers.admin.broadcast.asyncio.sleep", AsyncMock()),
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
        ):
            mock_settings.TELEGRAM_MAX_RETRIES = 3
            await _run_broadcast(bot, "msg", 99)

        summary_text: str = bot.send_message.call_args_list[-1][0][1]
        assert "Помилок: 1" in summary_text

    async def test_summary_send_exception_is_swallowed(self):
        """Lines 230-231: if final summary send fails, exception is logged and no re-raise."""
        from bot.handlers.admin.broadcast import _run_broadcast

        bot = AsyncMock()
        rows = [(1, "101")]

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        # All sends succeed except the final summary
        user_send_done = False

        async def _send(chat_id, text, **kw):
            nonlocal user_send_done
            if chat_id != 99:
                user_send_done = True
                return
            # Summary send always raises
            raise RuntimeError("telegram down")

        bot.send_message.side_effect = _send

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
            # Must not raise even though summary send fails
            await _run_broadcast(bot, "msg", 99)

        assert user_send_done


# ─── Checkpoint + resume ─────────────────────────────────────────────────


class TestBroadcastCheckpoint:
    """Interrupted-broadcast resume path."""

    def setup_method(self):
        _reset_broadcast_state()

    async def test_save_checkpoint_writes_json(self):
        from bot.handlers.admin.broadcast import (
            BROADCAST_STATE_KEY,
            _save_checkpoint,
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch("bot.handlers.admin.broadcast.set_setting", new=AsyncMock()) as ss,
        ):
            await _save_checkpoint("hi", 99, 42, 100, 5, 3)

        ss.assert_awaited_once()
        _, key, payload = ss.await_args.args
        assert key == BROADCAST_STATE_KEY
        import json

        data = json.loads(payload)
        assert data["text"] == "hi"
        assert data["admin_id"] == 99
        assert data["last_id"] == 42
        assert data["sent"] == 100
        assert data["failed"] == 5
        assert data["blocked"] == 3
        assert "started_at" in data

    async def test_save_checkpoint_swallows_db_error(self):
        """A broken DB must not crash the broadcast — at worst we lose the
        resume capability, which is strictly no worse than the pre-feature
        behaviour."""
        from bot.handlers.admin.broadcast import _save_checkpoint

        def _boom():
            raise Exception("db down")

        with patch("bot.handlers.admin.broadcast.async_session", side_effect=_boom):
            # Must not raise
            await _save_checkpoint("hi", 99, 0, 0, 0, 0)

    async def test_clear_checkpoint_calls_delete_setting(self):
        from bot.handlers.admin.broadcast import _clear_checkpoint

        session = AsyncMock()
        session.commit = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch("bot.handlers.admin.broadcast.delete_setting", new=AsyncMock()) as ds,
        ):
            await _clear_checkpoint()

        ds.assert_awaited_once()

    async def test_clear_checkpoint_swallows_db_error(self):
        from bot.handlers.admin.broadcast import _clear_checkpoint

        def _boom():
            raise Exception("db down")

        with patch("bot.handlers.admin.broadcast.async_session", side_effect=_boom):
            await _clear_checkpoint()

    async def test_load_interrupted_broadcast_returns_parsed(self):
        import json

        from bot.handlers.admin.broadcast import load_interrupted_broadcast

        payload = json.dumps(
            {
                "text": "hi",
                "admin_id": 99,
                "last_id": 42,
                "sent": 100,
                "failed": 0,
                "blocked": 0,
                "started_at": "2026-04-24T00:00:00+00:00",
            }
        )

        session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch("bot.handlers.admin.broadcast.get_setting", new=AsyncMock(return_value=payload)),
        ):
            result = await load_interrupted_broadcast()

        assert result is not None
        assert result["last_id"] == 42

    async def test_load_interrupted_broadcast_returns_none_when_absent(self):
        from bot.handlers.admin.broadcast import load_interrupted_broadcast

        session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch("bot.handlers.admin.broadcast.get_setting", new=AsyncMock(return_value=None)),
        ):
            result = await load_interrupted_broadcast()

        assert result is None

    async def test_load_interrupted_broadcast_handles_malformed_json(self):
        """Corrupt payload → log and clear, return None (don't trap operator
        on a zombie 'resume' prompt forever)."""
        from bot.handlers.admin.broadcast import load_interrupted_broadcast

        session = AsyncMock()
        session.commit = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.async_session", return_value=session_ctx),
            patch(
                "bot.handlers.admin.broadcast.get_setting",
                new=AsyncMock(return_value="not json"),
            ),
            patch("bot.handlers.admin.broadcast.delete_setting", new=AsyncMock()) as ds,
        ):
            result = await load_interrupted_broadcast()

        assert result is None
        ds.assert_awaited_once()

    async def test_load_interrupted_broadcast_swallows_db_error(self):
        from bot.handlers.admin.broadcast import load_interrupted_broadcast

        def _boom():
            raise Exception("db down")

        with patch("bot.handlers.admin.broadcast.async_session", side_effect=_boom):
            result = await load_interrupted_broadcast()

        assert result is None


class TestBroadcastResumeHandler:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_non_admin_denied(self):
        from bot.handlers.admin.broadcast import broadcast_resume

        cb = _make_callback(user_id=1)
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_resume(cb)

        cb.answer.assert_called_once_with("❌ Доступ заборонено")

    async def test_no_snapshot_informs_admin(self):
        from bot.handlers.admin.broadcast import broadcast_resume

        cb = _make_callback(user_id=42)
        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch(
                "bot.handlers.admin.broadcast.load_interrupted_broadcast",
                AsyncMock(return_value=None),
            ),
            patch("bot.handlers.admin.broadcast.safe_edit_text", AsyncMock()),
        ):
            mock_settings.is_admin.return_value = True
            await broadcast_resume(cb)

        cb.answer.assert_called_with("ℹ️ Немає перерваної розсилки", show_alert=True)

    async def test_resume_starts_background_task(self):
        import bot.handlers.admin.broadcast as bcast

        cb = _make_callback(user_id=42)
        cb.bot = AsyncMock()

        snapshot = {
            "text": "hi",
            "admin_id": 99,
            "last_id": 500,
            "sent": 500,
            "failed": 0,
            "blocked": 0,
        }

        created_task = MagicMock()
        created_task.done = MagicMock(return_value=False)

        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch(
                "bot.handlers.admin.broadcast.load_interrupted_broadcast",
                AsyncMock(return_value=snapshot),
            ),
            patch("bot.handlers.admin.broadcast.safe_edit_text", AsyncMock()),
            patch(
                "bot.handlers.admin.broadcast.asyncio.create_task",
                return_value=created_task,
            ) as mock_ct,
        ):
            mock_settings.is_admin.return_value = True
            await bcast.broadcast_resume(cb)

        mock_ct.assert_called_once()

    async def test_resume_refused_when_broadcast_already_running(self):
        import bot.handlers.admin.broadcast as bcast

        # Simulate running broadcast
        running = MagicMock()
        running.done = MagicMock(return_value=False)
        bcast._active_broadcast = running

        cb = _make_callback(user_id=42)
        snapshot = {"text": "hi", "admin_id": 99, "last_id": 1}

        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch(
                "bot.handlers.admin.broadcast.load_interrupted_broadcast",
                AsyncMock(return_value=snapshot),
            ),
        ):
            mock_settings.is_admin.return_value = True
            await bcast.broadcast_resume(cb)

        cb.answer.assert_called_with("⚠️ Розсилка вже виконується", show_alert=True)
        bcast._active_broadcast = None


class TestBroadcastAbortInterrupted:
    def setup_method(self):
        _reset_broadcast_state()

    async def test_non_admin_denied(self):
        from bot.handlers.admin.broadcast import broadcast_abort_interrupted

        cb = _make_callback(user_id=1)
        with patch("bot.handlers.admin.broadcast.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            await broadcast_abort_interrupted(cb)

        cb.answer.assert_called_once_with("❌ Доступ заборонено")

    async def test_clears_checkpoint(self):
        from bot.handlers.admin.broadcast import broadcast_abort_interrupted

        cb = _make_callback(user_id=42)
        with (
            patch("bot.handlers.admin.broadcast.settings") as mock_settings,
            patch("bot.handlers.admin.broadcast._clear_checkpoint", AsyncMock()) as cc,
            patch("bot.handlers.admin.broadcast.safe_edit_text", AsyncMock()),
        ):
            mock_settings.is_admin.return_value = True
            await broadcast_abort_interrupted(cb)

        cc.assert_awaited_once()
