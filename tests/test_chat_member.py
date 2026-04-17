"""Unit tests for bot/handlers/chat_member.py — handle_chat_member."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    chat_type="channel",
    chat_id=-1001234567890,
    chat_title="Test Channel",
    chat_username="test_channel",
    from_user_id=123,
    new_status="administrator",
    old_status="left",
):
    event = AsyncMock()
    event.chat = SimpleNamespace(type=chat_type, id=chat_id, title=chat_title, username=chat_username)
    event.new_chat_member = SimpleNamespace(status=new_status)
    event.old_chat_member = SimpleNamespace(status=old_status)
    event.from_user = SimpleNamespace(id=from_user_id)
    event.bot = AsyncMock()
    return event


def _make_mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


def _make_tracking(last_settings_message_id=None):
    tracking = MagicMock()
    tracking.last_settings_message_id = last_settings_message_id
    return tracking


def _make_user(telegram_id="123", channel_config=None):
    user = SimpleNamespace(
        id=1,
        telegram_id=telegram_id,
        channel_config=channel_config,
    )
    return user


def _make_channel_config(channel_id="-999", channel_title="Old Channel"):
    return SimpleNamespace(
        channel_id=channel_id,
        channel_title=channel_title,
        channel_status="active",
    )


def _session_execute_returns(session, tracking_obj):
    """Configure session.execute to return a result whose scalar_one_or_none() yields tracking_obj."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = tracking_obj
    session.execute.return_value = result_mock


# ===========================================================================
# 1. Early return — non-channel chat types
# ===========================================================================


class TestEarlyReturn:
    """Non-channel events are ignored immediately."""

    @pytest.fixture(autouse=True)
    def _patches(self):
        with (
            patch("bot.handlers.chat_member.get_user_by_channel_id", new_callable=AsyncMock) as p_owner,
            patch("bot.handlers.chat_member.get_user_by_telegram_id", new_callable=AsyncMock) as p_user,
            patch("bot.handlers.chat_member.save_pending_channel", new_callable=AsyncMock) as p_save,
            patch("bot.handlers.chat_member.delete_pending_channel", new_callable=AsyncMock) as p_del,
        ):
            self.p_owner = p_owner
            self.p_user = p_user
            self.p_save = p_save
            self.p_del = p_del
            yield

    async def _call(self, chat_type):
        from bot.handlers.chat_member import handle_chat_member

        event = _make_event(chat_type=chat_type)
        session = _make_mock_session()
        await handle_chat_member(event, session)
        self.p_owner.assert_not_called()
        self.p_user.assert_not_called()
        self.p_save.assert_not_called()
        self.p_del.assert_not_called()
        event.bot.send_message.assert_not_called()

    async def test_group_chat_ignored(self):
        await self._call("group")

    async def test_supergroup_chat_ignored(self):
        await self._call("supergroup")

    async def test_private_chat_ignored(self):
        await self._call("private")


# ===========================================================================
# 2. Bot promoted to admin
# ===========================================================================


class TestBotPromotedToAdmin:
    """new_status in (administrator, creator), old_status in (left, kicked, member)."""

    @pytest.fixture(autouse=True)
    def _patches(self):
        with (
            patch("bot.handlers.chat_member.get_user_by_channel_id", new_callable=AsyncMock) as p_owner,
            patch("bot.handlers.chat_member.get_user_by_telegram_id", new_callable=AsyncMock) as p_user,
            patch("bot.handlers.chat_member.save_pending_channel", new_callable=AsyncMock) as p_save,
            patch("bot.handlers.chat_member.delete_pending_channel", new_callable=AsyncMock) as p_del,
            patch("bot.handlers.chat_member.get_channel_connect_confirm_keyboard") as p_connect_kb,
            patch("bot.handlers.chat_member.get_channel_replace_confirm_keyboard") as p_replace_kb,
            patch("bot.handlers.chat_member.get_understood_keyboard") as p_understood_kb,
        ):
            self.p_owner = p_owner
            self.p_user = p_user
            self.p_save = p_save
            self.p_del = p_del
            self.p_connect_kb = p_connect_kb
            self.p_replace_kb = p_replace_kb
            self.p_understood_kb = p_understood_kb
            yield

    # --- 2a. Channel already owned by another user ---

    async def test_channel_owned_by_other_user_sends_warning_and_returns(self):
        """Channel already connected to another user → warning sent, no save_pending_channel."""
        other_user = SimpleNamespace(telegram_id="999")
        self.p_owner.return_value = other_user

        event = _make_event(from_user_id=123)
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        event.bot.send_message.assert_awaited_once()
        call_args = event.bot.send_message.call_args
        assert call_args[0][0] == 123  # sent to from_user
        assert "вже підключений" in call_args[0][1]

        self.p_save.assert_not_called()
        self.p_user.assert_not_called()

    async def test_channel_owned_by_same_user_does_not_return_early(self):
        """Channel connected to same telegram_id (not a different user) → continues."""
        same_user = SimpleNamespace(telegram_id="123")
        self.p_owner.return_value = same_user
        self.p_user.return_value = None

        event = _make_event(from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_save.assert_awaited_once()

    async def test_channel_owned_by_other_send_message_raises_no_crash(self):
        """send_message raises an exception → caught, still returns early."""
        other_user = SimpleNamespace(telegram_id="999")
        self.p_owner.return_value = other_user
        event = _make_event(from_user_id=123)
        event.bot.send_message.side_effect = Exception("network error")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)  # should not raise

        self.p_save.assert_not_called()

    # --- 2b. New channel, no existing owner ---

    async def test_new_channel_no_existing_user_sends_connect_confirmation(self):
        """No owner, no user → save_pending_channel + connect confirm keyboard + send_message."""
        self.p_owner.return_value = None
        self.p_user.return_value = None
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(chat_id=-1001234567890, chat_title="Test Channel", from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_save.assert_awaited_once_with(
            session,
            str(-1001234567890),
            123,
            channel_username="test_channel",
            channel_title="Test Channel",
        )
        self.p_connect_kb.assert_called_once_with(str(-1001234567890))
        event.bot.send_message.assert_awaited_once()

    async def test_save_pending_channel_called_with_correct_args(self):
        """Verify save_pending_channel receives all expected arguments."""
        self.p_owner.return_value = None
        self.p_user.return_value = None
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(
            chat_id=-9999,
            chat_title="My Channel",
            chat_username="mychannel",
            from_user_id=42,
        )
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_save.assert_awaited_once_with(
            session,
            "-9999",
            42,
            channel_username="mychannel",
            channel_title="My Channel",
        )

    # --- 2c. Existing user WITHOUT channel_config ---

    async def test_user_without_channel_config_sends_connect_confirmation(self):
        """User exists but has no channel_config → connect confirmation."""
        self.p_owner.return_value = None
        user = _make_user(telegram_id="123", channel_config=None)
        self.p_user.return_value = user
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_connect_kb.assert_called_once()
        self.p_replace_kb.assert_not_called()

    async def test_user_with_channel_config_but_no_channel_id_sends_connect(self):
        """User has channel_config but channel_id is None → connect confirmation."""
        self.p_owner.return_value = None
        cc = SimpleNamespace(channel_id=None, channel_title=None)
        user = _make_user(telegram_id="123", channel_config=cc)
        self.p_user.return_value = user
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_connect_kb.assert_called_once()
        self.p_replace_kb.assert_not_called()

    # --- 2d. Existing user WITH channel_config.channel_id ---

    async def test_user_with_existing_channel_sends_replace_confirmation(self):
        """User already has a channel → replace confirm keyboard."""
        self.p_owner.return_value = None
        cc = _make_channel_config(channel_id="-777", channel_title="Old Channel")
        user = _make_user(telegram_id="123", channel_config=cc)
        self.p_user.return_value = user
        self.p_replace_kb.return_value = MagicMock()

        event = _make_event(chat_id=-1001234567890, chat_title="New Channel", from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_replace_kb.assert_called_once_with(str(-1001234567890))
        self.p_connect_kb.assert_not_called()
        # Verify message text mentions both channels
        call_args = event.bot.send_message.call_args
        assert "New Channel" in call_args[0][1]
        assert "Old Channel" in call_args[0][1]

    async def test_replace_keyboard_called_with_new_channel_id(self):
        """get_channel_replace_confirm_keyboard receives the new channel_id."""
        self.p_owner.return_value = None
        cc = _make_channel_config(channel_id="-888")
        user = _make_user(telegram_id="55", channel_config=cc)
        self.p_user.return_value = user
        self.p_replace_kb.return_value = MagicMock()

        event = _make_event(chat_id=-5555, from_user_id=55)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_replace_kb.assert_called_once_with("-5555")

    # --- 2e. Instruction message editing ---

    async def test_edit_message_text_used_when_tracking_has_message_id(self):
        """Tracking has last_settings_message_id → edit_message_text called, send_message not called."""
        self.p_owner.return_value = None
        user = _make_user(telegram_id="123")
        self.p_user.return_value = user
        self.p_connect_kb.return_value = MagicMock()

        tracking = _make_tracking(last_settings_message_id=999)
        event = _make_event(from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, tracking)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        event.bot.edit_message_text.assert_awaited_once()
        event.bot.send_message.assert_not_called()
        assert tracking.last_settings_message_id is None  # cleared

    async def test_falls_back_to_send_message_when_edit_fails(self):
        """edit_message_text raises → falls back to send_message."""
        self.p_owner.return_value = None
        user = _make_user(telegram_id="123")
        self.p_user.return_value = user
        self.p_connect_kb.return_value = MagicMock()

        tracking = _make_tracking(last_settings_message_id=999)
        event = _make_event(from_user_id=123)
        event.bot.edit_message_text.side_effect = Exception("message not found")
        session = _make_mock_session()
        _session_execute_returns(session, tracking)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        event.bot.edit_message_text.assert_awaited_once()
        event.bot.send_message.assert_awaited_once()

    async def test_send_message_used_when_no_tracking(self):
        """No tracking record → send_message called directly (no edit attempt)."""
        self.p_owner.return_value = None
        user = _make_user(telegram_id="123")
        self.p_user.return_value = user
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        event.bot.edit_message_text.assert_not_called()
        event.bot.send_message.assert_awaited_once()

    async def test_send_message_used_when_tracking_has_no_message_id(self):
        """Tracking exists but last_settings_message_id is None → send_message directly."""
        self.p_owner.return_value = None
        user = _make_user(telegram_id="123")
        self.p_user.return_value = user
        self.p_connect_kb.return_value = MagicMock()

        tracking = _make_tracking(last_settings_message_id=None)
        event = _make_event(from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, tracking)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        event.bot.edit_message_text.assert_not_called()
        event.bot.send_message.assert_awaited_once()

    # --- 2f. Chat title fallback ---

    async def test_title_fallback_when_chat_title_is_none(self):
        """chat.title = None → uses 'Невідомий канал'."""
        self.p_owner.return_value = None
        self.p_user.return_value = None
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(chat_title=None, from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_save.assert_awaited_once()
        _, kwargs = self.p_save.call_args
        assert kwargs["channel_title"] == "Невідомий канал"

    async def test_title_used_when_chat_title_provided(self):
        """chat.title provided → uses that title."""
        self.p_owner.return_value = None
        self.p_user.return_value = None
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(chat_title="My Channel", from_user_id=123)
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        _, kwargs = self.p_save.call_args
        assert kwargs["channel_title"] == "My Channel"

    # --- Various old_status values ---

    async def test_old_status_kicked_triggers_promotion_branch(self):
        """old_status='kicked' also triggers the admin promotion branch."""
        self.p_owner.return_value = None
        self.p_user.return_value = None
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(new_status="administrator", old_status="kicked")
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_save.assert_awaited_once()

    async def test_old_status_member_triggers_promotion_branch(self):
        """old_status='member' also triggers the admin promotion branch."""
        self.p_owner.return_value = None
        self.p_user.return_value = None
        self.p_connect_kb.return_value = MagicMock()

        event = _make_event(new_status="creator", old_status="member")
        session = _make_mock_session()
        _session_execute_returns(session, None)

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_save.assert_awaited_once()


# ===========================================================================
# 3. Bot removed from channel
# ===========================================================================


class TestBotRemovedFromChannel:
    """new_status in (left, kicked), old_status in (administrator, creator)."""

    @pytest.fixture(autouse=True)
    def _patches(self):
        with (
            patch("bot.handlers.chat_member.get_user_by_channel_id", new_callable=AsyncMock) as p_owner,
            patch("bot.handlers.chat_member.get_user_by_telegram_id", new_callable=AsyncMock) as p_user,
            patch("bot.handlers.chat_member.save_pending_channel", new_callable=AsyncMock) as p_save,
            patch("bot.handlers.chat_member.delete_pending_channel", new_callable=AsyncMock) as p_del,
            patch("bot.handlers.chat_member.get_channel_connect_confirm_keyboard") as p_connect_kb,
            patch("bot.handlers.chat_member.get_channel_replace_confirm_keyboard") as p_replace_kb,
            patch("bot.handlers.chat_member.get_understood_keyboard") as p_understood_kb,
        ):
            self.p_owner = p_owner
            self.p_user = p_user
            self.p_save = p_save
            self.p_del = p_del
            self.p_connect_kb = p_connect_kb
            self.p_replace_kb = p_replace_kb
            self.p_understood_kb = p_understood_kb
            yield

    # --- 3a. Channel has connected user ---

    async def test_channel_with_connected_user_disconnects_and_notifies(self):
        """User with channel_config → config cleared, notification sent."""
        cc = _make_channel_config(channel_id="-1001234567890", channel_title="Test Channel")
        user = _make_user(telegram_id="123", channel_config=cc)
        self.p_owner.return_value = user
        self.p_understood_kb.return_value = MagicMock()

        event = _make_event(
            new_status="left", old_status="administrator",
            chat_id=-1001234567890, chat_title="Test Channel",
        )
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_del.assert_awaited_once_with(session, str(-1001234567890))
        assert cc.channel_id is None
        assert cc.channel_title is None
        assert cc.channel_status == "disconnected"

        event.bot.send_message.assert_awaited_once()
        self.p_understood_kb.assert_called_once()

    async def test_delete_pending_channel_called_on_removal(self):
        """delete_pending_channel is always called when bot is removed."""
        self.p_owner.return_value = None

        event = _make_event(new_status="kicked", old_status="creator", chat_id=-111)
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_del.assert_awaited_once_with(session, "-111")

    async def test_understood_keyboard_used_in_removal_notification(self):
        """get_understood_keyboard result used as reply_markup."""
        kb_mock = MagicMock()
        self.p_understood_kb.return_value = kb_mock
        cc = _make_channel_config()
        user = _make_user(telegram_id="55", channel_config=cc)
        self.p_owner.return_value = user

        event = _make_event(new_status="left", old_status="creator")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        call_args = event.bot.send_message.call_args
        assert call_args[1]["reply_markup"] is kb_mock

    async def test_channel_config_fields_nulled_on_removal(self):
        """channel_id and channel_title set to None, channel_status set to 'disconnected'."""
        cc = SimpleNamespace(channel_id="-777", channel_title="Gone Channel", channel_status="active")
        user = _make_user(telegram_id="10", channel_config=cc)
        self.p_owner.return_value = user
        self.p_understood_kb.return_value = MagicMock()

        event = _make_event(new_status="kicked", old_status="administrator")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        assert cc.channel_id is None
        assert cc.channel_title is None
        assert cc.channel_status == "disconnected"

    # --- 3b. Channel has no connected user ---

    async def test_no_connected_user_no_notification_sent(self):
        """No user found → delete_pending_channel only, no send_message."""
        self.p_owner.return_value = None

        event = _make_event(new_status="left", old_status="administrator")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_del.assert_awaited_once()
        event.bot.send_message.assert_not_called()

    async def test_user_without_channel_config_no_notification(self):
        """User found but channel_config is None → no notification."""
        user = _make_user(telegram_id="10", channel_config=None)
        self.p_owner.return_value = user

        event = _make_event(new_status="left", old_status="creator")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        event.bot.send_message.assert_not_called()

    # --- 3c. Send message fails on removal ---

    async def test_send_message_raises_on_removal_no_crash(self):
        """send_message raises → caught, no crash."""
        cc = _make_channel_config()
        user = _make_user(telegram_id="10", channel_config=cc)
        self.p_owner.return_value = user
        self.p_understood_kb.return_value = MagicMock()
        event = _make_event(new_status="left", old_status="administrator")
        event.bot.send_message.side_effect = Exception("Forbidden")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)  # must not raise

        # Config was still updated before send attempt
        assert cc.channel_status == "disconnected"

    # --- 3d. Chat title fallback on removal ---

    async def test_title_fallback_on_removal_when_chat_title_is_none(self):
        """chat.title = None → uses 'Невідомий канал' in notification."""
        cc = _make_channel_config()
        user = _make_user(telegram_id="10", channel_config=cc)
        self.p_owner.return_value = user
        self.p_understood_kb.return_value = MagicMock()

        event = _make_event(new_status="left", old_status="administrator", chat_title=None)
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        call_args = event.bot.send_message.call_args
        assert "Невідомий канал" in call_args[0][1]

    async def test_old_status_creator_triggers_removal_branch(self):
        """old_status='creator' also triggers the removal branch."""
        self.p_owner.return_value = None

        event = _make_event(new_status="left", old_status="creator")
        session = _make_mock_session()

        from bot.handlers.chat_member import handle_chat_member

        await handle_chat_member(event, session)

        self.p_del.assert_awaited_once()
        self.p_save.assert_not_called()


# ===========================================================================
# 4. Status combinations that don't match any branch
# ===========================================================================


class TestUnmatchedStatusCombinations:
    """Status transitions that don't match promotion or removal branches."""

    @pytest.fixture(autouse=True)
    def _patches(self):
        with (
            patch("bot.handlers.chat_member.get_user_by_channel_id", new_callable=AsyncMock) as p_owner,
            patch("bot.handlers.chat_member.get_user_by_telegram_id", new_callable=AsyncMock) as p_user,
            patch("bot.handlers.chat_member.save_pending_channel", new_callable=AsyncMock) as p_save,
            patch("bot.handlers.chat_member.delete_pending_channel", new_callable=AsyncMock) as p_del,
        ):
            self.p_owner = p_owner
            self.p_user = p_user
            self.p_save = p_save
            self.p_del = p_del
            yield

    async def _call_no_action(self, new_status, old_status):
        from bot.handlers.chat_member import handle_chat_member

        event = _make_event(new_status=new_status, old_status=old_status)
        session = _make_mock_session()
        await handle_chat_member(event, session)
        self.p_save.assert_not_called()
        self.p_del.assert_not_called()
        event.bot.send_message.assert_not_called()

    async def test_member_from_left_no_action(self):
        """new=member, old=left → no promotion, no removal."""
        await self._call_no_action("member", "left")

    async def test_admin_from_admin_no_action(self):
        """new=administrator, old=administrator → no action."""
        await self._call_no_action("administrator", "administrator")

    async def test_left_from_left_no_action(self):
        """new=left, old=left → no action."""
        await self._call_no_action("left", "left")

    async def test_kicked_from_left_no_action(self):
        """new=kicked, old=left → not an admin removal."""
        await self._call_no_action("kicked", "left")
