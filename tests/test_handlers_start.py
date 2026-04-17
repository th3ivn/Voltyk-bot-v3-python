"""Tests for bot/handlers/start.py.

Coverage targets:
- cmd_start: new user, existing active user, inactive user, registration disabled
- restore_profile: reactivates user and shows main menu
- create_new_profile: starts wizard from step 1
- wizard_region: valid region, unknown region, request_start no-op
- wizard_queue: new mode → notify_target step; edit mode → confirm step
- wizard_bot_done: clears state, shows completion message
- wizard_confirm: edit_from_schedule mode; regular edit mode

Each test directly calls the handler function with mocked aiogram objects —
no Dispatcher required.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_user(
    telegram_id: int = 111,
    is_active: bool = True,
    region: str = "kyiv",
    queue: str = "1.1",
    **kwargs,
) -> SimpleNamespace:
    ns = SimpleNamespace(
        notify_schedule_changes=True,
        notify_remind_off=True,
        notify_fact_off=True,
        notify_remind_on=True,
        notify_fact_on=True,
        remind_15m=True,
        remind_30m=False,
        remind_1h=False,
    )
    defaults = dict(
        telegram_id=str(telegram_id),
        is_active=is_active,
        region=region,
        queue=queue,
        router_ip=None,
        last_menu_message_id=None,
        channel_config=None,
        notification_settings=ns,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_message(user_id: int = 111, chat_id: int = 111) -> MagicMock:
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=user_id, username="tester")
    msg.chat = SimpleNamespace(id=chat_id)
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()
    msg.bot.delete_message = AsyncMock()
    return msg


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


def _make_state(data: dict | None = None) -> AsyncMock:
    state = AsyncMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    return state


# ---------------------------------------------------------------------------
# cmd_start
# ---------------------------------------------------------------------------


class TestCmdStart:
    async def test_new_user_shows_wizard(self):
        """Inexistent user → state set to WizardSG.region, answer with region keyboard."""
        from bot.handlers.start import cmd_start

        message = _make_message()
        state = _make_state()
        session = AsyncMock()

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.start.get_setting", AsyncMock(return_value=None)),
            patch("bot.handlers.start.get_region_keyboard", return_value=MagicMock()),
        ):
            await cmd_start(message, state, session)

        state.clear.assert_awaited_once()
        state.set_state.assert_awaited()
        message.answer.assert_awaited_once()
        args, _ = message.answer.call_args
        assert "Вольтик" in args[0]

    async def test_new_user_registration_disabled(self):
        """get_setting returns 'false' → registration closed message, no state change."""
        from bot.handlers.start import cmd_start

        message = _make_message()
        state = _make_state()
        session = AsyncMock()

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.start.get_setting", AsyncMock(return_value="false")),
        ):
            await cmd_start(message, state, session)

        message.answer.assert_awaited_once()
        args, _ = message.answer.call_args
        assert "обмежена" in args[0] or "зупинена" in args[0]
        state.set_state.assert_not_awaited()

    async def test_active_user_shows_main_menu(self):
        """Active existing user → main menu shown, no wizard."""
        from bot.handlers.start import cmd_start

        message = _make_message()
        state = _make_state()
        session = AsyncMock()
        user = _make_user(is_active=True)
        sent = MagicMock()
        sent.message_id = 99
        message.answer = AsyncMock(return_value=sent)

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.format_main_menu_message", return_value="menu text"),
            patch("bot.handlers.start.get_main_menu", return_value=MagicMock()),
        ):
            await cmd_start(message, state, session)

        state.clear.assert_awaited_once()
        message.answer.assert_awaited_once()
        state.set_state.assert_not_awaited()

    async def test_active_user_deletes_previous_menu_message(self):
        """Active user with last_menu_message_id → delete_message called."""
        from bot.handlers.start import cmd_start

        message = _make_message()
        state = _make_state()
        session = AsyncMock()
        user = _make_user(is_active=True, last_menu_message_id=42)
        sent = MagicMock()
        sent.message_id = 100
        message.answer = AsyncMock(return_value=sent)

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.start.get_main_menu", return_value=MagicMock()),
        ):
            await cmd_start(message, state, session)

        message.bot.delete_message.assert_awaited_once_with(message.chat.id, 42)

    async def test_inactive_user_shows_restoration_keyboard(self):
        """Inactive user → restoration choice shown."""
        from bot.handlers.start import cmd_start

        message = _make_message()
        state = _make_state()
        session = AsyncMock()
        user = _make_user(is_active=False)

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_restoration_keyboard", return_value=MagicMock()),
        ):
            await cmd_start(message, state, session)

        message.answer.assert_awaited_once()
        args, _ = message.answer.call_args
        assert "поверненням" in args[0]
        state.set_state.assert_not_awaited()

    async def test_delete_message_exception_is_swallowed(self):
        """Failure to delete old menu message doesn't abort flow."""
        from bot.handlers.start import cmd_start

        message = _make_message()
        message.bot.delete_message = AsyncMock(side_effect=Exception("not found"))
        state = _make_state()
        session = AsyncMock()
        user = _make_user(is_active=True, last_menu_message_id=5)
        sent = MagicMock()
        sent.message_id = 6
        message.answer = AsyncMock(return_value=sent)

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.format_main_menu_message", return_value="menu"),
            patch("bot.handlers.start.get_main_menu", return_value=MagicMock()),
        ):
            await cmd_start(message, state, session)

        # Should still send the menu despite delete failure
        message.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# restore_profile
# ---------------------------------------------------------------------------


class TestRestoreProfile:
    async def test_restores_user_and_shows_menu(self):
        """Callback restores is_active=True and shows main menu."""
        from bot.handlers.start import restore_profile

        cb = _make_callback(data="restore_profile")
        session = AsyncMock()
        user = _make_user(is_active=False)

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.format_main_menu_message", return_value="menu text"),
            patch("bot.handlers.start.get_main_menu", return_value=MagicMock()),
        ):
            await restore_profile(cb, AsyncMock(), session)

        cb.answer.assert_awaited_once()
        assert user.is_active is True
        cb.message.edit_text.assert_awaited_once()

    async def test_restore_user_not_found_does_nothing(self):
        """If user not found in DB, handler returns silently."""
        from bot.handlers.start import restore_profile

        cb = _make_callback(data="restore_profile")
        session = AsyncMock()

        with patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await restore_profile(cb, AsyncMock(), session)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# create_new_profile
# ---------------------------------------------------------------------------


class TestCreateNewProfile:
    async def test_starts_wizard_step1(self):
        """Callback starts wizard at WizardSG.region step."""
        from bot.handlers.start import create_new_profile

        cb = _make_callback(data="create_new_profile")
        state = _make_state()

        with patch("bot.handlers.start.get_region_keyboard", return_value=MagicMock()):
            await create_new_profile(cb, state, AsyncMock())

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        state.update_data.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "регіон" in args[0].lower()


# ---------------------------------------------------------------------------
# wizard_region
# ---------------------------------------------------------------------------


class TestWizardRegion:
    async def test_valid_region_advances_to_queue_step(self):
        """Valid region_kyiv → state moves to WizardSG.queue."""
        from bot.handlers.start import wizard_region

        cb = _make_callback(data="region_kyiv")
        state = _make_state(data={"mode": "new"})
        session = AsyncMock()

        with patch("bot.handlers.start.get_queue_keyboard", return_value=MagicMock()):
            await wizard_region(cb, state, session)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited()
        state.update_data.assert_awaited()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "черг" in args[0].lower() or "Черг" in args[0]

    async def test_unknown_region_answers_error(self):
        """Unknown region code → error answer, no state change."""
        from bot.handlers.start import wizard_region

        cb = _make_callback(data="region_nonexistent")
        state = _make_state()
        session = AsyncMock()

        await wizard_region(cb, state, session)

        cb.answer.assert_awaited_once()
        args, _ = cb.answer.call_args
        assert "Невідомий" in args[0]
        state.set_state.assert_not_awaited()

    async def test_request_start_returns_early(self):
        """region_request_start is a no-op placeholder."""
        from bot.handlers.start import wizard_region

        cb = _make_callback(data="region_request_start")
        state = _make_state()
        session = AsyncMock()

        await wizard_region(cb, state, session)

        state.set_state.assert_not_awaited()
        cb.message.edit_text.assert_not_awaited()

    async def test_edit_mode_fetches_current_queue(self):
        """Edit mode with matching region fetches user's current queue for highlighting."""
        from bot.handlers.start import wizard_region

        cb = _make_callback(data="region_kyiv")
        state = _make_state(data={"mode": "edit"})
        session = AsyncMock()
        user = _make_user(region="kyiv", queue="1.2")

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_queue_keyboard", return_value=MagicMock()) as mock_kb,
        ):
            await wizard_region(cb, state, session)

        # current_queue should be "1.2" (from user) passed to keyboard builder
        call_kwargs = mock_kb.call_args[1]
        assert call_kwargs.get("current_queue") == "1.2"


# ---------------------------------------------------------------------------
# wizard_queue
# ---------------------------------------------------------------------------


class TestWizardQueue:
    async def test_new_mode_advances_to_notify_target(self):
        """New mode → moves to notify_target step."""
        from bot.handlers.start import wizard_queue

        cb = _make_callback(data="queue_1.1")
        state = _make_state(data={"mode": "new", "region": "kyiv"})

        with patch("bot.handlers.start.get_wizard_notify_target_keyboard", return_value=MagicMock()):
            await wizard_queue(cb, state)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited()
        cb.message.edit_text.assert_awaited_once()

    async def test_edit_mode_advances_to_confirm(self):
        """Edit mode → moves to confirm step with summary."""
        from bot.handlers.start import wizard_queue

        cb = _make_callback(data="queue_2.3")
        state = _make_state(data={"mode": "edit", "region": "kyiv"})

        with patch("bot.handlers.start.get_confirm_keyboard", return_value=MagicMock()):
            await wizard_queue(cb, state)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "2.3" in args[0]

    async def test_page_prefix_is_ignored(self):
        """queue_page_ data is handled by wizard_queue_page, not wizard_queue."""
        from bot.handlers.start import wizard_queue

        cb = _make_callback(data="queue_page_2")
        state = _make_state(data={"mode": "new"})

        await wizard_queue(cb, state)

        state.set_state.assert_not_awaited()
        cb.message.edit_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# wizard_bot_done
# ---------------------------------------------------------------------------


class TestWizardBotDone:
    async def test_clears_state_and_shows_completion(self):
        """Done button → state cleared, completion message sent."""
        from bot.handlers.start import wizard_bot_done

        cb = _make_callback(data="wizard_bot_done")
        state = _make_state()
        session = AsyncMock()
        user = _make_user(region="kyiv", queue="1.1")

        with patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)):
            await wizard_bot_done(cb, state, session)

        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "Готово" in args[0]

    async def test_no_user_returns_early(self):
        """If user disappears from DB, handler returns silently."""
        from bot.handlers.start import wizard_bot_done

        cb = _make_callback(data="wizard_bot_done")
        state = _make_state()
        session = AsyncMock()

        with patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await wizard_bot_done(cb, state, session)

        cb.message.edit_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# wizard_confirm
# ---------------------------------------------------------------------------


class TestWizardConfirm:
    async def test_regular_edit_shows_menu(self):
        """Confirm in 'edit' mode → show main menu."""
        from bot.handlers.start import wizard_confirm

        cb = _make_callback(data="confirm_setup")
        state = _make_state(data={"region": "kyiv", "queue": "1.1", "mode": "edit"})
        session = AsyncMock()
        user = _make_user(region="kyiv", queue="1.1")

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_main_menu", return_value=MagicMock()),
        ):
            await wizard_confirm(cb, state, session)

        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "оновлено" in args[0]

    async def test_edit_from_schedule_skips_main_menu(self):
        """edit_from_schedule mode → delegates to _send_schedule_photo."""
        from bot.handlers.start import wizard_confirm

        cb = _make_callback(data="confirm_setup")
        state = _make_state(data={"region": "kyiv", "queue": "2.1", "mode": "edit_from_schedule"})
        session = AsyncMock()
        user = _make_user(region="kyiv", queue="2.1")

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)),
            patch("bot.handlers.menu._send_schedule_photo", AsyncMock()) as mock_send,
        ):
            await wizard_confirm(cb, state, session)

        cb.answer.assert_awaited_once()
        state.clear.assert_awaited_once()
        # First edit_text shows the "updated" message; _send_schedule_photo called
        mock_send.assert_awaited_once()


# ---------------------------------------------------------------------------
# back_to_region
# ---------------------------------------------------------------------------


class TestBackToRegion:
    async def test_returns_to_region_step(self):
        """back_to_region callback moves wizard back to region selection."""
        from bot.handlers.start import back_to_region

        cb = _make_callback(data="back_to_region")
        state = _make_state()

        with patch("bot.handlers.start.get_region_keyboard", return_value=MagicMock()):
            await back_to_region(cb, state)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# wizard_queue_page
# ---------------------------------------------------------------------------


class TestWizardQueuePage:
    async def test_valid_page_shows_queue_keyboard(self):
        """Valid page number → shows queue keyboard for that page."""
        from bot.handlers.start import wizard_queue_page

        cb = _make_callback(data="queue_page_2")
        state = _make_state(data={"region": "kyiv"})

        with patch("bot.handlers.start.get_queue_keyboard", return_value=MagicMock()):
            await wizard_queue_page(cb, state)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_invalid_page_returns_early(self):
        """Non-integer page suffix → answer and return without editing."""
        from bot.handlers.start import wizard_queue_page

        cb = _make_callback(data="queue_page_abc")
        state = _make_state(data={"region": "kyiv"})

        await wizard_queue_page(cb, state)

        cb.answer.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# wizard_notify_bot
# ---------------------------------------------------------------------------


class TestWizardNotifyBot:
    async def test_shows_bot_notification_step(self):
        """wizard_notify_bot → creates user, advances to bot_notifications step."""
        from bot.handlers.start import wizard_notify_bot

        cb = _make_callback(data="wizard_notify_bot")
        state = _make_state(data={"region": "kyiv", "queue": "1.1"})
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
        ):
            await wizard_notify_bot(cb, state, session)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()

    async def test_no_notification_settings_shows_error(self):
        """User created but notification_settings is None → error message shown."""
        from bot.handlers.start import wizard_notify_bot

        cb = _make_callback(data="wizard_notify_bot")
        state = _make_state(data={"region": "kyiv", "queue": "1.1"})
        session = AsyncMock()
        user = _make_user()
        user.notification_settings = None

        with patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)):
            await wizard_notify_bot(cb, state, session)

        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "Помилка" in args[0]
        state.clear.assert_awaited_once()

    async def test_new_mode_increments_registration_metric(self):
        """mode='new' without _registration_counted → inc() called once, flag set."""
        from bot.handlers.start import wizard_notify_bot

        cb = _make_callback(data="wizard_notify_bot")
        state = _make_state(data={"region": "kyiv", "queue": "1.1", "mode": "new"})
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
            patch("bot.handlers.start.USER_REGISTRATIONS_TOTAL") as mock_counter,
        ):
            await wizard_notify_bot(cb, state, session)

        mock_counter.inc.assert_called_once()
        state.update_data.assert_awaited()

    async def test_already_counted_does_not_increment_again(self):
        """_registration_counted=True → inc() not called a second time."""
        from bot.handlers.start import wizard_notify_bot

        cb = _make_callback(data="wizard_notify_bot")
        state = _make_state(
            data={"region": "kyiv", "queue": "1.1", "mode": "new", "_registration_counted": True}
        )
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
            patch("bot.handlers.start.USER_REGISTRATIONS_TOTAL") as mock_counter,
        ):
            await wizard_notify_bot(cb, state, session)

        mock_counter.inc.assert_not_called()


# ---------------------------------------------------------------------------
# wizard_toggle_schedule
# ---------------------------------------------------------------------------


class TestWizardToggleSchedule:
    async def test_toggles_schedule_flag(self):
        """wizard_toggle_schedule flips notify_schedule_changes and edits markup."""
        from bot.handlers.start import wizard_toggle_schedule

        cb = _make_callback(data="wizard_notif_toggle_schedule")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_schedule_changes = True

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
        ):
            await wizard_toggle_schedule(cb, state, session)

        assert user.notification_settings.notify_schedule_changes is False
        cb.answer.assert_awaited_once()
        cb.message.edit_reply_markup.assert_awaited_once()

    async def test_no_user_still_answers(self):
        """No user → answer is still called, no crash."""
        from bot.handlers.start import wizard_toggle_schedule

        cb = _make_callback(data="wizard_notif_toggle_schedule")
        state = _make_state()
        session = AsyncMock()

        with patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await wizard_toggle_schedule(cb, state, session)

        cb.answer.assert_awaited_once()
        cb.message.edit_reply_markup.assert_not_awaited()


# ---------------------------------------------------------------------------
# wizard_toggle_time
# ---------------------------------------------------------------------------


class TestWizardToggleTime:
    async def test_toggle_15m(self):
        """wizard_notif_time_15 → flips remind_15m."""
        from bot.handlers.start import wizard_toggle_time

        cb = _make_callback(data="wizard_notif_time_15")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.remind_15m = False

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
        ):
            await wizard_toggle_time(cb, state, session)

        assert user.notification_settings.remind_15m is True
        cb.answer.assert_awaited_once()

    async def test_toggle_30m(self):
        """wizard_notif_time_30 → flips remind_30m."""
        from bot.handlers.start import wizard_toggle_time

        cb = _make_callback(data="wizard_notif_time_30")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.remind_30m = False

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
        ):
            await wizard_toggle_time(cb, state, session)

        assert user.notification_settings.remind_30m is True

    async def test_toggle_60m(self):
        """wizard_notif_time_60 → flips remind_1h."""
        from bot.handlers.start import wizard_toggle_time

        cb = _make_callback(data="wizard_notif_time_60")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.remind_1h = False

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
        ):
            await wizard_toggle_time(cb, state, session)

        assert user.notification_settings.remind_1h is True

    async def test_invalid_suffix_returns_early(self):
        """Non-integer time suffix → answer and return."""
        from bot.handlers.start import wizard_toggle_time

        cb = _make_callback(data="wizard_notif_time_abc")
        state = _make_state()
        session = AsyncMock()

        with patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock()) as mock_get:
            await wizard_toggle_time(cb, state, session)

        mock_get.assert_not_awaited()
        cb.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# wizard_toggle_fact
# ---------------------------------------------------------------------------


class TestWizardToggleFact:
    async def test_toggles_fact_off_and_on(self):
        """wizard_toggle_fact flips both notify_fact_off and notify_fact_on."""
        from bot.handlers.start import wizard_toggle_fact

        cb = _make_callback(data="wizard_notif_toggle_fact")
        state = _make_state()
        session = AsyncMock()
        user = _make_user()
        user.notification_settings.notify_fact_off = True
        user.notification_settings.notify_fact_on = True

        with (
            patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_bot_notification_keyboard", return_value=MagicMock()),
        ):
            await wizard_toggle_fact(cb, state, session)

        assert user.notification_settings.notify_fact_off is False
        assert user.notification_settings.notify_fact_on is False
        cb.answer.assert_awaited_once()
        cb.message.edit_reply_markup.assert_awaited_once()

    async def test_no_user_still_answers(self):
        """No user → answer is still called."""
        from bot.handlers.start import wizard_toggle_fact

        cb = _make_callback(data="wizard_notif_toggle_fact")
        state = _make_state()
        session = AsyncMock()

        with patch("bot.handlers.start.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await wizard_toggle_fact(cb, state, session)

        cb.answer.assert_awaited_once()
        cb.message.edit_reply_markup.assert_not_awaited()


# ---------------------------------------------------------------------------
# wizard_notify_back
# ---------------------------------------------------------------------------


class TestWizardNotifyBack:
    async def test_returns_to_notify_target_step(self):
        """wizard_notify_back → moves back to notify_target step."""
        from bot.handlers.start import wizard_notify_back

        cb = _make_callback(data="wizard_notify_back")
        state = _make_state(data={"queue": "1.1"})

        with patch("bot.handlers.start.get_wizard_notify_target_keyboard", return_value=MagicMock()):
            await wizard_notify_back(cb, state)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "1.1" in args[0]


# ---------------------------------------------------------------------------
# wizard_notify_channel
# ---------------------------------------------------------------------------


class TestWizardNotifyChannel:
    async def test_shows_channel_setup_instructions(self):
        """wizard_notify_channel → creates user, shows channel setup instructions."""
        from bot.handlers.start import wizard_notify_channel

        cb = _make_callback(data="wizard_notify_channel")
        cb.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="VoltykBot"))
        state = _make_state(data={"region": "kyiv", "queue": "1.1"})
        session = AsyncMock()
        user = _make_user()

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock(return_value=user)),
            patch("bot.handlers.start.get_wizard_notify_target_keyboard", return_value=MagicMock()),
        ):
            await wizard_notify_channel(cb, state, session)

        cb.answer.assert_awaited_once()
        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()
        args, _ = cb.message.edit_text.call_args
        assert "VoltykBot" in args[0]

    async def test_new_mode_increments_registration_metric(self):
        """mode='new' in state → USER_REGISTRATIONS_TOTAL.inc() called."""
        from bot.handlers.start import wizard_notify_channel

        cb = _make_callback(data="wizard_notify_channel")
        cb.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="VoltykBot"))
        state = _make_state(data={"region": "kyiv", "queue": "1.1", "mode": "new"})
        session = AsyncMock()

        with (
            patch("bot.handlers.start.create_or_update_user", AsyncMock()),
            patch("bot.handlers.start.get_wizard_notify_target_keyboard", return_value=MagicMock()),
            patch("bot.handlers.start.USER_REGISTRATIONS_TOTAL") as mock_counter,
        ):
            await wizard_notify_channel(cb, state, session)

        mock_counter.inc.assert_called_once()
