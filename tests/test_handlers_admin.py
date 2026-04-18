"""Tests for bot/handlers/admin/*.py

Covered handlers:
- admin_router.py: admin_router_view, admin_router_set_ip, admin_router_ip_input,
  admin_router_toggle_notify, admin_router_stats
- chart_settings.py: admin_chart_render, set_chart_render, chart_preview_menu,
  chart_preview_render
- database.py: admin_clear_db, admin_restart, admin_restart_confirm
- growth.py: admin_growth, growth_metrics, growth_stage, growth_stage_set,
  growth_registration, growth_reg_toggle, growth_reg_status, growth_events
- intervals.py: admin_intervals, admin_interval_schedule, admin_schedule_set,
  admin_interval_ip, admin_ip_set, admin_refresh_cooldown, admin_cooldown_set
- maintenance.py: admin_maintenance, maintenance_toggle, maintenance_edit_message,
  maintenance_message_input
- panel.py: cmd_admin, settings_admin, admin_menu, admin_analytics, admin_stats,
  admin_users, admin_users_stats, admin_users_list, admin_settings_menu, admin_system
- pause.py: admin_pause, pause_status, pause_toggle, pause_message_settings,
  pause_template, pause_custom_message, pause_custom_message_input,
  pause_toggle_support, pause_type_select, pause_type_set, pause_log,
  admin_debounce, debounce_set
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_callback(user_id: int = 42, data: str = "") -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id)
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.answer_photo = AsyncMock()
    cb.message.reply = AsyncMock()
    return cb


def _make_message(user_id: int = 42, text: str | None = "hello") -> MagicMock:
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=user_id)
    msg.text = text
    msg.reply = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _make_session() -> AsyncMock:
    s = AsyncMock()
    s.commit = AsyncMock()
    return s


def _make_state() -> AsyncMock:
    state = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


# ===========================================================================
# admin_router.py
# ===========================================================================

class TestAdminRouterView:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.admin_router import admin_router_view

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = False
            await admin_router_view(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_no_admin_router_record(self):
        from bot.handlers.admin.admin_router import admin_router_view

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.admin_router.settings") as ms,
            patch("bot.handlers.admin.admin_router.get_admin_router", new_callable=AsyncMock, return_value=None),
            patch("bot.handlers.admin.admin_router.get_admin_router_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_router_view(cb, session)

        cb.answer.assert_awaited()
        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "не налаштовано" in text

    async def test_with_ip_and_last_state(self):
        from bot.handlers.admin.admin_router import admin_router_view

        cb = _make_callback()
        session = _make_session()
        ar = SimpleNamespace(router_ip="1.2.3.4", notifications_on=True, last_state="online")
        with (
            patch("bot.handlers.admin.admin_router.settings") as ms,
            patch("bot.handlers.admin.admin_router.get_admin_router", new_callable=AsyncMock, return_value=ar),
            patch("bot.handlers.admin.admin_router.get_admin_router_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_router_view(cb, session)

        text = cb.message.edit_text.call_args[0][0]
        assert "1.2.3.4" in text
        assert "online" in text


class TestAdminRouterSetIp:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.admin_router import admin_router_set_ip

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = False
            await admin_router_set_ip(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")
        state.set_state.assert_not_awaited()

    async def test_sets_waiting_state(self):
        from bot.handlers.admin.admin_router import admin_router_set_ip

        cb = _make_callback()
        state = _make_state()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = True
            await admin_router_set_ip(cb, state)

        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


class TestAdminRouterIpInput:
    async def test_not_admin_clears_state(self):
        from bot.handlers.admin.admin_router import admin_router_ip_input

        msg = _make_message(user_id=999)
        state = _make_state()
        session = _make_session()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = False
            await admin_router_ip_input(msg, state, session)

        state.clear.assert_awaited_once()

    async def test_no_text_returns(self):
        from bot.handlers.admin.admin_router import admin_router_ip_input

        msg = _make_message(text=None)
        state = _make_state()
        session = _make_session()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = True
            await admin_router_ip_input(msg, state, session)

        state.clear.assert_not_awaited()
        msg.reply.assert_not_awaited()

    async def test_invalid_ip_replies_error(self):
        from bot.handlers.admin.admin_router import admin_router_ip_input

        msg = _make_message(text="not-valid!")
        state = _make_state()
        session = _make_session()
        with (
            patch("bot.handlers.admin.admin_router.settings") as ms,
            patch(
                "bot.handlers.admin.admin_router.is_valid_ip_or_domain",
                return_value={"valid": False, "error": "bad ip"},
            ),
        ):
            ms.is_admin.return_value = True
            await admin_router_ip_input(msg, state, session)

        msg.reply.assert_awaited_once()
        state.clear.assert_not_awaited()

    async def test_valid_ip_saves(self):
        from bot.handlers.admin.admin_router import admin_router_ip_input

        msg = _make_message(text="192.168.1.1")
        state = _make_state()
        session = _make_session()
        with (
            patch("bot.handlers.admin.admin_router.settings") as ms,
            patch(
                "bot.handlers.admin.admin_router.is_valid_ip_or_domain",
                return_value={"valid": True, "host": "192.168.1.1", "port": 80, "address": "192.168.1.1"},
            ),
            patch("bot.handlers.admin.admin_router.upsert_admin_router", new_callable=AsyncMock) as mock_upsert,
        ):
            ms.is_admin.return_value = True
            await admin_router_ip_input(msg, state, session)

        mock_upsert.assert_awaited_once()
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()


class TestAdminRouterToggleNotify:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.admin_router import admin_router_toggle_notify

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = False
            await admin_router_toggle_notify(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_no_ar_just_answers(self):
        from bot.handlers.admin.admin_router import admin_router_toggle_notify

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.admin_router.settings") as ms,
            patch("bot.handlers.admin.admin_router.get_admin_router", new_callable=AsyncMock, return_value=None),
        ):
            ms.is_admin.return_value = True
            await admin_router_toggle_notify(cb, session)

        cb.answer.assert_awaited()
        cb.message.edit_reply_markup.assert_not_awaited()

    async def test_toggles_notifications(self):
        from bot.handlers.admin.admin_router import admin_router_toggle_notify

        cb = _make_callback()
        session = _make_session()
        ar = SimpleNamespace(router_ip="1.2.3.4", notifications_on=True)
        with (
            patch("bot.handlers.admin.admin_router.settings") as ms,
            patch("bot.handlers.admin.admin_router.get_admin_router", new_callable=AsyncMock, return_value=ar),
            patch("bot.handlers.admin.admin_router.get_admin_router_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_router_toggle_notify(cb, session)

        assert ar.notifications_on is False
        cb.message.edit_reply_markup.assert_awaited_once()


class TestAdminRouterStats:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.admin_router import admin_router_stats

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = False
            await admin_router_stats(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_wip_alert(self):
        from bot.handlers.admin.admin_router import admin_router_stats

        cb = _make_callback()
        with patch("bot.handlers.admin.admin_router.settings") as ms:
            ms.is_admin.return_value = True
            await admin_router_stats(cb)

        cb.answer.assert_awaited_once_with("⚠️ Статистика роутера в розробці", show_alert=True)


# ===========================================================================
# chart_settings.py
# ===========================================================================

class TestAdminChartRender:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.chart_settings import admin_chart_render

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.chart_settings.settings") as ms:
            ms.is_admin.return_value = False
            await admin_chart_render(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_current_mode(self):
        from bot.handlers.admin.chart_settings import admin_chart_render

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.get_setting", new_callable=AsyncMock, return_value="on_change"),
            patch("bot.handlers.admin.chart_settings.get_chart_render_mode_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_chart_render(cb, session)

        cb.answer.assert_awaited()
        cb.message.edit_text.assert_awaited_once()


class TestSetChartRender:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.chart_settings import set_chart_render

        cb = _make_callback(user_id=999, data="chart_render_mode_on_demand")
        session = _make_session()
        with patch("bot.handlers.admin.chart_settings.settings") as ms:
            ms.is_admin.return_value = False
            await set_chart_render(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_unknown_mode(self):
        from bot.handlers.admin.chart_settings import set_chart_render

        cb = _make_callback(data="chart_render_mode_unknown")
        session = _make_session()
        with patch("bot.handlers.admin.chart_settings.settings") as ms:
            ms.is_admin.return_value = True
            await set_chart_render(cb, session)

        cb.answer.assert_awaited_once_with("❌ Невідомий режим")

    async def test_same_mode_no_update(self):
        from bot.handlers.admin.chart_settings import set_chart_render

        cb = _make_callback(data="chart_render_mode_on_change")
        session = _make_session()
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.get_setting", new_callable=AsyncMock, return_value="on_change"),
        ):
            ms.is_admin.return_value = True
            await set_chart_render(cb, session)

        cb.answer.assert_awaited_once_with()
        session.commit.assert_not_awaited()

    async def test_different_mode_saves(self):
        from bot.handlers.admin.chart_settings import set_chart_render

        cb = _make_callback(data="chart_render_mode_on_demand")
        session = _make_session()
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.get_setting", new_callable=AsyncMock, return_value="on_change"),
            patch("bot.handlers.admin.chart_settings.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.chart_settings.set_chart_render_mode") as mock_mode,
            patch("bot.handlers.admin.chart_settings.get_chart_render_mode_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await set_chart_render(cb, session)

        mock_set.assert_awaited_once()
        session.commit.assert_awaited_once()
        mock_mode.assert_called_once_with(on_demand=True)
        cb.message.edit_reply_markup.assert_awaited_once()


class TestChartPreviewMenu:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.chart_settings import chart_preview_menu

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.chart_settings.settings") as ms:
            ms.is_admin.return_value = False
            await chart_preview_menu(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_preview_menu(self):
        from bot.handlers.admin.chart_settings import chart_preview_menu

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.get_chart_preview_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await chart_preview_menu(cb)

        cb.answer.assert_awaited()
        cb.message.edit_text.assert_awaited_once()


class TestChartPreviewRender:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.chart_settings import chart_preview_render

        cb = _make_callback(user_id=999, data="chart_preview:two_outages")
        with patch("bot.handlers.admin.chart_settings.settings") as ms:
            ms.is_admin.return_value = False
            await chart_preview_render(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_unknown_scenario(self):
        from bot.handlers.admin.chart_settings import chart_preview_render

        cb = _make_callback(data="chart_preview:nonexistent")
        with patch("bot.handlers.admin.chart_settings.settings") as ms:
            ms.is_admin.return_value = True
            await chart_preview_render(cb)

        cb.answer.assert_awaited_once_with("❌ Невідомий сценарій")

    async def test_png_bytes_none_sends_error(self):
        from bot.handlers.admin.chart_settings import chart_preview_render

        cb = _make_callback(data="chart_preview:two_outages")
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.generate_schedule_chart", new_callable=AsyncMock, return_value=None),
        ):
            ms.is_admin.return_value = True
            await chart_preview_render(cb)

        cb.message.answer.assert_awaited_once()
        cb.message.answer_photo.assert_not_awaited()

    async def test_valid_scenario_sends_photo(self):
        from bot.handlers.admin.chart_settings import chart_preview_render

        cb = _make_callback(data="chart_preview:allday")
        png_data = b"fakepng"
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.generate_schedule_chart", new_callable=AsyncMock, return_value=png_data),
        ):
            ms.is_admin.return_value = True
            await chart_preview_render(cb)

        cb.message.answer_photo.assert_awaited_once()

    async def test_three_outages_scenario_sends_photo(self):
        from bot.handlers.admin.chart_settings import chart_preview_render

        cb = _make_callback(data="chart_preview:three_outages")
        png_data = b"fakepng"
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.generate_schedule_chart", new_callable=AsyncMock, return_value=png_data),
        ):
            ms.is_admin.return_value = True
            await chart_preview_render(cb)

        cb.message.answer_photo.assert_awaited_once()

    async def test_halfhour_scenario_sends_photo(self):
        from bot.handlers.admin.chart_settings import chart_preview_render

        cb = _make_callback(data="chart_preview:halfhour")
        png_data = b"fakepng"
        with (
            patch("bot.handlers.admin.chart_settings.settings") as ms,
            patch("bot.handlers.admin.chart_settings.generate_schedule_chart", new_callable=AsyncMock, return_value=png_data),
        ):
            ms.is_admin.return_value = True
            await chart_preview_render(cb)

        cb.message.answer_photo.assert_awaited_once()


# ===========================================================================
# database.py
# ===========================================================================

class TestAdminClearDb:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.database import admin_clear_db

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.database.settings") as ms:
            ms.is_owner.return_value = False
            await admin_clear_db(cb)

        cb.answer.assert_awaited_once_with("❌ Тільки для власника")

    async def test_owner_sees_disabled_message(self):
        from bot.handlers.admin.database import admin_clear_db

        cb = _make_callback()
        with patch("bot.handlers.admin.database.settings") as ms:
            ms.is_owner.return_value = True
            await admin_clear_db(cb)

        cb.answer.assert_awaited_once_with("⚠️ Ця функція вимкнена з безпеки", show_alert=True)


class TestAdminRestart:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.database import admin_restart

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.database.settings") as ms:
            ms.is_owner.return_value = False
            await admin_restart(cb)

        cb.answer.assert_awaited_once_with("❌ Тільки для власника")

    async def test_owner_shows_confirm(self):
        from bot.handlers.admin.database import admin_restart

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.database.settings") as ms,
            patch("bot.handlers.admin.database.get_restart_confirm_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_restart(cb)

        cb.answer.assert_awaited()
        cb.message.edit_text.assert_awaited_once()


class TestAdminRestartConfirm:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.database import admin_restart_confirm

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.database.settings") as ms:
            ms.is_owner.return_value = False
            await admin_restart_confirm(cb)

        cb.answer.assert_awaited_once_with("❌ Тільки для власника")

    async def test_owner_calls_sys_exit(self):
        import sys

        from bot.handlers.admin.database import admin_restart_confirm

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.database.settings") as ms,
            patch.object(sys, "exit") as mock_exit,
        ):
            ms.is_owner.return_value = True
            await admin_restart_confirm(cb)

        cb.answer.assert_awaited()
        cb.message.edit_text.assert_awaited_once()
        mock_exit.assert_called_once_with(0)


# ===========================================================================
# growth.py
# ===========================================================================

class TestAdminGrowth:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.growth import admin_growth

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = False
            await admin_growth(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_growth_menu(self):
        from bot.handlers.admin.growth import admin_growth

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.get_growth_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_growth(cb)

        cb.message.edit_text.assert_awaited_once()


class TestGrowthMetrics:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.growth import growth_metrics

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = False
            await growth_metrics(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_metrics_alert(self):
        from bot.handlers.admin.growth import growth_metrics

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.count_active_users", new_callable=AsyncMock, return_value=5),
            patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="2"),
        ):
            ms.is_admin.return_value = True
            await growth_metrics(cb, session)

        cb.answer.assert_awaited_once()
        args = cb.answer.call_args
        assert show_alert_was_set(args)


class TestGrowthStage:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.growth import growth_stage

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = False
            await growth_stage(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_stage_keyboard(self):
        from bot.handlers.admin.growth import growth_stage

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="1"),
            patch("bot.handlers.admin.growth.get_growth_stage_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await growth_stage(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestGrowthStageSet:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.growth import growth_stage_set

        cb = _make_callback(user_id=999, data="growth_stage_2")
        session = _make_session()
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = False
            await growth_stage_set(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_invalid_stage_just_answers(self):
        from bot.handlers.admin.growth import growth_stage_set

        cb = _make_callback(data="growth_stage_bad")
        session = _make_session()
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = True
            await growth_stage_set(cb, session)

        cb.answer.assert_awaited_once_with()

    async def test_valid_stage_saves(self):
        from bot.handlers.admin.growth import growth_stage_set

        cb = _make_callback(data="growth_stage_3")
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.growth.get_growth_stage_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await growth_stage_set(cb, session)

        mock_set.assert_awaited_once()
        cb.message.edit_reply_markup.assert_awaited_once()


class TestGrowthRegistration:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.growth import growth_registration

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = False
            await growth_registration(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_enabled(self):
        from bot.handlers.admin.growth import growth_registration

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="true"),
            patch("bot.handlers.admin.growth.get_growth_registration_keyboard", return_value=MagicMock()) as mk,
        ):
            ms.is_admin.return_value = True
            await growth_registration(cb, session)

        mk.assert_called_once_with(enabled=True)

    async def test_disabled(self):
        from bot.handlers.admin.growth import growth_registration

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.growth.get_growth_registration_keyboard", return_value=MagicMock()) as mk,
        ):
            ms.is_admin.return_value = True
            await growth_registration(cb, session)

        mk.assert_called_once_with(enabled=False)


class TestGrowthRegToggle:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.growth import growth_reg_toggle

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.growth.settings") as ms:
            ms.is_admin.return_value = False
            await growth_reg_toggle(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_toggle_true_to_false(self):
        from bot.handlers.admin.growth import growth_reg_toggle

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="true"),
            patch("bot.handlers.admin.growth.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.growth.get_growth_registration_keyboard", return_value=MagicMock()) as mk,
        ):
            ms.is_admin.return_value = True
            await growth_reg_toggle(cb, session)

        mock_set.assert_awaited_once_with(session, "registration_enabled", "false")
        mk.assert_called_once_with(enabled=False)

    async def test_toggle_false_to_true(self):
        from bot.handlers.admin.growth import growth_reg_toggle

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.growth.settings") as ms,
            patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.growth.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.growth.get_growth_registration_keyboard", return_value=MagicMock()) as mk,
        ):
            ms.is_admin.return_value = True
            await growth_reg_toggle(cb, session)

        mock_set.assert_awaited_once_with(session, "registration_enabled", "true")
        mk.assert_called_once_with(enabled=True)


class TestGrowthRegStatus:
    async def test_enabled_answer(self):
        from bot.handlers.admin.growth import growth_reg_status

        cb = _make_callback()
        session = _make_session()
        with patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="true"):
            await growth_reg_status(cb, session)

        cb.answer.assert_awaited_once_with("🟢 Увімкнена")

    async def test_disabled_answer(self):
        from bot.handlers.admin.growth import growth_reg_status

        cb = _make_callback()
        session = _make_session()
        with patch("bot.handlers.admin.growth.get_setting", new_callable=AsyncMock, return_value="false"):
            await growth_reg_status(cb, session)

        cb.answer.assert_awaited_once_with("🔴 Вимкнена")


class TestGrowthEvents:
    async def test_shows_wip_alert(self):
        from bot.handlers.admin.growth import growth_events

        cb = _make_callback()
        await growth_events(cb)

        cb.answer.assert_awaited_once_with("⚠️ Ця функція в розробці", show_alert=True)


# ===========================================================================
# intervals.py
# ===========================================================================

class TestAdminIntervals:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_intervals

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_intervals(cb, session)

        cb.answer.assert_awaited_once()
        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_shows_intervals_keyboard(self):
        from bot.handlers.admin.intervals import admin_intervals

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.get_setting", new_callable=AsyncMock, return_value="180"),
            patch("bot.handlers.admin.intervals.get_admin_intervals_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_intervals(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestAdminIntervalSchedule:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_interval_schedule

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_interval_schedule(cb, session)

        cb.answer.assert_awaited_once()
        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_shows_schedule_keyboard(self):
        from bot.handlers.admin.intervals import admin_interval_schedule

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.get_setting", new_callable=AsyncMock, return_value="180"),
            patch("bot.handlers.admin.intervals.get_schedule_interval_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_interval_schedule(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestAdminScheduleSet:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_schedule_set

        cb = _make_callback(user_id=999, data="admin_schedule_5")
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_schedule_set(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_invalid_value_just_answers(self):
        from bot.handlers.admin.intervals import admin_schedule_set

        cb = _make_callback(data="admin_schedule_bad")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=None),
        ):
            ms.is_owner.return_value = True
            await admin_schedule_set(cb, session)

        cb.answer.assert_awaited_once_with()

    async def test_valid_minutes_saves(self):
        from bot.handlers.admin.intervals import admin_schedule_set

        cb = _make_callback(data="admin_schedule_5")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=5),
            patch("bot.handlers.admin.intervals.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.intervals.get_schedule_interval_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_schedule_set(cb, session)

        mock_set.assert_awaited_once_with(session, "schedule_check_interval", "300")
        cb.answer.assert_awaited_once_with("✅ Інтервал: 5 хв")


class TestAdminIntervalIp:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_interval_ip

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_interval_ip(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_shows_ip_keyboard(self):
        from bot.handlers.admin.intervals import admin_interval_ip

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.get_setting", new_callable=AsyncMock, return_value="10"),
            patch("bot.handlers.admin.intervals.get_ip_interval_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_interval_ip(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestAdminIpSet:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_ip_set

        cb = _make_callback(user_id=999, data="admin_ip_10")
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_ip_set(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_invalid_value_just_answers(self):
        from bot.handlers.admin.intervals import admin_ip_set

        cb = _make_callback(data="admin_ip_bad")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=None),
        ):
            ms.is_owner.return_value = True
            await admin_ip_set(cb, session)

        cb.answer.assert_awaited_once_with()

    async def test_zero_saves_dynamic(self):
        from bot.handlers.admin.intervals import admin_ip_set

        cb = _make_callback(data="admin_ip_0")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=0),
            patch("bot.handlers.admin.intervals.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.intervals.get_ip_interval_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_ip_set(cb, session)

        cb.answer.assert_awaited_once_with("✅ Інтервал: Динамічний")

    async def test_nonzero_saves_seconds(self):
        from bot.handlers.admin.intervals import admin_ip_set

        cb = _make_callback(data="admin_ip_30")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=30),
            patch("bot.handlers.admin.intervals.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.intervals.get_ip_interval_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_ip_set(cb, session)

        cb.answer.assert_awaited_once_with("✅ Інтервал: 30 сек")


class TestAdminRefreshCooldown:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_refresh_cooldown

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_refresh_cooldown(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_shows_cooldown_keyboard(self):
        from bot.handlers.admin.intervals import admin_refresh_cooldown

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.get_setting", new_callable=AsyncMock, return_value="30"),
            patch("bot.handlers.admin.intervals.get_refresh_cooldown_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_refresh_cooldown(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestAdminCooldownSet:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.intervals import admin_cooldown_set

        cb = _make_callback(user_id=999, data="admin_cooldown_set_60")
        session = _make_session()
        with patch("bot.handlers.admin.intervals.settings") as ms:
            ms.is_owner.return_value = False
            await admin_cooldown_set(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_invalid_value_just_answers(self):
        from bot.handlers.admin.intervals import admin_cooldown_set

        cb = _make_callback(data="admin_cooldown_set_bad")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=None),
        ):
            ms.is_owner.return_value = True
            await admin_cooldown_set(cb, session)

        cb.answer.assert_awaited_once_with()

    async def test_valid_value_saves(self):
        from bot.handlers.admin.intervals import admin_cooldown_set

        cb = _make_callback(data="admin_cooldown_set_60")
        session = _make_session()
        with (
            patch("bot.handlers.admin.intervals.settings") as ms,
            patch("bot.handlers.admin.intervals.safe_parse_callback_int", return_value=60),
            patch("bot.handlers.admin.intervals.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.intervals.get_refresh_cooldown_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_cooldown_set(cb, session)

        cb.answer.assert_awaited_once_with("✅ Cooldown: 60 сек")


# ===========================================================================
# maintenance.py
# ===========================================================================

class TestAdminMaintenance:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.maintenance import admin_maintenance

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.maintenance.settings") as ms:
            ms.is_admin.return_value = False
            await admin_maintenance(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_enabled_status(self):
        from bot.handlers.admin.maintenance import admin_maintenance

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.maintenance.settings") as ms,
            patch("bot.handlers.admin.maintenance.is_maintenance_mode", return_value=True),
            patch("bot.handlers.admin.maintenance.get_maintenance_message", return_value="msg"),
            patch("bot.handlers.admin.maintenance.get_maintenance_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_maintenance(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "🟢 Увімкнено" in text

    async def test_disabled_status(self):
        from bot.handlers.admin.maintenance import admin_maintenance

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.maintenance.settings") as ms,
            patch("bot.handlers.admin.maintenance.is_maintenance_mode", return_value=False),
            patch("bot.handlers.admin.maintenance.get_maintenance_message", return_value="msg"),
            patch("bot.handlers.admin.maintenance.get_maintenance_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_maintenance(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "🔴 Вимкнено" in text


class TestMaintenanceToggle:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.maintenance import maintenance_toggle

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.maintenance.settings") as ms:
            ms.is_admin.return_value = False
            await maintenance_toggle(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_toggle_on_to_off(self):
        from bot.handlers.admin.maintenance import maintenance_toggle

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.maintenance.settings") as ms,
            patch("bot.handlers.admin.maintenance.is_maintenance_mode", return_value=True),
            patch("bot.handlers.admin.maintenance.persist_maintenance_mode", new_callable=AsyncMock) as mock_persist,
            patch("bot.handlers.admin.maintenance.get_maintenance_message", return_value="msg"),
            patch("bot.handlers.admin.maintenance.get_maintenance_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await maintenance_toggle(cb)

        mock_persist.assert_awaited_once_with(False)
        text = cb.message.edit_text.call_args[0][0]
        assert "🔴 Вимкнено" in text

    async def test_toggle_off_to_on(self):
        from bot.handlers.admin.maintenance import maintenance_toggle

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.maintenance.settings") as ms,
            patch("bot.handlers.admin.maintenance.is_maintenance_mode", return_value=False),
            patch("bot.handlers.admin.maintenance.persist_maintenance_mode", new_callable=AsyncMock) as mock_persist,
            patch("bot.handlers.admin.maintenance.get_maintenance_message", return_value="msg"),
            patch("bot.handlers.admin.maintenance.get_maintenance_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await maintenance_toggle(cb)

        mock_persist.assert_awaited_once_with(True)
        text = cb.message.edit_text.call_args[0][0]
        assert "🟢 Увімкнено" in text


class TestMaintenanceEditMessage:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.maintenance import maintenance_edit_message

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.maintenance.settings") as ms:
            ms.is_admin.return_value = False
            await maintenance_edit_message(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")
        state.set_state.assert_not_awaited()

    async def test_sets_waiting_state(self):
        from bot.handlers.admin.maintenance import maintenance_edit_message

        cb = _make_callback()
        state = _make_state()
        with patch("bot.handlers.admin.maintenance.settings") as ms:
            ms.is_admin.return_value = True
            await maintenance_edit_message(cb, state)

        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


class TestMaintenanceMessageInput:
    async def test_not_admin_clears_state(self):
        from bot.handlers.admin.maintenance import maintenance_message_input

        msg = _make_message(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.maintenance.settings") as ms:
            ms.is_admin.return_value = False
            await maintenance_message_input(msg, state)

        state.clear.assert_awaited_once()
        msg.answer.assert_not_awaited()

    async def test_no_text_returns(self):
        from bot.handlers.admin.maintenance import maintenance_message_input

        msg = _make_message(text=None)
        state = _make_state()
        with patch("bot.handlers.admin.maintenance.settings") as ms:
            ms.is_admin.return_value = True
            await maintenance_message_input(msg, state)

        state.clear.assert_not_awaited()
        msg.answer.assert_not_awaited()

    async def test_valid_text_updates_message(self):
        from bot.handlers.admin.maintenance import maintenance_message_input

        msg = _make_message(text="Maintenance in progress")
        state = _make_state()
        with (
            patch("bot.handlers.admin.maintenance.settings") as ms,
            patch("bot.handlers.admin.maintenance.persist_maintenance_mode", new_callable=AsyncMock) as mock_persist,
            patch("bot.handlers.admin.maintenance.is_maintenance_mode", return_value=False),
            patch("bot.handlers.admin.maintenance.get_maintenance_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await maintenance_message_input(msg, state)

        mock_persist.assert_awaited_once()
        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()


# ===========================================================================
# panel.py
# ===========================================================================

class TestCmdAdmin:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import cmd_admin

        msg = _make_message(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await cmd_admin(msg, session)

        msg.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_admin_shows_panel(self):
        from bot.handlers.admin.panel import cmd_admin

        msg = _make_message()
        session = _make_session()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_admin_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await cmd_admin(msg, session)

        msg.answer.assert_awaited_once()


class TestSettingsAdmin:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import settings_admin

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await settings_admin(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_admin_shows_panel(self):
        from bot.handlers.admin.panel import settings_admin

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_admin_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await settings_admin(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestAdminMenu:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_menu

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_menu(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_admin_shows_menu(self):
        from bot.handlers.admin.panel import admin_menu

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_admin_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_menu(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestAdminAnalytics:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_analytics

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_analytics(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_analytics_keyboard(self):
        from bot.handlers.admin.panel import admin_analytics

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_admin_analytics_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_analytics(cb)

        cb.message.edit_text.assert_awaited_once()
        assert "📊 Аналітика" in cb.message.edit_text.call_args[0][0]


class TestAdminStats:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_stats

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_stats(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_stats(self):
        from bot.handlers.admin.panel import admin_stats

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.count_total_users", new_callable=AsyncMock, return_value=100),
            patch("bot.handlers.admin.panel.count_active_users", new_callable=AsyncMock, return_value=80),
            patch("bot.handlers.admin.panel.get_admin_analytics_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_stats(cb, session)

        text = cb.message.edit_text.call_args[0][0]
        assert "100" in text
        assert "80" in text
        assert "20" in text  # inactive


class TestAdminUsers:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_users

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_users(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_users_menu(self):
        from bot.handlers.admin.panel import admin_users

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_users_menu_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_users(cb)

        cb.message.edit_text.assert_awaited_once()


class TestAdminUsersStats:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_users_stats

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_users_stats(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_stats_alert(self):
        from bot.handlers.admin.panel import admin_users_stats

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.count_total_users", new_callable=AsyncMock, return_value=10),
            patch("bot.handlers.admin.panel.count_active_users", new_callable=AsyncMock, return_value=7),
        ):
            ms.is_admin.return_value = True
            await admin_users_stats(cb, session)

        args, kwargs = cb.answer.call_args
        assert show_alert_was_set((args, kwargs))
        assert "10" in args[0]


class TestAdminUsersList:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_users_list

        cb = _make_callback(user_id=999, data="admin_users_list_1")
        session = _make_session()
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_users_list(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_users(self):
        from bot.handlers.admin.panel import admin_users_list

        cb = _make_callback(data="admin_users_list_1")
        session = _make_session()
        user = SimpleNamespace(telegram_id=123, username="user1", region="kyiv", queue="1.1", is_active=True)
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_recent_users", new_callable=AsyncMock, return_value=[user]),
            patch("bot.handlers.admin.panel.get_users_menu_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_users_list(cb, session)

        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "user1" in text


class TestAdminSettingsMenu:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_settings_menu

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_settings_menu(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_settings_keyboard(self):
        from bot.handlers.admin.panel import admin_settings_menu

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_admin_settings_menu_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_settings_menu(cb)

        cb.message.edit_text.assert_awaited_once()


class TestAdminSystem:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.panel import admin_system

        cb = _make_callback(user_id=999)
        with patch("bot.handlers.admin.panel.settings") as ms:
            ms.is_admin.return_value = False
            await admin_system(cb)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_system_info(self):
        from bot.handlers.admin.panel import admin_system

        cb = _make_callback()
        with (
            patch("bot.handlers.admin.panel.settings") as ms,
            patch("bot.handlers.admin.panel.get_admin_settings_menu_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await admin_system(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Python" in text
        assert "Uptime" in text


# ===========================================================================
# pause.py
# ===========================================================================

class TestAdminPause:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import admin_pause

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await admin_pause(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_paused(self):
        from bot.handlers.admin.pause import admin_pause

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="true"),
            patch("bot.handlers.admin.pause.get_pause_menu_keyboard", return_value=MagicMock()) as mk,
        ):
            ms.is_admin.return_value = True
            await admin_pause(cb, session)

        mk.assert_called_once_with(is_paused=True)

    async def test_not_paused(self):
        from bot.handlers.admin.pause import admin_pause

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.pause.get_pause_menu_keyboard", return_value=MagicMock()) as mk,
        ):
            ms.is_admin.return_value = True
            await admin_pause(cb, session)

        mk.assert_called_once_with(is_paused=False)


class TestPauseStatus:
    async def test_paused_answer(self):
        from bot.handlers.admin.pause import pause_status

        cb = _make_callback()
        session = _make_session()
        with patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="true"):
            await pause_status(cb, session)

        cb.answer.assert_awaited_once_with("🔴 На паузі")

    async def test_active_answer(self):
        from bot.handlers.admin.pause import pause_status

        cb = _make_callback()
        session = _make_session()
        with patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"):
            await pause_status(cb, session)

        cb.answer.assert_awaited_once_with("🟢 Активний")


class TestPauseToggle:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_toggle

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_toggle(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_toggle_paused_to_active(self):
        from bot.handlers.admin.pause import pause_toggle

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="true"),
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.add_pause_log", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_pause_menu_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_toggle(cb, session)

        cb.answer.assert_awaited_once_with("🟢 Пауза вимкнена")

    async def test_toggle_active_to_paused(self):
        from bot.handlers.admin.pause import pause_toggle

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.add_pause_log", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_pause_menu_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_toggle(cb, session)

        cb.answer.assert_awaited_once_with("🔴 Пауза увімкнена")


class TestPauseMessageSettings:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_message_settings

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_message_settings(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_message_keyboard(self):
        from bot.handlers.admin.pause import pause_message_settings

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.pause.get_pause_message_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_message_settings(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestPauseTemplate:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_template

        cb = _make_callback(user_id=999, data="pause_template_1")
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_template(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_valid_template_saves(self):
        from bot.handlers.admin.pause import pause_template

        cb = _make_callback(data="pause_template_2")
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.pause.get_pause_message_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_template(cb, session)

        cb.answer.assert_awaited_once()
        cb.message.edit_reply_markup.assert_awaited_once()

    async def test_unknown_template_uses_default(self):
        from bot.handlers.admin.pause import pause_template

        cb = _make_callback(data="pause_template_99")
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.pause.get_pause_message_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_template(cb, session)

        # template "99" not found → falls back to template "1"
        _, kwargs = mock_set.call_args
        saved_msg = mock_set.call_args[0][2]
        assert saved_msg  # some non-empty message was saved


class TestPauseCustomMessage:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_custom_message

        cb = _make_callback(user_id=999)
        state = _make_state()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_custom_message(cb, state)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_sets_waiting_state(self):
        from bot.handlers.admin.pause import pause_custom_message

        cb = _make_callback()
        state = _make_state()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = True
            await pause_custom_message(cb, state)

        state.set_state.assert_awaited_once()
        cb.message.edit_text.assert_awaited_once()


class TestPauseCustomMessageInput:
    async def test_not_admin_clears_state(self):
        from bot.handlers.admin.pause import pause_custom_message_input

        msg = _make_message(user_id=999)
        state = _make_state()
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_custom_message_input(msg, state, session)

        state.clear.assert_awaited_once()

    async def test_no_text_replies_error(self):
        from bot.handlers.admin.pause import pause_custom_message_input

        msg = _make_message(text=None)
        state = _make_state()
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = True
            await pause_custom_message_input(msg, state, session)

        msg.reply.assert_awaited_once()
        state.clear.assert_not_awaited()

    async def test_valid_text_saves(self):
        from bot.handlers.admin.pause import pause_custom_message_input

        msg = _make_message(text="Custom pause message")
        state = _make_state()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="false"),
            patch("bot.handlers.admin.pause.get_pause_message_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_custom_message_input(msg, state, session)

        state.clear.assert_awaited_once()
        msg.answer.assert_awaited_once()


class TestPauseToggleSupport:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_toggle_support

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_toggle_support(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_toggle_support_false_to_true(self):
        from bot.handlers.admin.pause import pause_toggle_support

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, side_effect=["false", ""]),
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock) as mock_set,
            patch("bot.handlers.admin.pause.get_pause_message_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_toggle_support(cb, session)

        mock_set.assert_awaited_once_with(session, "pause_show_support", "true")
        cb.answer.assert_awaited_once_with("✅ Збережено")


class TestPauseTypeSelect:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_type_select

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_type_select(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_shows_type_keyboard(self):
        from bot.handlers.admin.pause import pause_type_select

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="update"),
            patch("bot.handlers.admin.pause.get_pause_type_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_type_select(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestPauseTypeSet:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_type_set

        cb = _make_callback(user_id=999, data="pause_type_update")
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_type_set(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_select_returns_early(self):
        from bot.handlers.admin.pause import pause_type_set

        cb = _make_callback(data="pause_type_select")
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = True
            await pause_type_set(cb, session)

        cb.answer.assert_not_awaited()
        cb.message.edit_reply_markup.assert_not_awaited()

    async def test_valid_type_saves(self):
        from bot.handlers.admin.pause import pause_type_set

        cb = _make_callback(data="pause_type_maintenance")
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_pause_type_keyboard", return_value=MagicMock()),
        ):
            ms.is_admin.return_value = True
            await pause_type_set(cb, session)

        cb.answer.assert_awaited_once_with("✅ Тип: maintenance")
        cb.message.edit_reply_markup.assert_awaited_once()


class TestPauseLog:
    async def test_not_admin_denied(self):
        from bot.handlers.admin.pause import pause_log

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_admin.return_value = False
            await pause_log(cb, session)

        cb.answer.assert_awaited_once_with("❌ Доступ заборонено")

    async def test_empty_logs(self):
        from bot.handlers.admin.pause import pause_log

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_pause_logs", new_callable=AsyncMock, return_value=[]),
        ):
            ms.is_admin.return_value = True
            await pause_log(cb, session)

        cb.message.edit_text.assert_awaited_once_with("📜 Лог паузи порожній")

    async def test_with_logs(self):
        from datetime import datetime

        from bot.handlers.admin.pause import pause_log

        cb = _make_callback()
        session = _make_session()
        log_entry = SimpleNamespace(
            event_type="pause_on",
            pause_type="update",
            created_at=datetime(2024, 1, 1, 12, 0),
        )
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_pause_logs", new_callable=AsyncMock, return_value=[log_entry]),
        ):
            ms.is_admin.return_value = True
            await pause_log(cb, session)

        text = cb.message.edit_text.call_args[0][0]
        assert "pause_on" in text


class TestAdminDebounce:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.pause import admin_debounce

        cb = _make_callback(user_id=999)
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_owner.return_value = False
            await admin_debounce(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_shows_debounce_keyboard(self):
        from bot.handlers.admin.pause import admin_debounce

        cb = _make_callback()
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.handlers.admin.pause.get_setting", new_callable=AsyncMock, return_value="5"),
            patch("bot.handlers.admin.pause.get_debounce_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await admin_debounce(cb, session)

        cb.message.edit_text.assert_awaited_once()


class TestDebounceSet:
    async def test_not_owner_denied(self):
        from bot.handlers.admin.pause import debounce_set

        cb = _make_callback(user_id=999, data="debounce_set_5")
        session = _make_session()
        with patch("bot.handlers.admin.pause.settings") as ms:
            ms.is_owner.return_value = False
            await debounce_set(cb, session)

        assert "Доступ заборонено" in cb.answer.call_args[0][0]

    async def test_invalid_value_just_answers(self):
        from bot.handlers.admin.pause import debounce_set

        cb = _make_callback(data="debounce_set_bad")
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.utils.helpers.safe_parse_callback_int", return_value=None),
        ):
            ms.is_owner.return_value = True
            await debounce_set(cb, session)

        cb.answer.assert_awaited_once_with()

    async def test_zero_saves_disabled(self):
        from bot.handlers.admin.pause import debounce_set

        cb = _make_callback(data="debounce_set_0")
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.utils.helpers.safe_parse_callback_int", return_value=0),
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_debounce_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await debounce_set(cb, session)

        cb.answer.assert_awaited_once_with("✅ Debounce: Вимкнено")

    async def test_nonzero_saves_minutes(self):
        from bot.handlers.admin.pause import debounce_set

        cb = _make_callback(data="debounce_set_10")
        session = _make_session()
        with (
            patch("bot.handlers.admin.pause.settings") as ms,
            patch("bot.utils.helpers.safe_parse_callback_int", return_value=10),
            patch("bot.handlers.admin.pause.set_setting", new_callable=AsyncMock),
            patch("bot.handlers.admin.pause.get_debounce_keyboard", return_value=MagicMock()),
        ):
            ms.is_owner.return_value = True
            await debounce_set(cb, session)

        cb.answer.assert_awaited_once_with("✅ Debounce: 10 хв")


# ---------------------------------------------------------------------------
# Utility used by some tests
# ---------------------------------------------------------------------------

def show_alert_was_set(call_args) -> bool:
    """Return True if show_alert=True was passed in the call."""
    args, kwargs = call_args
    return kwargs.get("show_alert") is True
