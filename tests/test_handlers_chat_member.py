"""Tests for bot/handlers/chat_member.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _make_event(new_status: str = "administrator", old_status: str = "left"):
    event = MagicMock()
    event.chat.type = "channel"
    event.chat.id = -1001234567890
    event.chat.title = "Test Channel"
    event.chat.username = "testchannel"
    event.new_chat_member.status = new_status
    event.old_chat_member.status = old_status
    event.from_user.id = 111
    event.from_user.username = "testuser"
    event.bot = AsyncMock()
    event.bot.send_message = AsyncMock()
    event.bot.edit_message_text = AsyncMock()
    return event


def _make_session(existing_owner=None, user=None, tracking=None):
    session = AsyncMock()

    # get_user_by_channel_id
    existing_owner_result = MagicMock()
    existing_owner_result.scalar_one_or_none.return_value = existing_owner

    # get_user_by_telegram_id
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user

    # UserMessageTracking query
    tracking_result = MagicMock()
    tracking_result.scalar_one_or_none.return_value = tracking

    session.execute = AsyncMock(side_effect=[
        existing_owner_result,
        user_result,
        tracking_result,
    ])
    return session


class TestHandleChatMemberBotAdded:
    async def test_send_message_exception_is_logged(self):
        """Lines 83-84: send_message raises when no instruction_msg_id → warning logged."""
        from bot.handlers.chat_member import handle_chat_member

        event = _make_event(new_status="administrator", old_status="left")
        event.bot.send_message.side_effect = Exception("Forbidden")

        session = AsyncMock()

        with (
            patch("bot.handlers.chat_member.get_user_by_channel_id", AsyncMock(return_value=None)),
            patch("bot.handlers.chat_member.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.chat_member.save_pending_channel", AsyncMock()),
        ):
            # Should complete without raising (exception is swallowed with warning)
            await handle_chat_member(event, session)

        # send_message was attempted and failed
        event.bot.send_message.assert_awaited()

    async def test_non_channel_event_is_ignored(self):
        """Events from non-channel chats are skipped immediately."""
        from bot.handlers.chat_member import handle_chat_member

        event = _make_event()
        event.chat.type = "group"
        session = AsyncMock()

        await handle_chat_member(event, session)

        event.bot.send_message.assert_not_awaited()

    async def test_bot_removed_notifies_user(self):
        """Bot removed from channel → user notified via send_message."""
        from bot.handlers.chat_member import handle_chat_member

        event = _make_event(new_status="left", old_status="administrator")

        mock_channel_config = MagicMock()
        mock_channel_config.channel_id = "-1001234567890"
        mock_channel_config.channel_title = "Test"
        mock_user = MagicMock()
        mock_user.telegram_id = "111"
        mock_user.channel_config = mock_channel_config

        session = AsyncMock()

        with (
            patch("bot.handlers.chat_member.delete_pending_channel", AsyncMock()),
            patch("bot.handlers.chat_member.get_user_by_channel_id", AsyncMock(return_value=mock_user)),
        ):
            await handle_chat_member(event, session)

        event.bot.send_message.assert_awaited_once()
