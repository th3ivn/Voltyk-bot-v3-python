"""Tests for bot/handlers/channel/*.py handler modules.

Covered:
- branding: channel_edit_title, channel_edit_description, channel_add_desc, channel_skip_desc
- connect: channel_connect, channel_confirm, connect_channel, replace_channel,
           keep_current, cancel_connect
- conversation: handle_title, handle_description, handle_edit_title,
                handle_edit_description, handle_schedule_caption, handle_period_format,
                handle_power_off_text, handle_power_on_text, handle_custom_test
- format: format_menu, format_schedule_settings, format_power_settings,
          format_toggle_delete, format_toggle_piconly, format_schedule_text,
          format_schedule_caption, format_schedule_periods, format_power_off,
          format_power_on, format_reset (all actions)
- notifications: channel_notifications (with/without user)
- pause: channel_pause, channel_pause_confirm, channel_resume, channel_resume_confirm
- settings: channel_info, channel_disable, channel_disable_confirm
- test: channel_test, test_schedule, test_power_on, test_power_off, test_custom
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel_config(**kwargs) -> SimpleNamespace:
    defaults = dict(
        channel_id=-100123456789,
        channel_title="Test Channel",
        channel_status="active",
        channel_user_title="Київ",
        channel_user_description="Опис",
        channel_paused=False,
        ch_notify_schedule=True,
        ch_notify_remind_off=True,
        ch_notify_remind_on=True,
        ch_notify_fact_off=True,
        ch_notify_fact_on=True,
        ch_remind_15m=True,
        ch_remind_30m=False,
        ch_remind_1h=False,
        delete_old_message=False,
        picture_only=False,
        schedule_caption=None,
        period_format=None,
        power_off_text=None,
        power_on_text=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_user(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=1,
        telegram_id=42,
        region="kyiv",
        queue="1.1",
        router_ip="192.168.1.1",
        channel_config=_make_channel_config(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_callback(user_id: int = 42, data: str = "") -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id)
    cb.data = data
    cb.bot = AsyncMock()
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.message_id = 100
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


def _make_message(user_id: int = 42, text: str | None = "hello") -> MagicMock:
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=user_id)
    msg.text = text
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()
    return msg


def _make_state() -> AsyncMock:
    state = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# branding.py
# ---------------------------------------------------------------------------


class TestChannelBranding:
    async def test_edit_title_no_user(self):
        from bot.handlers.channel.branding import channel_edit_title

        cb = _make_callback(data="channel_edit_title")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=None):
            await channel_edit_title(cb, state, session)
        cb.message.edit_text.assert_awaited_once_with("❌ Канал не підключено")

    async def test_edit_title_no_channel_config(self):
        from bot.handlers.channel.branding import channel_edit_title

        cb = _make_callback(data="channel_edit_title")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user):
            await channel_edit_title(cb, state, session)
        cb.message.edit_text.assert_awaited_once_with("❌ Канал не підключено")

    async def test_edit_title_no_channel_id(self):
        from bot.handlers.channel.branding import channel_edit_title

        cb = _make_callback(data="channel_edit_title")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_id=None))
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user):
            await channel_edit_title(cb, state, session)
        cb.message.edit_text.assert_awaited_once_with("❌ Канал не підключено")

    async def test_edit_title_sets_state(self):
        from bot.handlers.channel.branding import channel_edit_title

        cb = _make_callback(data="channel_edit_title")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user):
            await channel_edit_title(cb, state, session)
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_edit_description_no_user(self):
        from bot.handlers.channel.branding import channel_edit_description

        cb = _make_callback(data="channel_edit_description")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=None):
            await channel_edit_description(cb, state, session)
        cb.message.edit_text.assert_awaited_once_with("❌ Канал не підключено")

    async def test_edit_description_sets_state(self):
        from bot.handlers.channel.branding import channel_edit_description

        cb = _make_callback(data="channel_edit_description")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user):
            await channel_edit_description(cb, state, session)
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_edit_description_none_desc(self):
        from bot.handlers.channel.branding import channel_edit_description

        cb = _make_callback(data="channel_edit_description")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_user_description=None))
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user):
            await channel_edit_description(cb, state, session)
        state.set_state.assert_awaited_once()

    async def test_add_desc_sets_state(self):
        from bot.handlers.channel.branding import channel_add_desc

        cb = _make_callback(data="channel_add_desc")
        state = _make_state()
        await channel_add_desc(cb, state)
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_skip_desc_no_user(self):
        from bot.handlers.channel.branding import channel_skip_desc

        cb = _make_callback(data="channel_skip_desc")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=None):
            await channel_skip_desc(cb, state, session)
        state.clear.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()

    async def test_skip_desc_applies_branding(self):
        from bot.handlers.channel.branding import channel_skip_desc

        cb = _make_callback(data="channel_skip_desc")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.branding.apply_channel_branding") as mock_brand,
        ):
            mock_brand.return_value = AsyncMock()()
            await channel_skip_desc(cb, state, session)
        state.clear.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_skip_desc_no_channel_title(self):
        from bot.handlers.channel.branding import channel_skip_desc

        cb = _make_callback(data="channel_skip_desc")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_title=None))
        with (
            patch("bot.handlers.channel.branding.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.branding.apply_channel_branding") as mock_brand,
        ):
            mock_brand.return_value = AsyncMock()()
            await channel_skip_desc(cb, state, session)
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# connect.py
# ---------------------------------------------------------------------------


class TestChannelConnect:
    async def test_channel_connect_with_pending(self):
        from bot.handlers.channel.connect import channel_connect

        cb = _make_callback(data="channel_connect")
        session = AsyncMock()
        pending = SimpleNamespace(channel_title="My Channel", channel_id="-100111")
        with patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=pending):
            with patch("bot.handlers.channel.connect.get_channel_pending_confirm_keyboard", return_value=MagicMock()):
                await channel_connect(cb, session)
        cb.message.edit_text.assert_awaited_once()
        assert "My Channel" in cb.message.edit_text.call_args[0][0]

    async def test_channel_connect_no_pending_shows_instruction(self):
        from bot.handlers.channel.connect import channel_connect

        cb = _make_callback(data="channel_connect")
        session = AsyncMock()
        cb.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
        with (
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=None),
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=_make_user()),
        ):
            await channel_connect(cb, session)
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_connect_no_pending_no_user(self):
        from bot.handlers.channel.connect import channel_connect

        cb = _make_callback(data="channel_connect")
        session = AsyncMock()
        cb.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
        with (
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=None),
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=None),
        ):
            await channel_connect(cb, session)
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_connect_message_not_modified(self):
        from aiogram.exceptions import TelegramBadRequest

        from bot.handlers.channel.connect import channel_connect

        cb = _make_callback(data="channel_connect")
        session = AsyncMock()
        cb.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
        cb.message.edit_text = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="message is not modified")
        )
        with (
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=None),
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=_make_user()),
        ):
            await channel_connect(cb, session)  # should not raise

    async def test_channel_connect_reraises_other_bad_request(self):
        from aiogram.exceptions import TelegramBadRequest

        from bot.handlers.channel.connect import channel_connect

        cb = _make_callback(data="channel_connect")
        session = AsyncMock()
        cb.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
        cb.message.edit_text = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="some other error")
        )
        with (
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=None),
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=None),
        ):
            with pytest.raises(TelegramBadRequest):
                await channel_connect(cb, session)

    async def test_channel_confirm_no_user(self):
        from bot.handlers.channel.connect import channel_confirm

        cb = _make_callback(data="channel_confirm_-100111")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=None):
            await channel_confirm(cb, state, session)
        cb.message.edit_text.assert_not_awaited()

    async def test_channel_confirm_no_pending(self):
        from bot.handlers.channel.connect import channel_confirm

        cb = _make_callback(data="channel_confirm_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=None),
        ):
            await channel_confirm(cb, state, session)
        cb.message.edit_text.assert_awaited_once()
        assert "не знайдено" in cb.message.edit_text.call_args[0][0]

    async def test_channel_confirm_mismatched_channel_id(self):
        from bot.handlers.channel.connect import channel_confirm

        cb = _make_callback(data="channel_confirm_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        pending = SimpleNamespace(channel_id="-100999", channel_title="Other")
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=pending),
        ):
            await channel_confirm(cb, state, session)
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_confirm_success(self):
        from bot.handlers.channel.connect import channel_confirm

        cb = _make_callback(data="channel_confirm_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        pending = SimpleNamespace(channel_id="-100111", channel_title="My Channel")
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel_by_telegram_id", return_value=pending),
            patch("bot.handlers.channel.connect.delete_pending_channel") as mock_del,
        ):
            mock_del.return_value = AsyncMock()()
            await channel_confirm(cb, state, session)
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_connect_channel_no_pending(self):
        from bot.handlers.channel.connect import connect_channel

        cb = _make_callback(data="connect_channel_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel", return_value=None),
        ):
            await connect_channel(cb, state, session)
        cb.message.edit_text.assert_awaited_once()
        assert "не знайдено" in cb.message.edit_text.call_args[0][0]

    async def test_connect_channel_success(self):
        from bot.handlers.channel.connect import connect_channel

        cb = _make_callback(data="connect_channel_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        pending = SimpleNamespace(channel_id="-100111", channel_title="My Channel")
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel", return_value=pending),
            patch("bot.handlers.channel.connect.delete_pending_channel") as mock_del,
        ):
            mock_del.return_value = AsyncMock()()
            await connect_channel(cb, state, session)
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_replace_channel_no_pending(self):
        from bot.handlers.channel.connect import replace_channel

        cb = _make_callback(data="replace_channel_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel", return_value=None),
        ):
            await replace_channel(cb, state, session)
        cb.message.edit_text.assert_awaited_once()

    async def test_replace_channel_success(self):
        from bot.handlers.channel.connect import replace_channel

        cb = _make_callback(data="replace_channel_-100111")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        pending = SimpleNamespace(channel_id="-100111", channel_title="New Channel")
        with (
            patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.connect.get_pending_channel", return_value=pending),
            patch("bot.handlers.channel.connect.delete_pending_channel") as mock_del,
        ):
            mock_del.return_value = AsyncMock()()
            await replace_channel(cb, state, session)
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_connect_channel_no_user(self):
        from bot.handlers.channel.connect import connect_channel

        cb = _make_callback(data="connect_channel_-100111")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=None):
            await connect_channel(cb, state, session)
        cb.message.edit_text.assert_not_awaited()

    async def test_replace_channel_no_user(self):
        from bot.handlers.channel.connect import replace_channel

        cb = _make_callback(data="replace_channel_-100111")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.connect.get_user_by_telegram_id", return_value=None):
            await replace_channel(cb, state, session)
        cb.message.edit_text.assert_not_awaited()

    async def test_keep_current(self):
        from bot.handlers.channel.connect import keep_current

        cb = _make_callback(data="keep_current_channel")
        session = AsyncMock()
        with (
            patch("bot.handlers.channel.connect.delete_pending_channel_by_telegram_id") as mock_del,
            patch("bot.handlers.channel.connect.get_understood_keyboard", return_value=MagicMock()),
        ):
            mock_del.return_value = AsyncMock()()
            await keep_current(cb, session)
        cb.message.edit_text.assert_awaited_once()

    async def test_cancel_connect(self):
        from bot.handlers.channel.connect import cancel_connect

        cb = _make_callback(data="cancel_channel_connect")
        session = AsyncMock()
        with (
            patch("bot.handlers.channel.connect.delete_pending_channel_by_telegram_id") as mock_del,
            patch("bot.handlers.channel.connect.get_understood_keyboard", return_value=MagicMock()),
        ):
            mock_del.return_value = AsyncMock()()
            await cancel_connect(cb, session)
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# conversation.py
# ---------------------------------------------------------------------------


class TestChannelConversation:
    async def test_handle_title_empty(self):
        from bot.handlers.channel.conversation import handle_title

        msg = _make_message(text="")
        state = _make_state()
        session = AsyncMock()
        await handle_title(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_title_none(self):
        from bot.handlers.channel.conversation import handle_title

        msg = _make_message(text=None)
        state = _make_state()
        session = AsyncMock()
        await handle_title(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_title_too_long(self):
        from bot.handlers.channel.conversation import handle_title
        from bot.utils.branding import MAX_USER_TITLE_LEN

        msg = _make_message(text="x" * (MAX_USER_TITLE_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_title(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_title_valid(self):
        from bot.handlers.channel.conversation import handle_title

        msg = _make_message(text="Київ Черга 3.1")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_title(msg, state, session)
        assert user.channel_config.channel_user_title == "Київ Черга 3.1"
        state.set_state.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_title_no_user(self):
        from bot.handlers.channel.conversation import handle_title

        msg = _make_message(text="Київ")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_title(msg, state, session)
        state.set_state.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_description_empty(self):
        from bot.handlers.channel.conversation import handle_description

        msg = _make_message(text="")
        state = _make_state()
        session = AsyncMock()
        await handle_description(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_description_too_long(self):
        from bot.handlers.channel.conversation import handle_description
        from bot.utils.branding import MAX_USER_DESC_LEN

        msg = _make_message(text="x" * (MAX_USER_DESC_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_description(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_description_no_user(self):
        from bot.handlers.channel.conversation import handle_description

        msg = _make_message(text="A description")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_description(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()

    async def test_handle_description_valid(self):
        from bot.handlers.channel.conversation import handle_description

        msg = _make_message(text="My description")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.conversation.apply_channel_branding") as mock_brand,
        ):
            mock_brand.return_value = AsyncMock()()
            await handle_description(msg, state, session)
        assert user.channel_config.channel_user_description == "My description"
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_edit_title_empty(self):
        from bot.handlers.channel.conversation import handle_edit_title

        msg = _make_message(text="")
        state = _make_state()
        session = AsyncMock()
        await handle_edit_title(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_edit_title_too_long(self):
        from bot.handlers.channel.conversation import handle_edit_title
        from bot.utils.branding import MAX_USER_TITLE_LEN

        msg = _make_message(text="x" * (MAX_USER_TITLE_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_edit_title(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_edit_title_valid(self):
        from bot.handlers.channel.conversation import handle_edit_title

        msg = _make_message(text="New Title")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.conversation.apply_channel_branding") as mock_brand,
        ):
            mock_brand.return_value = AsyncMock()()
            await handle_edit_title(msg, state, session)
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_edit_title_no_user(self):
        from bot.handlers.channel.conversation import handle_edit_title

        msg = _make_message(text="New Title")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_edit_title(msg, state, session)
        state.clear.assert_awaited_once()
        # When user/config is missing, an error reply is sent (NOT a misleading
        # "✅ Назву каналу змінено!" message), so msg.reply is awaited and
        # msg.answer is not.
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_edit_title_no_channel_config(self):
        # User exists but channel_config is None — should also early-return with
        # an error reply instead of the success message.
        from bot.handlers.channel.conversation import handle_edit_title

        msg = _make_message(text="New Title")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_edit_title(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_edit_description_empty(self):
        from bot.handlers.channel.conversation import handle_edit_description

        msg = _make_message(text="")
        state = _make_state()
        session = AsyncMock()
        await handle_edit_description(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_edit_description_too_long(self):
        from bot.handlers.channel.conversation import handle_edit_description
        from bot.utils.branding import MAX_USER_DESC_LEN

        msg = _make_message(text="x" * (MAX_USER_DESC_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_edit_description(msg, state, session)
        msg.reply.assert_awaited_once()

    async def test_handle_edit_description_valid(self):
        from bot.handlers.channel.conversation import handle_edit_description

        msg = _make_message(text="New desc")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.conversation.apply_channel_branding") as mock_brand,
        ):
            mock_brand.return_value = AsyncMock()()
            await handle_edit_description(msg, state, session)
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_edit_description_no_user(self):
        from bot.handlers.channel.conversation import handle_edit_description

        msg = _make_message(text="New desc")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_edit_description(msg, state, session)
        state.clear.assert_awaited_once()
        # When user/config is missing, an error reply is sent (NOT a misleading
        # "✅ Опис каналу змінено!" message), so msg.reply is awaited and
        # msg.answer is not.
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_edit_description_no_channel_config(self):
        from bot.handlers.channel.conversation import handle_edit_description

        msg = _make_message(text="New desc")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_edit_description(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_schedule_caption_no_text(self):
        from bot.handlers.channel.conversation import handle_schedule_caption

        msg = _make_message(text=None)
        state = _make_state()
        session = AsyncMock()
        await handle_schedule_caption(msg, state, session)
        msg.answer.assert_not_awaited()

    async def test_handle_schedule_caption_valid(self):
        from bot.handlers.channel.conversation import handle_schedule_caption

        msg = _make_message(text="Caption {d}")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_schedule_caption(msg, state, session)
        assert user.channel_config.schedule_caption == "Caption {d}"
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_schedule_caption_no_user(self):
        from bot.handlers.channel.conversation import handle_schedule_caption

        msg = _make_message(text="Caption {d}")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_schedule_caption(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_schedule_caption_no_channel_config(self):
        from bot.handlers.channel.conversation import handle_schedule_caption

        msg = _make_message(text="Caption {d}")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_schedule_caption(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_period_format_no_text(self):
        from bot.handlers.channel.conversation import handle_period_format

        msg = _make_message(text=None)
        state = _make_state()
        session = AsyncMock()
        await handle_period_format(msg, state, session)
        msg.answer.assert_not_awaited()

    async def test_handle_period_format_valid(self):
        from bot.handlers.channel.conversation import handle_period_format

        msg = _make_message(text="{s}-{f}")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_period_format(msg, state, session)
        assert user.channel_config.period_format == "{s}-{f}"
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_period_format_no_user(self):
        from bot.handlers.channel.conversation import handle_period_format

        msg = _make_message(text="{s}-{f}")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_period_format(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_period_format_no_channel_config(self):
        from bot.handlers.channel.conversation import handle_period_format

        msg = _make_message(text="{s}-{f}")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_period_format(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_power_off_text_no_text(self):
        from bot.handlers.channel.conversation import handle_power_off_text

        msg = _make_message(text=None)
        state = _make_state()
        session = AsyncMock()
        await handle_power_off_text(msg, state, session)
        msg.answer.assert_not_awaited()

    async def test_handle_power_off_text_valid(self):
        from bot.handlers.channel.conversation import handle_power_off_text

        msg = _make_message(text="Power off text")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_power_off_text(msg, state, session)
        assert user.channel_config.power_off_text == "Power off text"
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_power_off_text_no_user(self):
        from bot.handlers.channel.conversation import handle_power_off_text

        msg = _make_message(text="Power off text")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_power_off_text(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_power_off_text_no_channel_config(self):
        from bot.handlers.channel.conversation import handle_power_off_text

        msg = _make_message(text="Power off text")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_power_off_text(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_power_on_text_no_text(self):
        from bot.handlers.channel.conversation import handle_power_on_text

        msg = _make_message(text=None)
        state = _make_state()
        session = AsyncMock()
        await handle_power_on_text(msg, state, session)
        msg.answer.assert_not_awaited()

    async def test_handle_power_on_text_valid(self):
        from bot.handlers.channel.conversation import handle_power_on_text

        msg = _make_message(text="Power on text")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_power_on_text(msg, state, session)
        assert user.channel_config.power_on_text == "Power on text"
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()

    async def test_handle_power_on_text_no_user(self):
        from bot.handlers.channel.conversation import handle_power_on_text

        msg = _make_message(text="Power on text")
        state = _make_state()
        session = AsyncMock()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=None):
            await handle_power_on_text(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_power_on_text_no_channel_config(self):
        from bot.handlers.channel.conversation import handle_power_on_text

        msg = _make_message(text="Power on text")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_power_on_text(msg, state, session)
        state.clear.assert_awaited_once()
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_custom_test_no_text(self):
        from bot.handlers.channel.conversation import handle_custom_test

        msg = _make_message(text=None)
        state = _make_state()
        session = AsyncMock()
        await handle_custom_test(msg, state, session)
        msg.answer.assert_not_awaited()
        state.clear.assert_not_awaited()

    async def test_handle_custom_test_sends_to_channel(self):
        from bot.handlers.channel.conversation import handle_custom_test

        msg = _make_message(text="Custom test message")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_custom_test(msg, state, session)
        msg.bot.send_message.assert_awaited_once()
        msg.answer.assert_awaited_once()
        state.clear.assert_awaited_once()

    async def test_handle_custom_test_send_exception(self):
        from bot.handlers.channel.conversation import handle_custom_test

        msg = _make_message(text="Custom test message")
        msg.bot.send_message = AsyncMock(side_effect=Exception("fail"))
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_custom_test(msg, state, session)
        msg.answer.assert_awaited_once()
        assert "Помилка" in msg.answer.call_args[0][0]
        state.clear.assert_awaited_once()

    async def test_handle_custom_test_no_channel_id(self):
        from bot.handlers.channel.conversation import handle_custom_test

        msg = _make_message(text="Custom test message")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_id=None))
        with patch("bot.handlers.channel.conversation.get_user_by_telegram_id", return_value=user):
            await handle_custom_test(msg, state, session)
        msg.bot.send_message.assert_not_awaited()
        state.clear.assert_awaited_once()


# ---------------------------------------------------------------------------
# format.py
# ---------------------------------------------------------------------------


class TestChannelFormat:
    async def test_format_menu(self):
        from bot.handlers.channel.format import format_menu

        cb = _make_callback(data="channel_format")
        with patch("bot.handlers.channel.format.get_format_settings_keyboard", return_value=MagicMock()):
            await format_menu(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_schedule_settings_no_user(self):
        from bot.handlers.channel.format import format_schedule_settings

        cb = _make_callback(data="format_schedule_settings")
        session = AsyncMock()
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=None):
            await format_schedule_settings(cb, session)
        cb.message.edit_text.assert_not_awaited()

    async def test_format_schedule_settings_valid(self):
        from bot.handlers.channel.format import format_schedule_settings

        cb = _make_callback(data="format_schedule_settings")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.format.get_format_schedule_keyboard", return_value=MagicMock()),
        ):
            await format_schedule_settings(cb, session)
        cb.message.edit_text.assert_awaited_once()

    async def test_format_power_settings(self):
        from bot.handlers.channel.format import format_power_settings

        cb = _make_callback(data="format_power_settings")
        with patch("bot.handlers.channel.format.get_format_power_keyboard", return_value=MagicMock()):
            await format_power_settings(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_toggle_delete_no_user(self):
        from bot.handlers.channel.format import format_toggle_delete

        cb = _make_callback(data="format_toggle_delete")
        session = AsyncMock()
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=None):
            await format_toggle_delete(cb, session)
        cb.message.edit_reply_markup.assert_not_awaited()

    async def test_format_toggle_delete_valid(self):
        from bot.handlers.channel.format import format_toggle_delete

        cb = _make_callback(data="format_toggle_delete")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.format.get_format_schedule_keyboard", return_value=MagicMock()),
        ):
            await format_toggle_delete(cb, session)
        assert user.channel_config.delete_old_message is True
        cb.message.edit_reply_markup.assert_awaited_once()

    async def test_format_toggle_piconly_valid(self):
        from bot.handlers.channel.format import format_toggle_piconly

        cb = _make_callback(data="format_toggle_piconly")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.format.get_format_schedule_keyboard", return_value=MagicMock()),
        ):
            await format_toggle_piconly(cb, session)
        assert user.channel_config.picture_only is True
        cb.message.edit_reply_markup.assert_awaited_once()

    async def test_format_toggle_piconly_no_user(self):
        from bot.handlers.channel.format import format_toggle_piconly

        cb = _make_callback(data="format_toggle_piconly")
        session = AsyncMock()
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=None):
            await format_toggle_piconly(cb, session)
        cb.message.edit_reply_markup.assert_not_awaited()

    async def test_format_schedule_text(self):
        from bot.handlers.channel.format import format_schedule_text

        cb = _make_callback(data="format_schedule_text")
        await format_schedule_text(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_schedule_caption(self):
        from bot.handlers.channel.format import format_schedule_caption

        cb = _make_callback(data="format_schedule_caption")
        state = _make_state()
        await format_schedule_caption(cb, state)
        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_schedule_periods(self):
        from bot.handlers.channel.format import format_schedule_periods

        cb = _make_callback(data="format_schedule_periods")
        state = _make_state()
        await format_schedule_periods(cb, state)
        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_power_off(self):
        from bot.handlers.channel.format import format_power_off

        cb = _make_callback(data="format_power_off")
        state = _make_state()
        await format_power_off(cb, state)
        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_power_on(self):
        from bot.handlers.channel.format import format_power_on

        cb = _make_callback(data="format_power_on")
        state = _make_state()
        await format_power_on(cb, state)
        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_format_reset_caption(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_caption")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(schedule_caption="Old"))
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        assert user.channel_config.schedule_caption is None
        cb.answer.assert_awaited_once()

    async def test_format_reset_periods(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_periods")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(period_format="Old"))
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        assert user.channel_config.period_format is None

    async def test_format_reset_power_off(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_power_off")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(power_off_text="Old"))
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        assert user.channel_config.power_off_text is None

    async def test_format_reset_power_on(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_power_on")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(power_on_text="Old"))
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        assert user.channel_config.power_on_text is None

    async def test_format_reset_all_schedule(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_all_schedule")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(schedule_caption="c", period_format="p"))
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        assert user.channel_config.schedule_caption is None
        assert user.channel_config.period_format is None

    async def test_format_reset_all_power(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_all_power")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(power_off_text="off", power_on_text="on"))
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        assert user.channel_config.power_off_text is None
        assert user.channel_config.power_on_text is None

    async def test_format_reset_unknown_action(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_unknown")
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=user):
            await format_reset(cb, session)
        cb.answer.assert_awaited_once_with()

    async def test_format_reset_no_user(self):
        from bot.handlers.channel.format import format_reset

        cb = _make_callback(data="format_reset_caption")
        session = AsyncMock()
        with patch("bot.handlers.channel.format.get_user_by_telegram_id", return_value=None):
            await format_reset(cb, session)
        cb.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# notifications.py
# ---------------------------------------------------------------------------


class TestChannelNotifications:
    async def test_no_user_returns_early(self):
        from bot.handlers.channel.notifications import channel_notifications

        cb = _make_callback(data="channel_notifications")
        session = AsyncMock()
        with patch("bot.handlers.channel.notifications.get_user_by_telegram_id", return_value=None):
            await channel_notifications(cb, session)
        cb.message.edit_text.assert_not_awaited()

    async def test_no_channel_config_returns_early(self):
        from bot.handlers.channel.notifications import channel_notifications

        cb = _make_callback(data="channel_notifications")
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.notifications.get_user_by_telegram_id", return_value=user):
            await channel_notifications(cb, session)
        cb.message.edit_text.assert_not_awaited()

    async def test_valid_user_edits_text(self):
        from bot.handlers.channel.notifications import channel_notifications

        cb = _make_callback(data="channel_notifications")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(
            ch_notify_remind_off=True,
            ch_notify_remind_on=True,
        ))
        with (
            patch("bot.handlers.channel.notifications.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.notifications.build_channel_notification_message", return_value="text"),
            patch("bot.handlers.channel.notifications.get_channel_notification_keyboard", return_value=MagicMock()),
        ):
            await channel_notifications(cb, session)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# pause.py
# ---------------------------------------------------------------------------


class TestChannelPause:
    async def test_channel_pause_shows_confirm(self):
        from bot.handlers.channel.pause import channel_pause

        cb = _make_callback(data="channel_pause")
        await channel_pause(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_pause_confirm_no_user(self):
        from bot.handlers.channel.pause import channel_pause_confirm

        cb = _make_callback(data="channel_pause_confirm")
        session = AsyncMock()
        with patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=None):
            await channel_pause_confirm(cb, session)
        cb.answer.assert_awaited_once_with("❌ Помилка")

    async def test_channel_pause_confirm_with_channel(self):
        from bot.handlers.channel.pause import channel_pause_confirm

        cb = _make_callback(data="channel_pause_confirm")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.pause.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.channel.pause.get_main_menu", return_value=MagicMock()),
        ):
            await channel_pause_confirm(cb, session)
        assert user.channel_config.channel_paused is True
        cb.bot.send_message.assert_awaited_once()

    async def test_channel_pause_confirm_send_fails(self):
        from bot.handlers.channel.pause import channel_pause_confirm

        cb = _make_callback(data="channel_pause_confirm")
        cb.bot.send_message = AsyncMock(side_effect=Exception("network error"))
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.pause.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.channel.pause.get_main_menu", return_value=MagicMock()),
        ):
            await channel_pause_confirm(cb, session)  # should not raise
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_pause_confirm_no_channel_config(self):
        from bot.handlers.channel.pause import channel_pause_confirm

        cb = _make_callback(data="channel_pause_confirm")
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with (
            patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.pause.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.channel.pause.get_main_menu", return_value=MagicMock()),
        ):
            await channel_pause_confirm(cb, session)
        cb.bot.send_message.assert_not_awaited()

    async def test_channel_resume_shows_confirm(self):
        from bot.handlers.channel.pause import channel_resume

        cb = _make_callback(data="channel_resume")
        await channel_resume(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_resume_confirm_no_user(self):
        from bot.handlers.channel.pause import channel_resume_confirm

        cb = _make_callback(data="channel_resume_confirm")
        session = AsyncMock()
        with patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=None):
            await channel_resume_confirm(cb, session)
        cb.answer.assert_awaited_once_with("❌ Помилка")

    async def test_channel_resume_confirm_with_channel(self):
        from bot.handlers.channel.pause import channel_resume_confirm

        cb = _make_callback(data="channel_resume_confirm")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_paused=True))
        with (
            patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.pause.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.channel.pause.get_main_menu", return_value=MagicMock()),
        ):
            await channel_resume_confirm(cb, session)
        assert user.channel_config.channel_paused is False
        cb.bot.send_message.assert_awaited_once()

    async def test_channel_resume_confirm_send_fails(self):
        from bot.handlers.channel.pause import channel_resume_confirm

        cb = _make_callback(data="channel_resume_confirm")
        cb.bot.send_message = AsyncMock(side_effect=Exception("error"))
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_paused=True))
        with (
            patch("bot.handlers.channel.pause.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.pause.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.channel.pause.get_main_menu", return_value=MagicMock()),
        ):
            await channel_resume_confirm(cb, session)  # should not raise
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# settings.py
# ---------------------------------------------------------------------------


class TestChannelSettings:
    async def test_channel_info_no_user(self):
        from bot.handlers.channel.settings import channel_info

        cb = _make_callback(data="channel_info")
        session = AsyncMock()
        with patch("bot.handlers.channel.settings.get_user_by_telegram_id", return_value=None):
            await channel_info(cb, session)
        cb.answer.assert_awaited_once_with("❌ Канал не підключено")

    async def test_channel_info_no_channel_config(self):
        from bot.handlers.channel.settings import channel_info

        cb = _make_callback(data="channel_info")
        session = AsyncMock()
        user = _make_user(channel_config=None)
        with patch("bot.handlers.channel.settings.get_user_by_telegram_id", return_value=user):
            await channel_info(cb, session)
        cb.answer.assert_awaited_once_with("❌ Канал не підключено")

    async def test_channel_info_valid(self):
        from bot.handlers.channel.settings import channel_info

        cb = _make_callback(data="channel_info")
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.settings.get_user_by_telegram_id", return_value=user):
            await channel_info(cb, session)
        cb.answer.assert_awaited_once()
        call_kwargs = cb.answer.call_args
        assert call_kwargs[1]["show_alert"] is True

    async def test_channel_info_no_title(self):
        from bot.handlers.channel.settings import channel_info

        cb = _make_callback(data="channel_info")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_title=None))
        with patch("bot.handlers.channel.settings.get_user_by_telegram_id", return_value=user):
            await channel_info(cb, session)
        cb.answer.assert_awaited_once()

    async def test_channel_disable_shows_confirm(self):
        from bot.handlers.channel.settings import channel_disable

        cb = _make_callback(data="channel_disable")
        await channel_disable(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_disable_confirm_no_user(self):
        from bot.handlers.channel.settings import channel_disable_confirm

        cb = _make_callback(data="channel_disable_confirm")
        session = AsyncMock()
        with (
            patch("bot.handlers.channel.settings.get_user_by_telegram_id", return_value=None),
            patch("bot.handlers.channel.settings.get_understood_keyboard", return_value=MagicMock()),
        ):
            await channel_disable_confirm(cb, session)
        cb.answer.assert_awaited_once_with("✅ Публікації вимкнено")
        cb.message.edit_text.assert_awaited_once()

    async def test_channel_disable_confirm_clears_config(self):
        from bot.handlers.channel.settings import channel_disable_confirm

        cb = _make_callback(data="channel_disable_confirm")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.settings.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.settings.get_understood_keyboard", return_value=MagicMock()),
        ):
            await channel_disable_confirm(cb, session)
        assert user.channel_config.channel_id is None
        assert user.channel_config.channel_title is None
        assert user.channel_config.channel_status == "disconnected"
        cb.answer.assert_awaited_once_with("✅ Публікації вимкнено")


# ---------------------------------------------------------------------------
# test.py (channel_test handler)
# ---------------------------------------------------------------------------


class TestChannelTestHandler:
    async def test_channel_test_shows_menu(self):
        from bot.handlers.channel.test import channel_test

        cb = _make_callback(data="channel_test")
        with patch("bot.handlers.channel.test.get_test_publication_keyboard", return_value=MagicMock()):
            await channel_test(cb)
        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_test_schedule_no_user(self):
        from bot.handlers.channel.test import test_schedule

        cb = _make_callback(data="test_schedule")
        session = AsyncMock()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=None):
            await test_schedule(cb, session)
        cb.answer.assert_awaited_once_with("❌ Канал не підключено")

    async def test_test_schedule_no_channel_id(self):
        from bot.handlers.channel.test import test_schedule

        cb = _make_callback(data="test_schedule")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(channel_id=None))
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_schedule(cb, session)
        cb.answer.assert_awaited_once_with("❌ Канал не підключено")

    async def test_test_schedule_no_data(self):
        from bot.handlers.channel.test import test_schedule

        cb = _make_callback(data="test_schedule")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.test.fetch_schedule_data", return_value=None),
        ):
            await test_schedule(cb, session)
        cb.answer.assert_awaited_once_with("❌ Дані недоступні")

    async def test_test_schedule_with_image(self):
        from bot.handlers.channel.test import test_schedule

        cb = _make_callback(data="test_schedule")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.test.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.handlers.channel.test.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.channel.test.format_schedule_message", return_value="<b>text</b>"),
            patch("bot.handlers.channel.test.html_to_entities", return_value=("text", [])),
            patch("bot.handlers.channel.test.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.channel.test.fetch_schedule_image", return_value=b"imgdata"),
        ):
            await test_schedule(cb, session)
        cb.bot.send_photo.assert_awaited_once()
        cb.answer.assert_awaited_once_with("✅ Графік опубліковано в канал!")

    async def test_test_schedule_without_image(self):
        from bot.handlers.channel.test import test_schedule

        cb = _make_callback(data="test_schedule")
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.test.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.handlers.channel.test.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.channel.test.format_schedule_message", return_value="text"),
            patch("bot.handlers.channel.test.html_to_entities", return_value=("text", [])),
            patch("bot.handlers.channel.test.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.channel.test.fetch_schedule_image", return_value=None),
        ):
            await test_schedule(cb, session)
        cb.bot.send_message.assert_awaited_once()
        cb.answer.assert_awaited_once_with("✅ Графік опубліковано в канал!")

    async def test_test_schedule_exception(self):
        from bot.handlers.channel.test import test_schedule

        cb = _make_callback(data="test_schedule")
        cb.bot.send_photo = AsyncMock(side_effect=Exception("fail"))
        session = AsyncMock()
        user = _make_user()
        with (
            patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user),
            patch("bot.handlers.channel.test.fetch_schedule_data", return_value={"data": "x"}),
            patch("bot.handlers.channel.test.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.channel.test.format_schedule_message", return_value="text"),
            patch("bot.handlers.channel.test.html_to_entities", return_value=("text", [])),
            patch("bot.handlers.channel.test.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.channel.test.fetch_schedule_image", return_value=b"imgdata"),
        ):
            await test_schedule(cb, session)
        cb.answer.assert_awaited_once_with("❌ Помилка публікації. Спробуйте пізніше.", show_alert=True)

    async def test_test_power_on_no_user(self):
        from bot.handlers.channel.test import test_power_on

        cb = _make_callback(data="test_power_on")
        session = AsyncMock()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=None):
            await test_power_on(cb, session)
        cb.answer.assert_awaited_once_with("❌ Канал не підключено")

    async def test_test_power_on_success(self):
        from bot.handlers.channel.test import test_power_on

        cb = _make_callback(data="test_power_on")
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_power_on(cb, session)
        cb.bot.send_message.assert_awaited_once()
        cb.answer.assert_awaited_once_with("✅ Тестове повідомлення опубліковано!")

    async def test_test_power_on_custom_text(self):
        from bot.handlers.channel.test import test_power_on

        cb = _make_callback(data="test_power_on")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(power_on_text="Custom ON"))
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_power_on(cb, session)
        assert cb.bot.send_message.call_args[0][1] == "Custom ON"

    async def test_test_power_on_exception(self):
        from bot.handlers.channel.test import test_power_on

        cb = _make_callback(data="test_power_on")
        cb.bot.send_message = AsyncMock(side_effect=Exception("fail"))
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_power_on(cb, session)
        cb.answer.assert_awaited_once_with("❌ Помилка. Спробуйте пізніше.", show_alert=True)

    async def test_test_power_off_no_user(self):
        from bot.handlers.channel.test import test_power_off

        cb = _make_callback(data="test_power_off")
        session = AsyncMock()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=None):
            await test_power_off(cb, session)
        cb.answer.assert_awaited_once_with("❌ Канал не підключено")

    async def test_test_power_off_success(self):
        from bot.handlers.channel.test import test_power_off

        cb = _make_callback(data="test_power_off")
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_power_off(cb, session)
        cb.bot.send_message.assert_awaited_once()
        cb.answer.assert_awaited_once_with("✅ Тестове повідомлення опубліковано!")

    async def test_test_power_off_custom_text(self):
        from bot.handlers.channel.test import test_power_off

        cb = _make_callback(data="test_power_off")
        session = AsyncMock()
        user = _make_user(channel_config=_make_channel_config(power_off_text="Custom OFF"))
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_power_off(cb, session)
        assert cb.bot.send_message.call_args[0][1] == "Custom OFF"

    async def test_test_power_off_exception(self):
        from bot.handlers.channel.test import test_power_off

        cb = _make_callback(data="test_power_off")
        cb.bot.send_message = AsyncMock(side_effect=Exception("fail"))
        session = AsyncMock()
        user = _make_user()
        with patch("bot.handlers.channel.test.get_user_by_telegram_id", return_value=user):
            await test_power_off(cb, session)
        cb.answer.assert_awaited_once_with("❌ Помилка. Спробуйте пізніше.", show_alert=True)

    async def test_test_custom_sets_state(self):
        from bot.handlers.channel.test import test_custom

        cb = _make_callback(data="test_custom")
        state = _make_state()
        await test_custom(cb, state)
        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    # ── length validation (new) ──────────────────────────────────────────────

    async def test_handle_schedule_caption_too_long(self):
        from bot.handlers.channel.conversation import MAX_CHANNEL_TEXT_LEN, handle_schedule_caption

        msg = _make_message(text="x" * (MAX_CHANNEL_TEXT_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_schedule_caption(msg, state, session)
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_period_format_too_long(self):
        from bot.handlers.channel.conversation import MAX_CHANNEL_TEXT_LEN, handle_period_format

        msg = _make_message(text="x" * (MAX_CHANNEL_TEXT_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_period_format(msg, state, session)
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_power_off_text_too_long(self):
        from bot.handlers.channel.conversation import MAX_CHANNEL_TEXT_LEN, handle_power_off_text

        msg = _make_message(text="x" * (MAX_CHANNEL_TEXT_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_power_off_text(msg, state, session)
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_handle_power_on_text_too_long(self):
        from bot.handlers.channel.conversation import MAX_CHANNEL_TEXT_LEN, handle_power_on_text

        msg = _make_message(text="x" * (MAX_CHANNEL_TEXT_LEN + 1))
        state = _make_state()
        session = AsyncMock()
        await handle_power_on_text(msg, state, session)
        msg.reply.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_channel_confirm_malformed_data(self):
        """channel_confirm_: non-integer suffix → answer error, no DB call."""
        from bot.handlers.channel.connect import channel_confirm

        cb = _make_callback(data="channel_confirm_not_an_int")
        state = _make_state()
        session = AsyncMock()
        await channel_confirm(cb, state, session)
        cb.answer.assert_awaited_once_with("❌ Невідомий формат.", show_alert=True)
