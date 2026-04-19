"""Tests for bot/handlers/settings/alerts.py.

Coverage targets (current: 19%):
- settings_alerts: with channel (shows select menu), without channel (shows notification menu)
- notif_select_bot: shows bot-specific notification settings
- notif_select_channel: shows channel-specific notification settings
- notif_toggle_schedule: toggles notify_schedule_changes flag
- notif_reminders: shows reminder settings
- notif_toggle (fact_off): toggles fact_off + syncs fact_on
- notif_toggle (fact_on): toggles fact_on + syncs fact_off
- notif_toggle (remind_off / remind_on): toggles individual fields
- notif_time: toggles 15m / 30m / 1h reminder flags; invalid value ignored
- notif_targets: shows target selector keyboard
- notif_target_type: switches target between bot / channel / ip
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ns(**kwargs) -> SimpleNamespace:
    defaults = dict(
        notify_schedule_changes=True,
        notify_remind_off=True,
        notify_fact_off=True,
        notify_remind_on=True,
        notify_fact_on=True,
        notify_schedule_target=None,
        notify_remind_target=None,
        notify_power_target=None,
        remind_15m=True,
        remind_30m=False,
        remind_1h=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_cc(**kwargs) -> SimpleNamespace:
    defaults = dict(
        channel_id=-1001111111,
        ch_notify_schedule=True,
        ch_notify_remind_off=False,
        ch_notify_fact_off=False,
        ch_notify_remind_on=False,
        ch_notify_fact_on=False,
        ch_remind_15m=True,
        ch_remind_30m=False,
        ch_remind_1h=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_user(with_channel: bool = False, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        telegram_id="111",
        router_ip="192.168.1.1",
        notification_settings=_make_ns(),
        channel_config=_make_cc() if with_channel else None,
        **kwargs,
    )


def _make_callback(user_id: int = 111, data: str = "") -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id)
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


# ---------------------------------------------------------------------------
# settings_alerts
# ---------------------------------------------------------------------------


class TestSettingsAlerts:
    async def test_with_channel_shows_select_keyboard(self):
        """User with channel → shows notification type selector (bot vs channel)."""
        from bot.handlers.settings.alerts import settings_alerts

        cb = _make_callback(data="settings_alerts")
        session = AsyncMock()
        user = _make_user(with_channel=True)

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.alerts.get_notification_select_keyboard", return_value=MagicMock()),
        ):
            await settings_alerts(cb, session)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()

    async def test_without_channel_shows_notification_menu(self):
        """User without channel → shows notification settings directly."""
        from bot.handlers.settings.alerts import settings_alerts

        cb = _make_callback(data="settings_alerts")
        session = AsyncMock()
        user = _make_user(with_channel=False)

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="ns text"),
        ):
            await settings_alerts(cb, session)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()
        _, kwargs = mock_edit.call_args
        assert kwargs.get("text") == "ns text" or mock_edit.call_args[0][1] == "ns text"

    async def test_user_not_found_returns_silently(self):
        """No user in DB → returns without editing message."""
        from bot.handlers.settings.alerts import settings_alerts

        cb = _make_callback(data="settings_alerts")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await settings_alerts(cb, session)

        mock_edit.assert_not_awaited()

    async def test_no_notification_settings_returns_silently(self):
        """User without notification_settings → returns without editing."""
        from bot.handlers.settings.alerts import settings_alerts

        cb = _make_callback(data="settings_alerts")
        session = AsyncMock()
        user = _make_user(with_channel=False)
        user.notification_settings = None

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await settings_alerts(cb, session)

        mock_edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# notif_select_bot
# ---------------------------------------------------------------------------


class TestNotifSelectBot:
    async def test_shows_bot_notification_settings(self):
        """notif_select_bot → shows bot-specific notification menu."""
        from bot.handlers.settings.alerts import notif_select_bot

        cb = _make_callback(data="notif_select_bot")
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="bot ns"),
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
        ):
            await notif_select_bot(cb, session)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()

    async def test_no_user_returns_silently(self):
        from bot.handlers.settings.alerts import notif_select_bot

        cb = _make_callback(data="notif_select_bot")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await notif_select_bot(cb, session)

        mock_edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# notif_select_channel
# ---------------------------------------------------------------------------


class TestNotifSelectChannel:
    async def test_shows_channel_notification_settings(self):
        """notif_select_channel → shows channel-specific notification menu."""
        from bot.handlers.settings.alerts import notif_select_channel

        cb = _make_callback(data="notif_select_channel")
        session = AsyncMock()
        user = _make_user(with_channel=True)

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.alerts.build_channel_notification_message", return_value="ch text"),
            patch("bot.handlers.settings.alerts.get_channel_notification_keyboard", return_value=MagicMock()),
        ):
            await notif_select_channel(cb, session)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()

    async def test_no_channel_config_returns_silently(self):
        from bot.handlers.settings.alerts import notif_select_channel

        cb = _make_callback(data="notif_select_channel")
        session = AsyncMock()
        user = _make_user(with_channel=False)

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await notif_select_channel(cb, session)

        mock_edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# notif_toggle_schedule
# ---------------------------------------------------------------------------


class TestNotifToggleSchedule:
    async def test_toggles_schedule_notifications_off(self):
        """notify_schedule_changes True → False after toggle."""
        from bot.handlers.settings.alerts import notif_toggle_schedule

        cb = _make_callback(data="notif_toggle_schedule")
        session = AsyncMock()
        user = _make_user()
        assert user.notification_settings.notify_schedule_changes is True

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="updated"),
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
        ):
            await notif_toggle_schedule(cb, session)

        assert user.notification_settings.notify_schedule_changes is False
        cb.answer.assert_awaited_once()

    async def test_toggles_schedule_notifications_on(self):
        """notify_schedule_changes False → True after toggle."""
        from bot.handlers.settings.alerts import notif_toggle_schedule

        cb = _make_callback(data="notif_toggle_schedule")
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_schedule_changes = False

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="updated"),
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
        ):
            await notif_toggle_schedule(cb, session)

        assert user.notification_settings.notify_schedule_changes is True


# ---------------------------------------------------------------------------
# notif_reminders
# ---------------------------------------------------------------------------


class TestNotifReminders:
    async def test_shows_reminder_settings(self):
        from bot.handlers.settings.alerts import notif_reminders

        cb = _make_callback(data="notif_reminders")
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.alerts.get_notification_reminders_keyboard", return_value=MagicMock()),
        ):
            await notif_reminders(cb, session)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()
        args, _ = mock_edit.call_args
        assert "Нагадування" in args[1]

    async def test_no_user_returns_silently(self):
        from bot.handlers.settings.alerts import notif_reminders

        cb = _make_callback(data="notif_reminders")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await notif_reminders(cb, session)

        mock_edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# notif_toggle (generic toggle handler)
# ---------------------------------------------------------------------------


class TestNotifToggle:
    async def _run_toggle(self, field_suffix: str, user: SimpleNamespace) -> None:
        from bot.handlers.settings.alerts import notif_toggle

        cb = _make_callback(data=f"notif_toggle_{field_suffix}")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="text"),
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
        ):
            await notif_toggle(cb, session)

    async def test_toggle_remind_off(self):
        """notif_toggle_remind_off toggles notify_remind_off."""
        user = _make_user()
        user.notification_settings.notify_remind_off = True
        await self._run_toggle("remind_off", user)
        assert user.notification_settings.notify_remind_off is False

    async def test_toggle_remind_on(self):
        """notif_toggle_remind_on toggles notify_remind_on."""
        user = _make_user()
        user.notification_settings.notify_remind_on = False
        await self._run_toggle("remind_on", user)
        assert user.notification_settings.notify_remind_on is True

    async def test_toggle_fact_off_syncs_fact_on(self):
        """Toggling fact_off also updates fact_on to keep IP-monitoring in sync."""
        user = _make_user()
        user.notification_settings.notify_fact_off = True
        user.notification_settings.notify_fact_on = True
        await self._run_toggle("fact_off", user)
        assert user.notification_settings.notify_fact_off is False
        assert user.notification_settings.notify_fact_on is False

    async def test_toggle_fact_on_syncs_fact_off(self):
        """Toggling fact_on also updates fact_off."""
        user = _make_user()
        user.notification_settings.notify_fact_on = False
        user.notification_settings.notify_fact_off = False
        await self._run_toggle("fact_on", user)
        assert user.notification_settings.notify_fact_on is True
        assert user.notification_settings.notify_fact_off is True

    async def test_unknown_field_does_not_crash(self):
        """Unknown toggle field is a no-op (no attr change, no error)."""
        from bot.handlers.settings.alerts import notif_toggle

        cb = _make_callback(data="notif_toggle_nonexistent")
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="text"),
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
        ):
            await notif_toggle(cb, session)  # must not raise

        cb.answer.assert_awaited_once()

    async def test_no_user_returns_after_answer(self):
        from bot.handlers.settings.alerts import notif_toggle

        cb = _make_callback(data="notif_toggle_remind_off")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await notif_toggle(cb, session)

        mock_edit.assert_not_awaited()
        cb.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# notif_time
# ---------------------------------------------------------------------------


class TestNotifTime:
    async def _run_time_toggle(self, minutes_str: str, user: SimpleNamespace) -> None:
        from bot.handlers.settings.alerts import notif_time

        cb = _make_callback(data=f"notif_time_{minutes_str}")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.build_notification_settings_message", return_value="text"),
            patch("bot.handlers.settings.alerts.get_notification_main_keyboard", return_value=MagicMock()),
        ):
            await notif_time(cb, session)

    async def test_toggle_15m(self):
        user = _make_user()
        user.notification_settings.remind_15m = False
        await self._run_time_toggle("15", user)
        assert user.notification_settings.remind_15m is True

    async def test_toggle_30m(self):
        user = _make_user()
        user.notification_settings.remind_30m = False
        await self._run_time_toggle("30", user)
        assert user.notification_settings.remind_30m is True

    async def test_toggle_1h(self):
        user = _make_user()
        user.notification_settings.remind_1h = False
        await self._run_time_toggle("60", user)
        assert user.notification_settings.remind_1h is True

    async def test_invalid_minutes_returns_early(self):
        """Non-integer suffix → answer and return without DB query."""
        from bot.handlers.settings.alerts import notif_time

        cb = _make_callback(data="notif_time_abc")
        session = AsyncMock()

        with patch(
            "bot.handlers.settings.alerts.get_user_by_telegram_id",
            AsyncMock(),
        ) as mock_get:
            await notif_time(cb, session)

        mock_get.assert_not_awaited()
        cb.answer.assert_awaited_once()

    async def test_no_user_returns_after_answer(self):
        from bot.handlers.settings.alerts import notif_time

        cb = _make_callback(data="notif_time_15")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await notif_time(cb, session)

        mock_edit.assert_not_awaited()
        cb.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# notif_targets
# ---------------------------------------------------------------------------


class TestNotifTargets:
    async def test_shows_targets_keyboard_with_ip(self):
        """User with router_ip → has_ip=True passed to keyboard."""
        from bot.handlers.settings.alerts import notif_targets

        cb = _make_callback(data="notif_targets")
        session = AsyncMock()
        user = _make_user()
        user.router_ip = "192.168.1.1"

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.get_notification_targets_keyboard", return_value=MagicMock()) as mock_kb,
        ):
            await notif_targets(cb, session)

        cb.answer.assert_awaited_once()
        call_kwargs = mock_kb.call_args[1]
        assert call_kwargs.get("has_ip") is True

    async def test_shows_targets_keyboard_without_ip(self):
        """User without router_ip → has_ip=False."""
        from bot.handlers.settings.alerts import notif_targets

        cb = _make_callback(data="notif_targets")
        session = AsyncMock()
        user = _make_user()
        user.router_ip = None

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.get_notification_targets_keyboard", return_value=MagicMock()) as mock_kb,
        ):
            await notif_targets(cb, session)

        call_kwargs = mock_kb.call_args[1]
        assert call_kwargs.get("has_ip") is False


# ---------------------------------------------------------------------------
# notif_target_type
# ---------------------------------------------------------------------------


class TestNotifTargetType:
    async def test_shows_target_selector_for_schedule(self):
        """notif_target_type_schedule → shows selector with current schedule target."""
        from bot.handlers.settings.alerts import notif_target_type

        cb = _make_callback(data="notif_target_type_schedule")
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_schedule_target = "channel"

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch(
                "bot.handlers.settings.alerts.get_notification_target_select_keyboard",
                return_value=MagicMock(),
            ) as mock_kb,
        ):
            await notif_target_type(cb, session)

        cb.answer.assert_awaited_once()
        mock_edit.assert_awaited_once()
        mock_kb.assert_called_once_with("schedule", "channel")

    async def test_no_user_or_ns_returns_silently(self):
        """No user → returns without editing message."""
        from bot.handlers.settings.alerts import notif_target_type

        cb = _make_callback(data="notif_target_type_remind")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await notif_target_type(cb, session)

        mock_edit.assert_not_awaited()


# ---------------------------------------------------------------------------
# notif_target_set
# ---------------------------------------------------------------------------


class TestNotifTargetSet:
    async def test_sets_schedule_target(self):
        """notif_target_set_schedule_channel → sets notify_schedule_target='channel'."""
        from bot.handlers.settings.alerts import notif_target_set

        cb = _make_callback(data="notif_target_set_schedule_channel")
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_schedule_target = "bot"

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_reply_markup", AsyncMock()),
            patch(
                "bot.handlers.settings.alerts.get_notification_target_select_keyboard",
                return_value=MagicMock(),
            ),
        ):
            await notif_target_set(cb, session)

        assert user.notification_settings.notify_schedule_target == "channel"
        cb.answer.assert_awaited_once_with("✅ Збережено")

    async def test_invalid_target_value_returns_early(self):
        """target_value not in allowed set → answer and return without DB change."""
        from bot.handlers.settings.alerts import notif_target_set

        cb = _make_callback(data="notif_target_set_schedule_evil")
        session = AsyncMock()

        with patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock()) as mock_get:
            await notif_target_set(cb, session)

        mock_get.assert_not_awaited()
        cb.answer.assert_awaited_once()

    async def test_malformed_data_no_underscore_returns_early(self):
        """Data without exactly 2 parts after prefix → early return."""
        from bot.handlers.settings.alerts import notif_target_set

        cb = _make_callback(data="notif_target_set_onlyonepart")
        session = AsyncMock()

        with patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock()) as mock_get:
            await notif_target_set(cb, session)

        mock_get.assert_not_awaited()
        cb.answer.assert_awaited_once()

    async def test_no_user_or_ns_returns_early(self):
        """User not found → answer and return."""
        from bot.handlers.settings.alerts import notif_target_set

        cb = _make_callback(data="notif_target_set_power_bot")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.settings.alerts.safe_edit_reply_markup", AsyncMock()) as mock_edit,
        ):
            await notif_target_set(cb, session)

        mock_edit.assert_not_awaited()
        cb.answer.assert_awaited_once()

    async def test_sets_both_target(self):
        """target_value='both' is a valid allowed destination."""
        from bot.handlers.settings.alerts import notif_target_set

        cb = _make_callback(data="notif_target_set_remind_both")
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_remind_target = "bot"

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_reply_markup", AsyncMock()),
            patch(
                "bot.handlers.settings.alerts.get_notification_target_select_keyboard",
                return_value=MagicMock(),
            ),
        ):
            await notif_target_set(cb, session)

        assert user.notification_settings.notify_remind_target == "both"


# ---------------------------------------------------------------------------
# alert_toggle
# ---------------------------------------------------------------------------


class TestAlertToggle:
    async def test_disables_all_when_any_enabled(self):
        """At least one field True → all set to False."""
        from bot.handlers.settings.alerts import alert_toggle

        cb = _make_callback(data="alert_toggle")
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_schedule_changes = True
        user.notification_settings.notify_remind_off = False
        user.notification_settings.notify_fact_off = False

        with patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await alert_toggle(cb, session)

        ns = user.notification_settings
        assert ns.notify_schedule_changes is False
        assert ns.notify_remind_off is False
        assert ns.notify_fact_off is False
        assert ns.notify_remind_on is False
        assert ns.notify_fact_on is False
        cb.answer.assert_awaited_once_with("✅ Збережено")

    async def test_enables_all_when_all_disabled(self):
        """All fields False → all set to True."""
        from bot.handlers.settings.alerts import alert_toggle

        cb = _make_callback(data="alert_toggle")
        session = AsyncMock()
        user = _make_user()
        ns = user.notification_settings
        ns.notify_schedule_changes = False
        ns.notify_remind_off = False
        ns.notify_fact_off = False
        ns.notify_remind_on = False
        ns.notify_fact_on = False

        with patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await alert_toggle(cb, session)

        assert ns.notify_schedule_changes is True
        assert ns.notify_remind_off is True
        assert ns.notify_fact_off is True

    async def test_no_user_still_answers(self):
        """No user → answer is still called (no crash)."""
        from bot.handlers.settings.alerts import alert_toggle

        cb = _make_callback(data="alert_toggle")
        session = AsyncMock()

        with patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await alert_toggle(cb, session)

        cb.answer.assert_awaited_once_with("✅ Збережено")


# ---------------------------------------------------------------------------
# ch_notif_handler
# ---------------------------------------------------------------------------


def _make_cc_with_all(**overrides) -> SimpleNamespace:
    defaults = dict(
        ch_notify_schedule=True,
        ch_notify_remind_off=False,
        ch_notify_fact_off=False,
        ch_notify_remind_on=False,
        ch_notify_fact_on=False,
        ch_remind_15m=False,
        ch_remind_30m=False,
        ch_remind_1h=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestChNotifHandler:
    async def _run(self, action: str, user: SimpleNamespace) -> None:
        from bot.handlers.settings.alerts import ch_notif_handler

        cb = _make_callback(data=f"ch_notif_{action}")
        session = AsyncMock()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()),
            patch("bot.handlers.settings.alerts.build_channel_notification_message", return_value="text"),
            patch("bot.handlers.settings.alerts.get_channel_notification_keyboard", return_value=MagicMock()),
        ):
            await ch_notif_handler(cb, session)

        return cb

    async def test_toggle_schedule(self):
        """ch_notif_toggle_schedule → flips ch_notify_schedule."""
        user = _make_user(with_channel=True)
        user.channel_config = _make_cc_with_all(ch_notify_schedule=True)

        await self._run("toggle_schedule", user)

        assert user.channel_config.ch_notify_schedule is False

    async def test_toggle_fact(self):
        """ch_notif_toggle_fact → flips both ch_notify_fact_off and ch_notify_fact_on."""
        user = _make_user(with_channel=True)
        user.channel_config = _make_cc_with_all(ch_notify_fact_off=False, ch_notify_fact_on=False)

        await self._run("toggle_fact", user)

        assert user.channel_config.ch_notify_fact_off is True
        assert user.channel_config.ch_notify_fact_on is True

    async def test_time_15m(self):
        """ch_notif_time_15 → toggles ch_remind_15m."""
        user = _make_user(with_channel=True)
        user.channel_config = _make_cc_with_all(ch_remind_15m=False)

        await self._run("time_15", user)

        assert user.channel_config.ch_remind_15m is True

    async def test_time_30m(self):
        """ch_notif_time_30 → toggles ch_remind_30m."""
        user = _make_user(with_channel=True)
        user.channel_config = _make_cc_with_all(ch_remind_30m=False)

        await self._run("time_30", user)

        assert user.channel_config.ch_remind_30m is True

    async def test_time_60m(self):
        """ch_notif_time_60 → toggles ch_remind_1h."""
        user = _make_user(with_channel=True)
        user.channel_config = _make_cc_with_all(ch_remind_1h=False)

        await self._run("time_60", user)

        assert user.channel_config.ch_remind_1h is True

    async def test_time_invalid_suffix_returns_early(self):
        """Non-integer time suffix → answer and return without editing."""
        from bot.handlers.settings.alerts import ch_notif_handler

        cb = _make_callback(data="ch_notif_time_abc")
        session = AsyncMock()
        user = _make_user(with_channel=True)
        user.channel_config = _make_cc_with_all()

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
            patch("bot.handlers.settings.alerts.build_channel_notification_message", return_value="text"),
            patch("bot.handlers.settings.alerts.get_channel_notification_keyboard", return_value=MagicMock()),
        ):
            await ch_notif_handler(cb, session)

        mock_edit.assert_not_awaited()
        cb.answer.assert_awaited_once()

    async def test_no_channel_config_returns_early(self):
        """User without channel_config → early return."""
        from bot.handlers.settings.alerts import ch_notif_handler

        cb = _make_callback(data="ch_notif_toggle_schedule")
        session = AsyncMock()
        user = _make_user(with_channel=False)

        with (
            patch("bot.handlers.settings.alerts.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.settings.alerts.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await ch_notif_handler(cb, session)

        mock_edit.assert_not_awaited()
        cb.answer.assert_awaited_once()
