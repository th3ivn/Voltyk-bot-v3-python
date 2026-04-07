"""Tests for bot/handlers/settings/ip.py.

Coverage targets (current: 26%):
- settings_ip: user with IP → management screen; without IP → input screen
- ip_change: shows confirm dialog with current IP
- ip_change_confirm: transitions to input screen
- ip_delete_confirm: shows delete confirm dialog
- ip_delete_execute: nulls router_ip, calls deactivate_ping_error_alert
- ip_cancel_to_settings / ip_cancel: return to settings screen
- ip_ping_check: pings IP → green or red result
- ip_input (Message handler): validates IP, saves, pings, shows result
- ip_show: shows current IP as popup alert
- ip_delete (legacy): nulls router_ip, shows deleted screen
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    router_ip: str | None = None,
    telegram_id: str = "111",
    **kwargs,
) -> SimpleNamespace:
    return SimpleNamespace(
        telegram_id=telegram_id,
        is_active=True,
        region="kyiv",
        queue="1.1",
        router_ip=router_ip,
        power_tracking=None,
        notification_settings=SimpleNamespace(
            notify_schedule_changes=True,
            notify_remind_off=True,
            notify_fact_off=True,
            notify_remind_on=True,
            notify_fact_on=True,
            remind_15m=True,
            remind_30m=False,
            remind_1h=False,
        ),
        channel_config=None,
        **kwargs,
    )


def _make_callback(user_id: int = 111, data: str = "") -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id, username="tester")
    cb.data = data
    cb.answer = AsyncMock()
    cb.bot = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.chat = SimpleNamespace(id=user_id)
    return cb


def _make_message(user_id: int = 111, text: str = "192.168.1.1") -> MagicMock:
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=user_id, username="tester")
    msg.text = text
    msg.reply = AsyncMock()
    msg.answer = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    msg.bot = AsyncMock()
    return msg


def _make_state() -> AsyncMock:
    state = AsyncMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# settings_ip
# ---------------------------------------------------------------------------


class TestSettingsIp:
    async def test_user_without_ip_shows_input_screen(self):
        """User with no router_ip → instruction + IP input screen."""
        from bot.handlers.settings.ip import settings_ip

        cb = _make_callback(data="settings_ip")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(router_ip=None)

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_monitoring_keyboard_no_ip", return_value=MagicMock()),
        ):
            await settings_ip(cb, state, session)

        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()
        mock_edit.assert_awaited_once()
        state.set_state.assert_awaited_once()

    async def test_user_with_ip_shows_management_screen(self):
        """User with router_ip → management screen with live ping."""
        from bot.handlers.settings.ip import settings_ip

        cb = _make_callback(data="settings_ip")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(router_ip="192.168.1.1")

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.check_router_http", AsyncMock(return_value=True)),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_management_keyboard", return_value=MagicMock()),
        ):
            await settings_ip(cb, state, session)

        cb.answer.assert_awaited_once()
        # safe_edit_text called twice: loading screen + result
        assert mock_edit.await_count == 2

    async def test_user_not_found_shows_error(self):
        """No user in DB → edit_text with error message."""
        from bot.handlers.settings.ip import settings_ip

        cb = _make_callback(data="settings_ip")
        state = _make_state()
        session = AsyncMock()

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await settings_ip(cb, state, session)

        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "/start" in args[0]


# ---------------------------------------------------------------------------
# ip_change
# ---------------------------------------------------------------------------


class TestIpChange:
    async def test_shows_confirm_dialog_with_current_ip(self):
        from bot.handlers.settings.ip import ip_change

        cb = _make_callback(data="ip_change")
        session = AsyncMock()
        user = _make_user(router_ip="10.0.0.1")

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.get_ip_change_confirm_keyboard", return_value=MagicMock()),
        ):
            await ip_change(cb, session)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "10.0.0.1" in args[0]

    async def test_user_not_found_shows_error(self):
        from bot.handlers.settings.ip import ip_change

        cb = _make_callback(data="ip_change")
        session = AsyncMock()

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await ip_change(cb, session)

        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "/start" in args[0]


# ---------------------------------------------------------------------------
# ip_change_confirm
# ---------------------------------------------------------------------------


class TestIpChangeConfirm:
    async def test_shows_input_screen(self):
        from bot.handlers.settings.ip import ip_change_confirm

        cb = _make_callback(data="ip_change_confirm")
        state = _make_state()

        with (
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_monitoring_keyboard_no_ip", return_value=MagicMock()),
        ):
            await ip_change_confirm(cb, state)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()
        state.set_state.assert_awaited_once()


# ---------------------------------------------------------------------------
# ip_delete_confirm
# ---------------------------------------------------------------------------


class TestIpDeleteConfirm:
    async def test_shows_delete_confirm_with_ip(self):
        from bot.handlers.settings.ip import ip_delete_confirm

        cb = _make_callback(data="ip_delete_confirm")
        session = AsyncMock()
        user = _make_user(router_ip="192.168.0.1")

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.get_ip_delete_confirm_keyboard", return_value=MagicMock()),
        ):
            await ip_delete_confirm(cb, session)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "192.168.0.1" in args[0]

    async def test_user_not_found_shows_error(self):
        from bot.handlers.settings.ip import ip_delete_confirm

        cb = _make_callback(data="ip_delete_confirm")
        session = AsyncMock()

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await ip_delete_confirm(cb, session)

        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "/start" in args[0]


# ---------------------------------------------------------------------------
# ip_delete_execute
# ---------------------------------------------------------------------------


class TestIpDeleteExecute:
    async def test_nulls_router_ip_and_shows_deleted(self):
        from bot.handlers.settings.ip import ip_delete_execute

        cb = _make_callback(data="ip_delete_execute")
        session = AsyncMock()
        session.flush = AsyncMock()
        user = _make_user(router_ip="192.168.1.1", telegram_id="111")

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.deactivate_ping_error_alert", AsyncMock()),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_deleted_keyboard", return_value=MagicMock()),
        ):
            await ip_delete_execute(cb, session)

        assert user.router_ip is None
        session.flush.assert_awaited_once()
        mock_edit.assert_awaited_once()

    async def test_no_user_still_shows_deleted_message(self):
        from bot.handlers.settings.ip import ip_delete_execute

        cb = _make_callback(data="ip_delete_execute")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_deleted_keyboard", return_value=MagicMock()),
        ):
            await ip_delete_execute(cb, session)

        mock_edit.assert_awaited_once()


# ---------------------------------------------------------------------------
# ip_ping_check
# ---------------------------------------------------------------------------


class TestIpPingCheck:
    async def test_ping_success_shows_green(self):
        from bot.handlers.settings.ip import ip_ping_check

        cb = _make_callback(data="ip_ping_check")
        session = AsyncMock()
        user = _make_user(router_ip="192.168.1.1")

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.check_router_http", AsyncMock(return_value=True)),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_ping_result_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.ip.app_settings") as mock_settings,
        ):
            mock_settings.SUPPORT_CHANNEL_URL = None
            await ip_ping_check(cb, session)

        cb.answer.assert_awaited_once()
        # Two calls: loading screen + result
        assert mock_edit.await_count == 2
        last_call_text = mock_edit.call_args_list[-1][0][1]
        assert "успішно" in last_call_text

    async def test_ping_fail_shows_red(self):
        from bot.handlers.settings.ip import ip_ping_check

        cb = _make_callback(data="ip_ping_check")
        session = AsyncMock()
        user = _make_user(router_ip="192.168.1.1")

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.check_router_http", AsyncMock(return_value=False)),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.ip.get_ip_ping_fail_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.ip.app_settings") as mock_settings,
        ):
            mock_settings.SUPPORT_CHANNEL_URL = None
            await ip_ping_check(cb, session)

        last_call_text = mock_edit.call_args_list[-1][0][1]
        assert "не пройшов" in last_call_text

    async def test_no_user_or_ip_shows_error(self):
        from bot.handlers.settings.ip import ip_ping_check

        cb = _make_callback(data="ip_ping_check")
        session = AsyncMock()

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await ip_ping_check(cb, session)

        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# ip_input (Message handler)
# ---------------------------------------------------------------------------


class TestIpInput:
    async def test_valid_ip_ping_ok_shows_success(self):
        from bot.handlers.settings.ip import ip_input

        msg = _make_message(text="192.168.1.1")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(router_ip=None)
        session.flush = AsyncMock()

        with (
            patch("bot.handlers.settings.ip.is_valid_ip_or_domain", return_value={"valid": True, "address": "192.168.1.1"}),
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.check_router_http", AsyncMock(return_value=True)),
            patch("bot.handlers.settings.ip.get_ip_saved_success_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.ip.app_settings") as mock_settings,
        ):
            mock_settings.SUPPORT_CHANNEL_URL = None
            await ip_input(msg, state, session)

        assert user.router_ip == "192.168.1.1"
        session.flush.assert_awaited_once()
        state.clear.assert_awaited_once()
        sent_msg = msg.answer.return_value
        sent_msg.edit_text.assert_awaited_once()
        args, _ = sent_msg.edit_text.call_args
        assert "збережено" in args[0]
        assert "успішно" in args[0]

    async def test_valid_ip_ping_fail_shows_warning(self):
        from bot.handlers.settings.ip import ip_input

        msg = _make_message(text="8.8.8.8")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(router_ip=None)
        session.flush = AsyncMock()

        with (
            patch("bot.handlers.settings.ip.is_valid_ip_or_domain", return_value={"valid": True, "address": "8.8.8.8"}),
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.check_router_http", AsyncMock(return_value=False)),
            patch("bot.handlers.settings.ip.upsert_ping_error_alert", AsyncMock()),
            patch("bot.handlers.settings.ip.get_ip_saved_fail_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.ip.app_settings") as mock_settings,
        ):
            mock_settings.SUPPORT_CHANNEL_URL = None
            await ip_input(msg, state, session)

        assert user.router_ip == "8.8.8.8"
        sent_msg = msg.answer.return_value
        sent_msg.edit_text.assert_awaited_once()
        args, _ = sent_msg.edit_text.call_args
        assert "збережено" in args[0]
        assert "не проходить" in args[0]

    async def test_invalid_ip_shows_error(self):
        from bot.handlers.settings.ip import ip_input

        msg = _make_message(text="not-valid!!")
        state = _make_state()
        session = AsyncMock()

        with patch(
            "bot.handlers.settings.ip.is_valid_ip_or_domain",
            return_value={"valid": False, "error": "Невірний формат"},
        ):
            await ip_input(msg, state, session)

        msg.reply.assert_awaited_once()
        args, _ = msg.reply.call_args
        assert "Невірний формат" in args[0]
        state.clear.assert_not_awaited()

    async def test_no_text_shows_error(self):
        from bot.handlers.settings.ip import ip_input

        msg = _make_message()
        msg.text = None
        state = _make_state()
        session = AsyncMock()

        await ip_input(msg, state, session)

        msg.reply.assert_awaited_once()


# ---------------------------------------------------------------------------
# ip_show
# ---------------------------------------------------------------------------


class TestIpShow:
    async def test_shows_ip_in_alert(self):
        from bot.handlers.settings.ip import ip_show

        cb = _make_callback(data="ip_show")
        session = AsyncMock()
        user = _make_user(router_ip="192.168.1.100")

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await ip_show(cb, session)

        cb.answer.assert_awaited_once()
        args, kwargs = cb.answer.call_args
        assert "192.168.1.100" in args[0]
        assert kwargs.get("show_alert") is True

    async def test_shows_ip_with_power_state(self):
        from bot.handlers.settings.ip import ip_show

        cb = _make_callback(data="ip_show")
        session = AsyncMock()
        user = _make_user(router_ip="10.0.0.1")
        user.power_tracking = SimpleNamespace(power_state="on")

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await ip_show(cb, session)

        args, _ = cb.answer.call_args
        assert "Онлайн" in args[0]

    async def test_no_ip_shows_not_configured(self):
        from bot.handlers.settings.ip import ip_show

        cb = _make_callback(data="ip_show")
        session = AsyncMock()
        user = _make_user(router_ip=None)

        with patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await ip_show(cb, session)

        cb.answer.assert_awaited_once()
        args, _ = cb.answer.call_args
        assert "не налаштовано" in args[0]


# ---------------------------------------------------------------------------
# ip_cancel_to_settings / ip_cancel
# ---------------------------------------------------------------------------


class TestIpCancel:
    async def test_cancel_to_settings_returns_to_settings(self):
        from bot.handlers.settings.ip import ip_cancel_to_settings

        cb = _make_callback(data="ip_cancel_to_settings")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.format_live_status_message", return_value="status"),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.ip.get_settings_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.ip.app_settings") as mock_settings,
        ):
            mock_settings.is_admin.return_value = False
            await ip_cancel_to_settings(cb, state, session)

        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()

    async def test_ip_cancel_alias_works(self):
        from bot.handlers.settings.ip import ip_cancel

        cb = _make_callback(data="ip_cancel")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.settings.ip.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.ip.format_live_status_message", return_value="status"),
            patch("bot.handlers.settings.ip.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.ip.get_settings_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.ip.app_settings") as mock_settings,
        ):
            mock_settings.is_admin.return_value = False
            await ip_cancel(cb, state, session)

        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()
