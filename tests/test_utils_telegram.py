"""Tests for bot/utils/telegram.py.

Coverage:
- safe_edit_text: not-Message, success, not-modified, error+no-emoji,
  error+emoji retry success, error+emoji retry not-modified, error+emoji retry fail,
  ForbiddenError
- safe_edit_reply_markup: not-Message, success, not-modified, error
- safe_delete: not-Message, success, TelegramBadRequest suppressed
- safe_edit_or_resend: not-Message, photo→delete+answer, no-photo edit ok,
  no-photo edit fails→answer, TelegramBadRequest→None
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bad_request(text: str = "bad request") -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=text)


def _forbidden() -> TelegramForbiddenError:
    return TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked")


def _make_message(**kwargs) -> MagicMock:
    """Return a MagicMock that isinstance-checks as Message."""
    msg = MagicMock(spec=Message)
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    msg.delete = AsyncMock()
    msg.answer = AsyncMock()
    msg.photo = None
    for k, v in kwargs.items():
        setattr(msg, k, v)
    return msg


# ---------------------------------------------------------------------------
# safe_edit_text
# ---------------------------------------------------------------------------


class TestSafeEditText:
    async def test_not_message_returns_false(self):
        from bot.utils.telegram import safe_edit_text

        result = await safe_edit_text(SimpleNamespace(), "text")
        assert result is False

    async def test_none_returns_false(self):
        from bot.utils.telegram import safe_edit_text

        result = await safe_edit_text(None, "text")
        assert result is False

    async def test_success_returns_true(self):
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        result = await safe_edit_text(msg, "hello")

        assert result is True
        msg.edit_text.assert_awaited_once_with("hello", reply_markup=None, parse_mode="HTML")

    async def test_not_modified_returns_true(self):
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        msg.edit_text.side_effect = _bad_request("message is not modified: specified new message content and reply markup are exactly the same")

        result = await safe_edit_text(msg, "hello")
        assert result is True

    async def test_other_error_no_emoji_returns_false(self):
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        msg.edit_text.side_effect = _bad_request("BUTTON_USER_PRIVACY_RESTRICTED")

        result = await safe_edit_text(msg, "plain text")
        assert result is False
        # Only one attempt (no emoji to strip)
        msg.edit_text.assert_awaited_once()

    async def test_other_error_with_emoji_retry_success(self):
        """First attempt fails (emoji unsupported), retry with stripped emoji succeeds."""
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        msg.edit_text.side_effect = [
            _bad_request("can't parse entities"),
            None,  # retry succeeds
        ]
        text_with_emoji = 'Hello <tg-emoji emoji-id="1">⚡</tg-emoji> world'

        result = await safe_edit_text(msg, text_with_emoji)
        assert result is True
        assert msg.edit_text.await_count == 2
        # Second call should have stripped tg-emoji tags
        second_call_text = msg.edit_text.call_args_list[1][0][0]
        assert "<tg-emoji" not in second_call_text
        assert "⚡" in second_call_text

    async def test_other_error_with_emoji_retry_not_modified(self):
        """Retry raises not-modified → still returns True."""
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        msg.edit_text.side_effect = [
            _bad_request("can't parse entities"),
            _bad_request("message is not modified"),
        ]
        text_with_emoji = '<tg-emoji emoji-id="1">⚡</tg-emoji>'

        result = await safe_edit_text(msg, text_with_emoji)
        assert result is True

    async def test_other_error_with_emoji_retry_fails(self):
        """Both attempts fail → returns False."""
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        msg.edit_text.side_effect = [
            _bad_request("can't parse entities"),
            _bad_request("some other error"),
        ]
        text_with_emoji = '<tg-emoji emoji-id="1">⚡</tg-emoji>'

        result = await safe_edit_text(msg, text_with_emoji)
        assert result is False

    async def test_forbidden_error_returns_false(self):
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        msg.edit_text.side_effect = _forbidden()

        result = await safe_edit_text(msg, "hello")
        assert result is False

    async def test_passes_kwargs_to_edit_text(self):
        from bot.utils.telegram import safe_edit_text

        msg = _make_message()
        kb = MagicMock()
        result = await safe_edit_text(msg, "hi", reply_markup=kb, parse_mode="MarkdownV2")

        assert result is True
        msg.edit_text.assert_awaited_once_with("hi", reply_markup=kb, parse_mode="MarkdownV2")


# ---------------------------------------------------------------------------
# safe_edit_reply_markup
# ---------------------------------------------------------------------------


class TestSafeEditReplyMarkup:
    async def test_not_message_returns_false(self):
        from bot.utils.telegram import safe_edit_reply_markup

        result = await safe_edit_reply_markup(SimpleNamespace())
        assert result is False

    async def test_success_returns_true(self):
        from bot.utils.telegram import safe_edit_reply_markup

        msg = _make_message()
        kb = MagicMock()
        result = await safe_edit_reply_markup(msg, reply_markup=kb)

        assert result is True
        msg.edit_reply_markup.assert_awaited_once_with(reply_markup=kb)

    async def test_not_modified_returns_true(self):
        from bot.utils.telegram import safe_edit_reply_markup

        msg = _make_message()
        msg.edit_reply_markup.side_effect = _bad_request("message is not modified")

        result = await safe_edit_reply_markup(msg)
        assert result is True

    async def test_other_error_returns_false(self):
        from bot.utils.telegram import safe_edit_reply_markup

        msg = _make_message()
        msg.edit_reply_markup.side_effect = _bad_request("MESSAGE_ID_INVALID")

        result = await safe_edit_reply_markup(msg)
        assert result is False

    async def test_forbidden_returns_false(self):
        from bot.utils.telegram import safe_edit_reply_markup

        msg = _make_message()
        msg.edit_reply_markup.side_effect = _forbidden()

        result = await safe_edit_reply_markup(msg)
        assert result is False


# ---------------------------------------------------------------------------
# safe_delete
# ---------------------------------------------------------------------------


class TestSafeDelete:
    async def test_not_message_is_noop(self):
        from bot.utils.telegram import safe_delete

        # Should not raise
        await safe_delete(None)
        await safe_delete(SimpleNamespace())

    async def test_success_deletes(self):
        from bot.utils.telegram import safe_delete

        msg = _make_message()
        await safe_delete(msg)

        msg.delete.assert_awaited_once()

    async def test_bad_request_suppressed(self):
        from bot.utils.telegram import safe_delete

        msg = _make_message()
        msg.delete.side_effect = _bad_request("message to delete not found")

        # Should not raise
        await safe_delete(msg)

    async def test_forbidden_suppressed(self):
        from bot.utils.telegram import safe_delete

        msg = _make_message()
        msg.delete.side_effect = _forbidden()

        await safe_delete(msg)


# ---------------------------------------------------------------------------
# safe_edit_or_resend
# ---------------------------------------------------------------------------


class TestSafeEditOrResend:
    async def test_not_message_returns_none(self):
        from bot.utils.telegram import safe_edit_or_resend

        result = await safe_edit_or_resend(None, "text")
        assert result is None

    async def test_photo_message_deletes_and_resends(self):
        from bot.utils.telegram import safe_edit_or_resend

        new_msg = MagicMock(spec=Message)
        msg = _make_message(photo=[MagicMock()])
        msg.answer.return_value = new_msg

        with patch("bot.utils.telegram.safe_delete", AsyncMock()) as mock_delete:
            result = await safe_edit_or_resend(msg, "new text")

        mock_delete.assert_awaited_once_with(msg)
        msg.answer.assert_awaited_once_with("new text", reply_markup=None, parse_mode="HTML")
        assert result is new_msg

    async def test_no_photo_edit_success_returns_message(self):
        from bot.utils.telegram import safe_edit_or_resend

        msg = _make_message(photo=None)

        with patch("bot.utils.telegram.safe_edit_text", AsyncMock(return_value=True)):
            result = await safe_edit_or_resend(msg, "text")

        assert result is msg
        msg.answer.assert_not_awaited()

    async def test_no_photo_edit_fails_resends(self):
        from bot.utils.telegram import safe_edit_or_resend

        new_msg = MagicMock(spec=Message)
        msg = _make_message(photo=None)
        msg.answer.return_value = new_msg

        with patch("bot.utils.telegram.safe_edit_text", AsyncMock(return_value=False)):
            result = await safe_edit_or_resend(msg, "text")

        msg.answer.assert_awaited_once()
        assert result is new_msg

    async def test_telegram_error_returns_none(self):
        from bot.utils.telegram import safe_edit_or_resend

        msg = _make_message(photo=None)

        with patch("bot.utils.telegram.safe_edit_text", AsyncMock(side_effect=_bad_request("gone"))):
            result = await safe_edit_or_resend(msg, "text")

        assert result is None
