"""Tests for bot/handlers/menu/* and bot/handlers/settings/* and bot/handlers/__init__.py.

Covered scenarios:
- menu/help.py: menu_help, help_instructions, help_faq, help_support,
  instr_region, instr_notif, instr_channel, instr_ip, instr_schedule, instr_bot_settings
- menu/navigation.py: back_to_main (user not found, old menu msg deletion, photo/text branches)
- menu/reminders.py: reminder_dismiss, reminder_show_schedule (no user)
- menu/schedule.py: _send_schedule_photo (image/no-image, edit/no-edit),
  menu_schedule, schedule_check (cooldown, no data, hash equal/different),
  change_queue (photo/text)
- menu/settings.py: menu_settings (no user, photo, edit)
- menu/stats.py: menu_stats, stats_week, stats_device (no IP, state on/off/unknown)
- menu/timer.py: menu_timer (no user, no data, with data)
- settings/channel.py: settings_channel, channel_reconnect
- settings/cleanup.py: settings_cleanup, cleanup_toggle_commands, cleanup_toggle_messages
- settings/data.py: settings_delete_data, delete_data_step2, confirm_delete_data,
  settings_deactivate, confirm_deactivate
- settings/region.py: settings_region, settings_region_confirm, back_to_settings
- handlers/__init__.py: register_all_handlers
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(**kwargs) -> MagicMock:
    msg = MagicMock()
    msg.message_id = kwargs.get("message_id", 100)
    msg.chat = SimpleNamespace(id=999)
    msg.photo = kwargs.get("photo", None)
    msg.edit_text = AsyncMock(return_value=True)
    msg.edit_media = AsyncMock()
    msg.answer = AsyncMock(return_value=MagicMock(message_id=200))
    msg.answer_photo = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _make_callback(user_id: int = 42, data: str = "", **kwargs) -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id)
    cb.data = data
    cb.bot = AsyncMock()
    cb.bot.delete_message = AsyncMock()
    cb.answer = AsyncMock()
    cb.message = _make_message(**kwargs)
    return cb


def _make_user(**kwargs) -> SimpleNamespace:
    ns = SimpleNamespace(
        id=1,
        telegram_id=42,
        region="kyiv",
        queue="1.1",
        router_ip=None,
        last_menu_message_id=None,
        channel_config=None,
        notification_settings=None,
        power_tracking=None,
        is_active=True,
    )
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


def _make_channel_config(**kwargs) -> SimpleNamespace:
    cc = SimpleNamespace(
        channel_id=-1001234567890,
        channel_title="Test Channel",
        channel_status="active",
        channel_paused=False,
        channel_guard_warnings=0,
    )
    for k, v in kwargs.items():
        setattr(cc, k, v)
    return cc


def _make_notification_settings(**kwargs) -> SimpleNamespace:
    ns = SimpleNamespace(
        auto_delete_commands=True,
        auto_delete_bot_messages=False,
    )
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# menu/help.py
# ---------------------------------------------------------------------------

class TestMenuHelp:
    async def test_menu_help_with_user_and_msg(self):
        from bot.handlers.menu.help import menu_help

        user = _make_user()
        cb = _make_callback()
        mock_msg = MagicMock(message_id=555)

        with (
            patch("bot.handlers.menu.help.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock(return_value=mock_msg)),
            patch("bot.handlers.menu.help.app_settings") as ms,
            patch("bot.handlers.menu.help.get_help_keyboard", return_value=MagicMock()),
        ):
            ms.FAQ_CHANNEL_URL = "https://faq.example.com"
            ms.SUPPORT_CHANNEL_URL = "https://support.example.com"
            await menu_help(cb, AsyncMock())

        cb.answer.assert_awaited_once()
        assert user.last_menu_message_id == 555

    async def test_menu_help_no_msg_returned(self):
        from bot.handlers.menu.help import menu_help

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.help.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.help.app_settings") as ms,
            patch("bot.handlers.menu.help.get_help_keyboard", return_value=MagicMock()),
        ):
            ms.FAQ_CHANNEL_URL = ""
            ms.SUPPORT_CHANNEL_URL = ""
            await menu_help(cb, AsyncMock())

        # last_menu_message_id should not be updated
        assert user.last_menu_message_id is None

    async def test_menu_help_no_user(self):
        from bot.handlers.menu.help import menu_help

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.help.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.help.app_settings") as ms,
            patch("bot.handlers.menu.help.get_help_keyboard", return_value=MagicMock()),
        ):
            ms.FAQ_CHANNEL_URL = ""
            ms.SUPPORT_CHANNEL_URL = ""
            await menu_help(cb, AsyncMock())

        cb.answer.assert_awaited_once()

    async def test_help_instructions(self):
        from bot.handlers.menu.help import help_instructions

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.help.get_instructions_keyboard", return_value=MagicMock()),
        ):
            await help_instructions(cb)

        cb.answer.assert_awaited_once()
        mock_send.assert_awaited_once()

    async def test_help_faq(self):
        from bot.handlers.menu.help import help_faq

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.help.app_settings") as ms,
            patch("bot.handlers.menu.help.get_faq_keyboard", return_value=MagicMock()),
        ):
            ms.FAQ_CHANNEL_URL = "https://faq.example.com"
            await help_faq(cb)

        mock_send.assert_awaited_once()

    async def test_help_support(self):
        from bot.handlers.menu.help import help_support

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.help.app_settings") as ms,
            patch("bot.handlers.menu.help.get_support_keyboard", return_value=MagicMock()),
        ):
            ms.SUPPORT_CHANNEL_URL = ""
            await help_support(cb)

        mock_send.assert_awaited_once()

    async def test_instr_region(self):
        from bot.handlers.menu.help import instr_region

        cb = _make_callback()
        with patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send:
            await instr_region(cb)
        mock_send.assert_awaited_once()

    async def test_instr_notif(self):
        from bot.handlers.menu.help import instr_notif

        cb = _make_callback()
        with patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send:
            await instr_notif(cb)
        mock_send.assert_awaited_once()

    async def test_instr_channel(self):
        from bot.handlers.menu.help import instr_channel

        cb = _make_callback()
        with patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send:
            await instr_channel(cb)
        mock_send.assert_awaited_once()

    async def test_instr_ip(self):
        from bot.handlers.menu.help import instr_ip

        cb = _make_callback()
        with patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send:
            await instr_ip(cb)
        mock_send.assert_awaited_once()

    async def test_instr_schedule(self):
        from bot.handlers.menu.help import instr_schedule

        cb = _make_callback()
        with patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send:
            await instr_schedule(cb)
        mock_send.assert_awaited_once()

    async def test_instr_bot_settings(self):
        from bot.handlers.menu.help import instr_bot_settings

        cb = _make_callback()
        with patch("bot.handlers.menu.help.safe_edit_or_resend", AsyncMock()) as mock_send:
            await instr_bot_settings(cb)
        mock_send.assert_awaited_once()


# ---------------------------------------------------------------------------
# menu/navigation.py
# ---------------------------------------------------------------------------

class TestMenuNavigation:
    async def test_back_to_main_no_user(self):
        from bot.handlers.menu.navigation import back_to_main

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.navigation.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await back_to_main(cb, AsyncMock())

        mock_edit.assert_awaited_once()

    async def test_back_to_main_deletes_old_menu_message(self):
        from bot.handlers.menu.navigation import back_to_main

        user = _make_user(last_menu_message_id=50)
        cb = _make_callback()
        cb.message.message_id = 100  # different from last_menu_message_id=50

        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.navigation.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.navigation.get_main_menu", return_value=MagicMock()),
            patch("bot.handlers.menu.navigation.safe_edit_text", AsyncMock(return_value=True)),
            patch("bot.handlers.menu.navigation.safe_delete", AsyncMock()),
        ):
            await back_to_main(cb, AsyncMock())

        cb.bot.delete_message.assert_awaited_once_with(cb.message.chat.id, 50)

    async def test_back_to_main_same_message_id_no_delete(self):
        from bot.handlers.menu.navigation import back_to_main

        user = _make_user(last_menu_message_id=100)
        cb = _make_callback()
        cb.message.message_id = 100

        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.navigation.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.navigation.get_main_menu", return_value=MagicMock()),
            patch("bot.handlers.menu.navigation.safe_edit_text", AsyncMock(return_value=True)),
        ):
            await back_to_main(cb, AsyncMock())

        cb.bot.delete_message.assert_not_awaited()

    async def test_back_to_main_delete_raises_exception(self):
        from bot.handlers.menu.navigation import back_to_main

        user = _make_user(last_menu_message_id=50)
        cb = _make_callback()
        cb.message.message_id = 100
        cb.bot.delete_message = AsyncMock(side_effect=Exception("cannot delete"))

        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.navigation.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.navigation.get_main_menu", return_value=MagicMock()),
            patch("bot.handlers.menu.navigation.safe_edit_text", AsyncMock(return_value=True)),
        ):
            # should not raise
            await back_to_main(cb, AsyncMock())

    async def test_back_to_main_photo_message(self):
        from bot.handlers.menu.navigation import back_to_main

        user = _make_user(last_menu_message_id=None)
        cb = _make_callback(photo=True)
        cb.message.photo = True
        reply_msg = MagicMock(message_id=300)
        cb.message.answer = AsyncMock(return_value=reply_msg)

        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.navigation.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.navigation.get_main_menu", return_value=MagicMock()),
            patch("bot.handlers.menu.navigation.safe_delete", AsyncMock()),
        ):
            await back_to_main(cb, AsyncMock())

        cb.message.answer.assert_awaited_once()
        assert user.last_menu_message_id == 300

    async def test_back_to_main_edit_fails_then_answer(self):
        from bot.handlers.menu.navigation import back_to_main

        user = _make_user(last_menu_message_id=None)
        cb = _make_callback()
        cb.message.photo = None
        reply_msg = MagicMock(message_id=400)
        cb.message.answer = AsyncMock(return_value=reply_msg)

        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.navigation.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.navigation.get_main_menu", return_value=MagicMock()),
            patch("bot.handlers.menu.navigation.safe_edit_text", AsyncMock(return_value=False)),
        ):
            await back_to_main(cb, AsyncMock())

        cb.message.answer.assert_awaited_once()

    async def test_back_to_main_with_channel_config(self):
        from bot.handlers.menu.navigation import back_to_main

        cc = _make_channel_config(channel_id=-100, channel_paused=True)
        user = _make_user(last_menu_message_id=None, channel_config=cc)
        cb = _make_callback()
        cb.message.photo = None
        edited_msg = MagicMock(message_id=500)

        with (
            patch("bot.handlers.menu.navigation.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.navigation.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.navigation.get_main_menu", return_value=MagicMock()),
            patch("bot.handlers.menu.navigation.safe_edit_text", AsyncMock(return_value=True)),
        ):
            await back_to_main(cb, AsyncMock())


# ---------------------------------------------------------------------------
# menu/reminders.py
# ---------------------------------------------------------------------------

class TestMenuReminders:
    async def test_reminder_dismiss_no_user(self):
        from bot.handlers.menu.reminders import reminder_dismiss

        cb = _make_callback()
        cb.message.delete = AsyncMock()

        with patch("bot.handlers.menu.reminders.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await reminder_dismiss(cb, AsyncMock())

        cb.message.delete.assert_awaited_once()
        cb.message.answer.assert_not_awaited()

    async def test_reminder_dismiss_with_user(self):
        from bot.handlers.menu.reminders import reminder_dismiss

        user = _make_user()
        cb = _make_callback()
        cb.message.delete = AsyncMock()
        reply_msg = MagicMock(message_id=111)
        cb.message.answer = AsyncMock(return_value=reply_msg)

        with (
            patch("bot.handlers.menu.reminders.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.reminders.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.reminders.get_main_menu", return_value=MagicMock()),
        ):
            await reminder_dismiss(cb, AsyncMock())

        cb.message.answer.assert_awaited_once()
        assert user.last_menu_message_id == 111

    async def test_reminder_dismiss_delete_fails(self):
        from bot.handlers.menu.reminders import reminder_dismiss

        user = _make_user()
        cb = _make_callback()
        cb.message.delete = AsyncMock(side_effect=Exception("cannot delete"))
        reply_msg = MagicMock(message_id=112)
        cb.message.answer = AsyncMock(return_value=reply_msg)

        with (
            patch("bot.handlers.menu.reminders.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.reminders.format_main_menu_message", return_value="text"),
            patch("bot.handlers.menu.reminders.get_main_menu", return_value=MagicMock()),
        ):
            await reminder_dismiss(cb, AsyncMock())

        cb.message.answer.assert_awaited_once()

    async def test_reminder_show_schedule_no_user(self):
        from bot.handlers.menu.reminders import reminder_show_schedule

        cb = _make_callback()

        with patch("bot.handlers.menu.reminders.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await reminder_show_schedule(cb, AsyncMock())

        cb.answer.assert_awaited()

    async def test_reminder_show_schedule_with_user(self):
        from bot.handlers.menu.reminders import reminder_show_schedule

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.reminders.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.reminders._send_schedule_photo", AsyncMock()) as mock_send,
        ):
            await reminder_show_schedule(cb, AsyncMock())

        mock_send.assert_awaited_once_with(cb, user, mock_send.call_args[0][2], edit_photo=False)


# ---------------------------------------------------------------------------
# menu/schedule.py
# ---------------------------------------------------------------------------

class TestSendSchedulePhoto:
    async def test_send_schedule_photo_no_data(self):
        from bot.handlers.menu.schedule import _send_schedule_photo

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.get_error_keyboard", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=False)

        cb.message.answer.assert_awaited_once()

    async def test_send_schedule_photo_with_image_no_edit(self):
        from bot.handlers.menu.schedule import _send_schedule_photo

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>text</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"img")),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
            patch("bot.handlers.menu.schedule.BufferedInputFile", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=False)

        cb.message.answer_photo.assert_awaited_once()

    async def test_send_schedule_photo_with_image_edit_success(self):
        from bot.handlers.menu.schedule import _send_schedule_photo

        user = _make_user()
        cb = _make_callback()
        cb.message.edit_media = AsyncMock()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>text</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"img")),
            patch("bot.handlers.menu.schedule.BufferedInputFile", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.InputMediaPhoto", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=True)

        cb.message.edit_media.assert_awaited_once()

    async def test_send_schedule_photo_with_image_edit_fallback(self):
        from bot.handlers.menu.schedule import _send_schedule_photo

        user = _make_user()
        cb = _make_callback()
        cb.message.edit_media = AsyncMock(side_effect=Exception("fail"))

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="text"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"img")),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
            patch("bot.handlers.menu.schedule.BufferedInputFile", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.InputMediaPhoto", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=True)

        cb.message.answer_photo.assert_awaited_once()

    async def test_send_schedule_photo_no_image_no_edit(self):
        from bot.handlers.menu.schedule import _send_schedule_photo

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="text"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=False)

        cb.message.answer.assert_awaited_once()

    async def test_send_schedule_photo_no_image_edit_success(self):
        from bot.handlers.menu.schedule import _send_schedule_photo

        user = _make_user()
        cb = _make_callback()
        cb.message.edit_text = AsyncMock()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="text"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=True)

        cb.message.edit_text.assert_awaited_once()

    async def test_send_schedule_photo_no_image_edit_fallback(self):
        from bot.handlers.menu.schedule import _send_schedule_photo, MSG_NOT_MODIFIED

        user = _make_user()
        cb = _make_callback()
        cb.message.edit_text = AsyncMock(side_effect=Exception("fail"))

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="text"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=True)

        cb.message.answer.assert_awaited_once()

    async def test_send_schedule_photo_no_image_edit_not_modified(self):
        from bot.handlers.menu.schedule import _send_schedule_photo, MSG_NOT_MODIFIED

        user = _make_user()
        cb = _make_callback()
        cb.message.edit_text = AsyncMock(side_effect=Exception(MSG_NOT_MODIFIED))
        cb.message.answer = AsyncMock()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="text"),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("text", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
        ):
            await _send_schedule_photo(cb, user, AsyncMock(), edit_photo=True)

        cb.message.answer.assert_not_awaited()


class TestMenuSchedule:
    async def test_menu_schedule_no_user(self):
        from bot.handlers.menu.schedule import menu_schedule

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await menu_schedule(cb, AsyncMock())

        mock_edit.assert_awaited_once()

    async def test_menu_schedule_with_user(self):
        from bot.handlers.menu.schedule import menu_schedule

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()) as mock_send,
        ):
            await menu_schedule(cb, AsyncMock())

        mock_send.assert_awaited_once()


class TestScheduleCheck:
    def setup_method(self):
        import bot.handlers.menu.schedule as sched_mod
        sched_mod._user_last_check = {}
        sched_mod._last_check_cleanup_at = 0.0

    async def test_schedule_check_no_user(self):
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
        ):
            await schedule_check(cb, AsyncMock())

        cb.answer.assert_awaited_with("❌ Користувача не знайдено")

    async def test_schedule_check_cooldown(self):
        import time

        import bot.handlers.menu.schedule as sched_mod
        from bot.handlers.menu.schedule import schedule_check

        user = _make_user()
        cb = _make_callback(user_id=42)
        sched_mod._user_last_check[42] = time.monotonic()  # just pressed

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
        ):
            await schedule_check(cb, AsyncMock())

        # should have answered with cooldown message
        assert cb.answer.called
        call_args = cb.answer.call_args[0][0]
        assert "Зачекай" in call_args

    async def test_schedule_check_api_failure(self):
        import bot.handlers.menu.schedule as sched_mod
        from bot.handlers.menu.schedule import schedule_check

        user = _make_user()
        cb = _make_callback(user_id=99)
        sched_mod._user_last_check = {}

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="0")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value=None),
        ):
            await schedule_check(cb, AsyncMock())

        cb.answer.assert_awaited_with("❌ Не вдалось отримати дані", show_alert=False)

    async def test_schedule_check_hash_changed(self):
        import bot.handlers.menu.schedule as sched_mod
        from bot.handlers.menu.schedule import schedule_check

        user = _make_user()
        cb = _make_callback(user_id=77)
        sched_mod._user_last_check = {}

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="0")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(side_effect=[
                {"events": [1]},
                {"events": [1, 2]},
            ])),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", side_effect=[
                {"events": ["a"]},
                {"events": ["a", "b"]},
            ]),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", side_effect=["hash1", "hash2"]),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, AsyncMock())

        cb.answer.assert_awaited_with("💡 Знайдено зміни — оновлено", show_alert=False)

    async def test_schedule_check_hash_same(self):
        import bot.handlers.menu.schedule as sched_mod
        from bot.handlers.menu.schedule import schedule_check

        user = _make_user()
        cb = _make_callback(user_id=88)
        sched_mod._user_last_check = {}

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="0")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(side_effect=[
                {"events": [1]},
                {"events": [1]},
            ])),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", side_effect=[
                {"events": ["a"]},
                {"events": ["a"]},
            ]),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", side_effect=["same", "same"]),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, AsyncMock())

        cb.answer.assert_awaited_with("✅ Без змін — дані актуальні", show_alert=False)

    async def test_schedule_check_invalid_cooldown_setting(self):
        import bot.handlers.menu.schedule as sched_mod
        from bot.handlers.menu.schedule import schedule_check

        user = _make_user()
        cb = _make_callback(user_id=55)
        sched_mod._user_last_check = {}

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="not_a_number")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value=None)),
        ):
            await schedule_check(cb, AsyncMock())

        # Should use default cooldown and proceed
        assert cb.answer.called


class TestChangeQueue:
    async def test_change_queue_no_user(self):
        from bot.handlers.menu.schedule import change_queue

        cb = _make_callback()
        state = AsyncMock()

        with patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await change_queue(cb, state, AsyncMock())

        state.set_state.assert_not_awaited()

    async def test_change_queue_text_message(self):
        from bot.handlers.menu.schedule import change_queue

        user = _make_user()
        cb = _make_callback()
        cb.message.photo = None
        state = AsyncMock()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_region_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await change_queue(cb, state, AsyncMock())

        state.set_state.assert_awaited_once()
        mock_edit.assert_awaited_once()

    async def test_change_queue_photo_message(self):
        from bot.handlers.menu.schedule import change_queue

        user = _make_user()
        cb = _make_callback()
        cb.message.photo = True
        state = AsyncMock()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_region_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await change_queue(cb, state, AsyncMock())

        state.set_state.assert_awaited_once()
        cb.message.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# menu/settings.py
# ---------------------------------------------------------------------------

class TestMenuSettings:
    async def test_menu_settings_no_user(self):
        from bot.handlers.menu.settings import menu_settings

        cb = _make_callback()
        with patch("bot.handlers.menu.settings.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await menu_settings(cb, AsyncMock())

        cb.answer.assert_awaited_once()

    async def test_menu_settings_photo(self):
        from bot.handlers.menu.settings import menu_settings

        user = _make_user()
        cb = _make_callback()
        cb.message.photo = True

        with (
            patch("bot.handlers.menu.settings.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.settings.app_settings") as ms,
            patch("bot.handlers.menu.settings.format_live_status_message", return_value="text"),
            patch("bot.handlers.menu.settings.get_settings_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.settings.safe_delete", AsyncMock()),
        ):
            ms.is_admin.return_value = False
            await menu_settings(cb, AsyncMock())

        cb.message.answer.assert_awaited_once()

    async def test_menu_settings_edit_success(self):
        from bot.handlers.menu.settings import menu_settings

        user = _make_user()
        cb = _make_callback()
        cb.message.photo = None

        with (
            patch("bot.handlers.menu.settings.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.settings.app_settings") as ms,
            patch("bot.handlers.menu.settings.format_live_status_message", return_value="text"),
            patch("bot.handlers.menu.settings.get_settings_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.settings.safe_edit_text", AsyncMock(return_value=True)),
        ):
            ms.is_admin.return_value = True
            await menu_settings(cb, AsyncMock())

        cb.message.answer.assert_not_awaited()

    async def test_menu_settings_edit_fails(self):
        from bot.handlers.menu.settings import menu_settings

        user = _make_user()
        cb = _make_callback()
        cb.message.photo = None

        with (
            patch("bot.handlers.menu.settings.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.settings.app_settings") as ms,
            patch("bot.handlers.menu.settings.format_live_status_message", return_value="text"),
            patch("bot.handlers.menu.settings.get_settings_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.settings.safe_edit_text", AsyncMock(return_value=False)),
        ):
            ms.is_admin.return_value = False
            await menu_settings(cb, AsyncMock())

        cb.message.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# menu/stats.py
# ---------------------------------------------------------------------------

class TestMenuStats:
    async def test_menu_stats_no_user(self):
        from bot.handlers.menu.stats import menu_stats

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()),
        ):
            await menu_stats(cb, AsyncMock())

        cb.answer.assert_awaited_once()

    async def test_menu_stats_with_user(self):
        from bot.handlers.menu.stats import menu_stats

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
        ):
            await menu_stats(cb, AsyncMock())

        mock_send.assert_awaited_once()

    async def test_stats_week_no_user(self):
        from bot.handlers.menu.stats import stats_week

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()),
        ):
            await stats_week(cb, AsyncMock())

    async def test_stats_week_no_outages(self):
        from bot.handlers.menu.stats import stats_week

        user = _make_user(id=10)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.get_power_history_week", AsyncMock(return_value=[])),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
        ):
            await stats_week(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "не зафіксовано" in text

    async def test_stats_week_with_outages(self):
        from bot.handlers.menu.stats import stats_week

        user = _make_user(id=10)
        off1 = SimpleNamespace(event_type="off", duration_seconds=3600)
        off2 = SimpleNamespace(event_type="off", duration_seconds=1800)
        on1 = SimpleNamespace(event_type="on", duration_seconds=None)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.get_power_history_week", AsyncMock(return_value=[off1, off2, on1])),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
        ):
            await stats_week(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "2" in text  # 2 outages

    async def test_stats_device_no_user(self):
        from bot.handlers.menu.stats import stats_device

        cb = _make_callback()
        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()),
        ):
            await stats_device(cb, AsyncMock())

    async def test_stats_device_no_router_ip(self):
        from bot.handlers.menu.stats import stats_device

        user = _make_user(router_ip=None)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
        ):
            await stats_device(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "не налаштовано" in text

    async def test_stats_device_state_on(self):
        from bot.handlers.menu.stats import stats_device

        pt = SimpleNamespace(power_state="on", power_changed_at=None)
        user = _make_user(router_ip="1.2.3.4", power_tracking=pt)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.stats.app_settings") as ms,
        ):
            from zoneinfo import ZoneInfo
            ms.timezone = ZoneInfo("Europe/Kyiv")
            await stats_device(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "Світло є" in text

    async def test_stats_device_state_off_with_timestamp(self):
        from bot.handlers.menu.stats import stats_device

        changed = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        pt = SimpleNamespace(power_state="off", power_changed_at=changed)
        user = _make_user(router_ip="1.2.3.4", power_tracking=pt)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.stats.app_settings") as ms,
        ):
            from zoneinfo import ZoneInfo
            ms.timezone = ZoneInfo("Europe/Kyiv")
            await stats_device(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "Світла немає" in text

    async def test_stats_device_state_unknown(self):
        from bot.handlers.menu.stats import stats_device

        pt = SimpleNamespace(power_state=None, power_changed_at=None)
        user = _make_user(router_ip="1.2.3.4", power_tracking=pt)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.stats.app_settings") as ms,
        ):
            from zoneinfo import ZoneInfo
            ms.timezone = ZoneInfo("Europe/Kyiv")
            await stats_device(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "невідомий" in text

    async def test_stats_device_no_power_tracking(self):
        from bot.handlers.menu.stats import stats_device

        user = _make_user(router_ip="1.2.3.4", power_tracking=None)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.stats.app_settings") as ms,
        ):
            from zoneinfo import ZoneInfo
            ms.timezone = ZoneInfo("Europe/Kyiv")
            await stats_device(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "невідомий" in text

    async def test_stats_device_naive_datetime(self):
        from bot.handlers.menu.stats import stats_device

        # naive datetime (no tzinfo)
        changed = datetime(2024, 1, 15, 10, 30)
        pt = SimpleNamespace(power_state="on", power_changed_at=changed)
        user = _make_user(router_ip="5.6.7.8", power_tracking=pt)
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.stats.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.stats.safe_edit_or_resend", AsyncMock()) as mock_send,
            patch("bot.handlers.menu.stats.get_statistics_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.stats.app_settings") as ms,
        ):
            from zoneinfo import ZoneInfo
            ms.timezone = ZoneInfo("Europe/Kyiv")
            await stats_device(cb, AsyncMock())

        text = mock_send.call_args[0][1]
        assert "Світло є" in text


# ---------------------------------------------------------------------------
# menu/timer.py
# ---------------------------------------------------------------------------

class TestMenuTimer:
    async def test_menu_timer_no_user(self):
        from bot.handlers.menu.timer import menu_timer

        cb = _make_callback()
        with patch("bot.handlers.menu.timer.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await menu_timer(cb, AsyncMock())

        cb.answer.assert_awaited_with("❌ Спочатку запустіть бота")

    async def test_menu_timer_no_data(self):
        from bot.handlers.menu.timer import menu_timer

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.timer.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.timer.fetch_schedule_data", AsyncMock(return_value=None)),
        ):
            await menu_timer(cb, AsyncMock())

        cb.answer.assert_awaited_with("⚠️ Дані тимчасово недоступні")

    async def test_menu_timer_with_data(self):
        from bot.handlers.menu.timer import menu_timer

        user = _make_user()
        cb = _make_callback()

        with (
            patch("bot.handlers.menu.timer.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.timer.fetch_schedule_data", AsyncMock(return_value={"data": True})),
            patch("bot.handlers.menu.timer.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.timer.find_next_event", return_value=None),
            patch("bot.handlers.menu.timer.format_timer_popup", return_value="⏰ Timer text"),
        ):
            await menu_timer(cb, AsyncMock())

        cb.answer.assert_awaited_with("⏰ Timer text", show_alert=True)

# ---------------------------------------------------------------------------
# settings/channel.py
# ---------------------------------------------------------------------------

class TestSettingsChannel:
    async def test_settings_channel_no_user(self):
        from bot.handlers.settings.channel import settings_channel

        cb = _make_callback()
        with patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await settings_channel(cb, AsyncMock())

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()

    async def test_settings_channel_no_channel_config(self):
        from bot.handlers.settings.channel import settings_channel

        user = _make_user(channel_config=None)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.channel.get_channel_menu_keyboard", return_value=MagicMock()),
        ):
            await settings_channel(cb, AsyncMock())

        cb.message.edit_text.assert_awaited_once()

    async def test_settings_channel_with_active_channel(self):
        from bot.handlers.settings.channel import settings_channel

        cc = _make_channel_config(channel_id=-100, channel_status="active", channel_title="My Channel")
        user = _make_user(channel_config=cc)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.channel.get_channel_menu_keyboard", return_value=MagicMock()),
        ):
            await settings_channel(cb, AsyncMock())

        call_text = cb.message.edit_text.call_args[0][0]
        assert "My Channel" in call_text
        assert "✅" in call_text

    async def test_settings_channel_blocked(self):
        from bot.handlers.settings.channel import settings_channel

        cc = _make_channel_config(channel_id=-100, channel_status="blocked", channel_title=None)
        user = _make_user(channel_config=cc)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.channel.get_channel_menu_keyboard", return_value=MagicMock()),
        ):
            await settings_channel(cb, AsyncMock())

        call_text = cb.message.edit_text.call_args[0][0]
        assert "заблоковано" in call_text

    async def test_channel_reconnect_no_user(self):
        from bot.handlers.settings.channel import channel_reconnect

        cb = _make_callback()
        with patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await channel_reconnect(cb, AsyncMock())

        cb.answer.assert_awaited_once()

    async def test_channel_reconnect_with_user_and_config(self):
        from bot.handlers.settings.channel import channel_reconnect

        cc = _make_channel_config(channel_status="blocked", channel_guard_warnings=3)
        user = _make_user(channel_config=cc)
        cb = _make_callback()

        with patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await channel_reconnect(cb, AsyncMock())

        assert cc.channel_status == "active"
        assert cc.channel_guard_warnings == 0

    async def test_channel_reconnect_no_channel_config(self):
        from bot.handlers.settings.channel import channel_reconnect

        user = _make_user(channel_config=None)
        cb = _make_callback()

        with patch("bot.handlers.settings.channel.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await channel_reconnect(cb, AsyncMock())

        cb.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# settings/cleanup.py
# ---------------------------------------------------------------------------

class TestSettingsCleanup:
    async def test_settings_cleanup_no_user(self):
        from bot.handlers.settings.cleanup import settings_cleanup

        cb = _make_callback()
        with patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await settings_cleanup(cb, AsyncMock())

        cb.message.edit_text.assert_not_awaited()

    async def test_settings_cleanup_no_notification_settings(self):
        from bot.handlers.settings.cleanup import settings_cleanup

        user = _make_user(notification_settings=None)
        cb = _make_callback()

        with patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await settings_cleanup(cb, AsyncMock())

        cb.message.edit_text.assert_not_awaited()

    async def test_settings_cleanup_with_settings(self):
        from bot.handlers.settings.cleanup import settings_cleanup

        ns = _make_notification_settings(auto_delete_commands=True, auto_delete_bot_messages=False)
        user = _make_user(notification_settings=ns)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.cleanup.get_cleanup_keyboard", return_value=MagicMock()),
        ):
            await settings_cleanup(cb, AsyncMock())

        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "увімкнено" in text

    async def test_cleanup_toggle_commands_no_user(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_commands

        cb = _make_callback()
        with patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await cleanup_toggle_commands(cb, AsyncMock())

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()

    async def test_cleanup_toggle_commands_no_notification_settings(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_commands

        user = _make_user(notification_settings=None)
        cb = _make_callback()

        with patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await cleanup_toggle_commands(cb, AsyncMock())

        cb.message.edit_text.assert_not_awaited()

    async def test_cleanup_toggle_commands_enable(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_commands

        ns = _make_notification_settings(auto_delete_commands=False, auto_delete_bot_messages=True)
        user = _make_user(notification_settings=ns)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.cleanup.get_cleanup_keyboard", return_value=MagicMock()),
        ):
            await cleanup_toggle_commands(cb, AsyncMock())

        assert ns.auto_delete_commands is True
        answer_text = cb.answer.call_args[0][0]
        assert "будуть видалятись" in answer_text

    async def test_cleanup_toggle_commands_disable(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_commands

        ns = _make_notification_settings(auto_delete_commands=True, auto_delete_bot_messages=False)
        user = _make_user(notification_settings=ns)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.cleanup.get_cleanup_keyboard", return_value=MagicMock()),
        ):
            await cleanup_toggle_commands(cb, AsyncMock())

        assert ns.auto_delete_commands is False

    async def test_cleanup_toggle_messages_no_user(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_messages

        cb = _make_callback()
        with patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await cleanup_toggle_messages(cb, AsyncMock())

        cb.message.edit_text.assert_not_awaited()

    async def test_cleanup_toggle_messages_enable(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_messages

        ns = _make_notification_settings(auto_delete_commands=True, auto_delete_bot_messages=False)
        user = _make_user(notification_settings=ns)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.cleanup.get_cleanup_keyboard", return_value=MagicMock()),
        ):
            await cleanup_toggle_messages(cb, AsyncMock())

        assert ns.auto_delete_bot_messages is True
        answer_text = cb.answer.call_args[0][0]
        assert "120" in answer_text

    async def test_cleanup_toggle_messages_disable(self):
        from bot.handlers.settings.cleanup import cleanup_toggle_messages

        ns = _make_notification_settings(auto_delete_commands=False, auto_delete_bot_messages=True)
        user = _make_user(notification_settings=ns)
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.cleanup.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.cleanup.get_cleanup_keyboard", return_value=MagicMock()),
        ):
            await cleanup_toggle_messages(cb, AsyncMock())

        assert ns.auto_delete_bot_messages is False


# ---------------------------------------------------------------------------
# settings/data.py
# ---------------------------------------------------------------------------

class TestSettingsData:
    async def test_settings_delete_data(self):
        from bot.handlers.settings.data import settings_delete_data

        cb = _make_callback()
        with patch("bot.handlers.settings.data.get_delete_data_confirm_keyboard", return_value=MagicMock()):
            await settings_delete_data(cb)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_delete_data_step2(self):
        from bot.handlers.settings.data import delete_data_step2

        cb = _make_callback()
        with patch("bot.handlers.settings.data.get_delete_data_final_keyboard", return_value=MagicMock()):
            await delete_data_step2(cb)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_confirm_delete_data(self):
        from bot.handlers.settings.data import confirm_delete_data

        cb = _make_callback(user_id=42)
        with patch("bot.handlers.settings.data.delete_user_data", AsyncMock()) as mock_delete:
            await confirm_delete_data(cb, AsyncMock())

        mock_delete.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_settings_deactivate(self):
        from bot.handlers.settings.data import settings_deactivate

        cb = _make_callback()
        with patch("bot.handlers.settings.data.get_deactivate_confirm_keyboard", return_value=MagicMock()):
            await settings_deactivate(cb)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_confirm_deactivate(self):
        from bot.handlers.settings.data import confirm_deactivate

        cb = _make_callback(user_id=42)
        with patch("bot.handlers.settings.data.deactivate_user", AsyncMock()) as mock_deactivate:
            await confirm_deactivate(cb, AsyncMock())

        mock_deactivate.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "деактивовано" in text


# ---------------------------------------------------------------------------
# settings/region.py
# ---------------------------------------------------------------------------

class TestSettingsRegion:
    async def test_settings_region_no_user(self):
        from bot.handlers.settings.region import settings_region

        cb = _make_callback()
        with patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await settings_region(cb, AsyncMock())

        cb.message.edit_text.assert_not_awaited()

    async def test_settings_region_known_region(self):
        from bot.handlers.settings.region import settings_region

        user = _make_user(region="kyiv", queue="2.1")
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.region.REGIONS") as mock_regions,
        ):
            mock_region_obj = MagicMock()
            mock_region_obj.name = "Київ"
            mock_regions.get.return_value = mock_region_obj
            await settings_region(cb, AsyncMock())

        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "Київ" in text

    async def test_settings_region_unknown_region(self):
        from bot.handlers.settings.region import settings_region

        user = _make_user(region="unknown_reg", queue="1.1")
        cb = _make_callback()

        with (
            patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.region.REGIONS") as mock_regions,
        ):
            mock_regions.get.return_value = None
            await settings_region(cb, AsyncMock())

        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "unknown_reg" in text

    async def test_settings_region_confirm(self):
        from bot.handlers.settings.region import settings_region_confirm

        user = _make_user(region="kyiv")
        cb = _make_callback()
        state = AsyncMock()

        with (
            patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.region.get_region_keyboard", return_value=MagicMock()),
        ):
            await settings_region_confirm(cb, state, AsyncMock())

        state.set_state.assert_awaited_once()
        state.update_data.assert_awaited_once_with(mode="edit")
        cb.message.edit_text.assert_awaited_once()

    async def test_settings_region_confirm_no_user(self):
        from bot.handlers.settings.region import settings_region_confirm

        cb = _make_callback()
        state = AsyncMock()

        with (
            patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.region.get_region_keyboard", return_value=MagicMock()),
        ):
            await settings_region_confirm(cb, state, AsyncMock())

        state.set_state.assert_awaited_once()

    async def test_back_to_settings_no_user(self):
        from bot.handlers.settings.region import back_to_settings

        cb = _make_callback()
        with patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await back_to_settings(cb, AsyncMock())

        cb.message.edit_text.assert_not_awaited()

    async def test_back_to_settings_with_user(self):
        from bot.handlers.settings.region import back_to_settings

        user = _make_user()
        cb = _make_callback(user_id=42)

        with (
            patch("bot.handlers.settings.region.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.region.app_settings") as ms,
            patch("bot.handlers.settings.region.format_live_status_message", return_value="status"),
            patch("bot.handlers.settings.region.get_settings_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = False
            await back_to_settings(cb, AsyncMock())

        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# handlers/__init__.py
# ---------------------------------------------------------------------------

class TestRegisterAllHandlers:
    def test_register_all_handlers(self):
        from aiogram import Dispatcher
        from bot.handlers import register_all_handlers

        dp = MagicMock(spec=Dispatcher)
        dp.include_router = MagicMock()

        register_all_handlers(dp)

        assert dp.include_router.call_count == 7
