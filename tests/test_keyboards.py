"""Comprehensive tests for all keyboard modules and formatter/template.py."""
from __future__ import annotations

import re
from datetime import datetime

import pytest

# ─── admin keyboards ──────────────────────────────────────────────────────

from bot.keyboards.admin import (
    get_admin_analytics_keyboard,
    get_admin_intervals_keyboard,
    get_admin_keyboard,
    get_admin_router_keyboard,
    get_admin_settings_menu_keyboard,
    get_broadcast_cancel_keyboard,
    get_chart_preview_keyboard,
    get_chart_render_mode_keyboard,
    get_debounce_keyboard,
    get_growth_keyboard,
    get_growth_registration_keyboard,
    get_growth_stage_keyboard,
    get_ip_interval_keyboard,
    get_maintenance_keyboard,
    get_pause_menu_keyboard,
    get_pause_message_keyboard,
    get_pause_type_keyboard,
    get_refresh_cooldown_keyboard,
    get_restart_confirm_keyboard,
    get_schedule_interval_keyboard,
    get_users_menu_keyboard,
)

# ─── channel keyboards ────────────────────────────────────────────────────

from bot.keyboards.channel import (
    get_channel_connect_confirm_keyboard,
    get_channel_menu_keyboard,
    get_channel_pending_confirm_keyboard,
    get_channel_replace_confirm_keyboard,
)

# ─── common helpers ───────────────────────────────────────────────────────

from bot.keyboards.common import (
    _btn,
    _nav_row,
    _url_btn,
    _url_btn_with_emoji,
    get_error_keyboard,
    get_understood_keyboard,
)

# ─── format keyboards ─────────────────────────────────────────────────────

from bot.keyboards.format import (
    get_format_power_keyboard,
    get_format_schedule_keyboard,
    get_format_settings_keyboard,
    get_test_publication_keyboard,
)

# ─── help keyboards ───────────────────────────────────────────────────────

from bot.keyboards.help import (
    get_faq_keyboard,
    get_help_keyboard,
    get_instruction_section_keyboard,
    get_instructions_keyboard,
    get_support_keyboard,
)

# ─── ip keyboards ─────────────────────────────────────────────────────────

from bot.keyboards.ip import (
    get_ip_change_confirm_keyboard,
    get_ip_delete_confirm_keyboard,
    get_ip_deleted_keyboard,
    get_ip_management_keyboard,
    get_ip_monitoring_keyboard_no_ip,
    get_ip_ping_error_keyboard,
    get_ip_ping_fail_keyboard,
    get_ip_ping_result_keyboard,
    get_ip_saved_fail_keyboard,
    get_ip_saved_keyboard,
    get_ip_saved_success_keyboard,
)

# ─── main_menu keyboards ──────────────────────────────────────────────────

from bot.keyboards.main_menu import (
    get_main_menu,
    get_restoration_keyboard,
    get_statistics_keyboard,
)

# ─── notifications keyboards ──────────────────────────────────────────────

from bot.keyboards.notifications import (
    get_channel_notification_keyboard,
    get_notification_main_keyboard,
    get_notification_reminders_keyboard,
    get_notification_select_keyboard,
    get_notification_target_select_keyboard,
    get_notification_targets_keyboard,
    get_reminder_keyboard,
)

# ─── schedule keyboard ────────────────────────────────────────────────────

from bot.keyboards.schedule import get_schedule_view_keyboard

# ─── settings keyboards ───────────────────────────────────────────────────

from bot.keyboards.settings import (
    get_cleanup_keyboard,
    get_deactivate_confirm_keyboard,
    get_delete_data_confirm_keyboard,
    get_delete_data_final_keyboard,
    get_settings_keyboard,
)

# ─── wizard keyboards ─────────────────────────────────────────────────────

from bot.keyboards.wizard import (
    get_confirm_keyboard,
    get_queue_keyboard,
    get_region_keyboard,
    get_wizard_bot_notification_keyboard,
    get_wizard_channel_notification_keyboard,
    get_wizard_notify_target_keyboard,
)

# ─── formatter ────────────────────────────────────────────────────────────

from bot.formatter.template import format_template, get_current_datetime_for_template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_buttons(kb):
    """Flatten all InlineKeyboardButton objects from a keyboard markup."""
    return [btn for row in kb.inline_keyboard for btn in row]


def _callback_data_set(kb):
    """Return set of all callback_data strings in the keyboard."""
    return {btn.callback_data for btn in _all_buttons(kb) if btn.callback_data}


# ===========================================================================
# common.py
# ===========================================================================


class TestCommonHelpers:
    def test_btn_basic(self):
        btn = _btn("Label", "cb_data")
        assert btn.text == "Label"
        assert btn.callback_data == "cb_data"

    def test_btn_with_style(self):
        btn = _btn("Label", "cb_data", style="success")
        assert btn.callback_data == "cb_data"

    def test_btn_with_emoji(self):
        btn = _btn("Label", "cb_data", emoji_id="12345")
        assert btn.callback_data == "cb_data"

    def test_url_btn(self):
        btn = _url_btn("Link", "https://example.com")
        assert btn.text == "Link"
        assert btn.url == "https://example.com"
        assert btn.callback_data is None

    def test_url_btn_with_emoji_no_emoji(self):
        btn = _url_btn_with_emoji("Link", "https://example.com")
        assert btn.url == "https://example.com"

    def test_url_btn_with_emoji_has_emoji(self):
        btn = _url_btn_with_emoji("Link", "https://example.com", emoji_id="9999")
        assert btn.url == "https://example.com"

    def test_nav_row_both(self):
        row = _nav_row("back_cb")
        assert len(row) == 2
        assert row[0].callback_data == "back_cb"
        assert row[1].callback_data == "back_to_main"

    def test_nav_row_no_back(self):
        row = _nav_row(None)
        assert len(row) == 1
        assert row[0].callback_data == "back_to_main"

    def test_nav_row_no_menu(self):
        row = _nav_row("some_cb", menu=False)
        assert len(row) == 1
        assert row[0].callback_data == "some_cb"

    def test_nav_row_neither(self):
        row = _nav_row(None, menu=False)
        assert len(row) == 0

    def test_get_error_keyboard(self):
        kb = get_error_keyboard()
        cbs = _callback_data_set(kb)
        assert "back_to_main" in cbs

    def test_get_understood_keyboard(self):
        kb = get_understood_keyboard()
        cbs = _callback_data_set(kb)
        assert "reminder_dismiss" in cbs


# ===========================================================================
# admin.py
# ===========================================================================


class TestAdminKeyboard:
    def test_get_admin_keyboard_structure(self):
        kb = get_admin_keyboard()
        cbs = _callback_data_set(kb)
        assert "admin_analytics" in cbs
        assert "admin_users" in cbs
        assert "admin_broadcast" in cbs
        assert "admin_settings_menu" in cbs
        assert "admin_router" in cbs
        assert "admin_maintenance" in cbs
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs

    def test_get_admin_analytics_keyboard(self):
        kb = get_admin_analytics_keyboard()
        cbs = _callback_data_set(kb)
        assert "admin_stats" in cbs
        assert "admin_growth" in cbs
        assert "admin_menu" in cbs
        assert "back_to_main" in cbs

    def test_get_admin_settings_menu_keyboard(self):
        kb = get_admin_settings_menu_keyboard()
        cbs = _callback_data_set(kb)
        assert "admin_system" in cbs
        assert "admin_intervals" in cbs
        assert "admin_debounce" in cbs
        assert "admin_pause" in cbs
        assert "admin_refresh_cooldown" in cbs
        assert "admin_chart_render" in cbs
        assert "admin_clear_db" in cbs
        assert "admin_restart" in cbs

    def test_get_chart_render_mode_default(self):
        kb = get_chart_render_mode_keyboard()
        btns = _all_buttons(kb)
        on_change_btn = next(b for b in btns if b.callback_data == "chart_render_mode_on_change")
        assert "✅" in on_change_btn.text

    def test_get_chart_render_mode_on_demand_selected(self):
        kb = get_chart_render_mode_keyboard(current_mode="on_demand")
        btns = _all_buttons(kb)
        on_demand_btn = next(b for b in btns if b.callback_data == "chart_render_mode_on_demand")
        on_change_btn = next(b for b in btns if b.callback_data == "chart_render_mode_on_change")
        assert "✅" in on_demand_btn.text
        assert "✅" not in on_change_btn.text

    def test_get_chart_render_mode_contains_preview(self):
        kb = get_chart_render_mode_keyboard()
        cbs = _callback_data_set(kb)
        assert "chart_preview_menu" in cbs
        assert "admin_settings_menu" in cbs

    def test_get_chart_preview_keyboard(self):
        kb = get_chart_preview_keyboard()
        cbs = _callback_data_set(kb)
        assert "chart_preview:two_outages" in cbs
        assert "chart_preview:three_outages" in cbs
        assert "chart_preview:allday" in cbs
        assert "chart_preview:halfhour" in cbs
        assert "admin_chart_render" in cbs

    def test_get_refresh_cooldown_default(self):
        kb = get_refresh_cooldown_keyboard()
        cbs = _callback_data_set(kb)
        for secs in [5, 10, 20, 30, 60]:
            assert f"admin_cooldown_set_{secs}" in cbs
        btns = _all_buttons(kb)
        btn_30 = next(b for b in btns if b.callback_data == "admin_cooldown_set_30")
        assert btn_30.text == "30 сек"

    def test_get_refresh_cooldown_custom_selected(self):
        kb = get_refresh_cooldown_keyboard(current_seconds=10)
        btns = _all_buttons(kb)
        btn_10 = next(b for b in btns if b.callback_data == "admin_cooldown_set_10")
        assert btn_10.text == "10 сек"

    def test_get_maintenance_keyboard_disabled(self):
        kb = get_maintenance_keyboard(enabled=False)
        btns = _all_buttons(kb)
        toggle_btn = next(b for b in btns if b.callback_data == "maintenance_toggle")
        assert "Увімкнути" in toggle_btn.text

    def test_get_maintenance_keyboard_enabled(self):
        kb = get_maintenance_keyboard(enabled=True)
        btns = _all_buttons(kb)
        toggle_btn = next(b for b in btns if b.callback_data == "maintenance_toggle")
        assert "Вимкнути" in toggle_btn.text

    def test_get_maintenance_keyboard_contains_edit(self):
        kb = get_maintenance_keyboard()
        cbs = _callback_data_set(kb)
        assert "maintenance_edit_message" in cbs

    def test_get_admin_intervals_keyboard_defaults(self):
        kb = get_admin_intervals_keyboard()
        cbs = _callback_data_set(kb)
        assert "admin_interval_schedule" in cbs
        assert "admin_interval_ip" in cbs

    def test_get_admin_intervals_keyboard_custom_values(self):
        kb = get_admin_intervals_keyboard(schedule_interval=120, ip_interval=5)
        btns = _all_buttons(kb)
        sched_btn = next(b for b in btns if b.callback_data == "admin_interval_schedule")
        assert "2 хв" in sched_btn.text
        ip_btn = next(b for b in btns if b.callback_data == "admin_interval_ip")
        assert "5" in ip_btn.text

    def test_get_schedule_interval_keyboard_defaults(self):
        kb = get_schedule_interval_keyboard()
        cbs = _callback_data_set(kb)
        for m in [3, 5, 10, 15]:
            assert f"admin_schedule_{m}" in cbs

    def test_get_schedule_interval_keyboard_selected(self):
        kb = get_schedule_interval_keyboard(current_seconds=300)  # 5 minutes
        btns = _all_buttons(kb)
        btn_5 = next(b for b in btns if b.callback_data == "admin_schedule_5")
        assert "5 хв" in btn_5.text

    def test_get_ip_interval_keyboard_defaults(self):
        kb = get_ip_interval_keyboard()
        cbs = _callback_data_set(kb)
        for secs in [10, 30, 60, 120, 0]:
            assert f"admin_ip_{secs}" in cbs

    def test_get_ip_interval_keyboard_dynamic_selected(self):
        kb = get_ip_interval_keyboard(current_seconds=0)
        btns = _all_buttons(kb)
        btn_dyn = next(b for b in btns if b.callback_data == "admin_ip_0")
        assert "Динамічний" in btn_dyn.text

    def test_get_ip_interval_keyboard_value_selected(self):
        kb = get_ip_interval_keyboard(current_seconds=60)
        btns = _all_buttons(kb)
        btn_60 = next(b for b in btns if b.callback_data == "admin_ip_60")
        assert "1 хв" in btn_60.text

    def test_get_debounce_keyboard_default(self):
        kb = get_debounce_keyboard()
        cbs = _callback_data_set(kb)
        assert "debounce_set_0" in cbs
        for v in [1, 2, 3, 5, 10, 15]:
            assert f"debounce_set_{v}" in cbs

    def test_get_debounce_keyboard_selected_value(self):
        kb = get_debounce_keyboard(current_value=5)
        btns = _all_buttons(kb)
        btn_5 = next(b for b in btns if b.callback_data == "debounce_set_5")
        assert "5 хв" in btn_5.text

    def test_get_pause_menu_keyboard_not_paused(self):
        kb = get_pause_menu_keyboard(is_paused=False)
        cbs = _callback_data_set(kb)
        assert "pause_toggle" in cbs
        assert "pause_status" in cbs
        assert "pause_message_settings" in cbs
        assert "pause_log" in cbs
        # pause_type_select should NOT appear when not paused
        assert "pause_type_select" not in cbs

    def test_get_pause_menu_keyboard_paused(self):
        kb = get_pause_menu_keyboard(is_paused=True)
        cbs = _callback_data_set(kb)
        assert "pause_type_select" in cbs
        # When paused: toggle should say "Вимкнути"
        btns = _all_buttons(kb)
        toggle_btn = next(b for b in btns if b.callback_data == "pause_toggle")
        assert "Вимкнути" in toggle_btn.text

    def test_get_pause_type_keyboard_default(self):
        kb = get_pause_type_keyboard()
        cbs = _callback_data_set(kb)
        for t in ["update", "emergency", "maintenance", "testing"]:
            assert f"pause_type_{t}" in cbs

    def test_get_pause_type_keyboard_selected(self):
        kb = get_pause_type_keyboard(current_type="emergency")
        btns = _all_buttons(kb)
        em_btn = next(b for b in btns if b.callback_data == "pause_type_emergency")
        assert em_btn.style == "success"
        up_btn = next(b for b in btns if b.callback_data == "pause_type_update")
        assert up_btn.style is None

    def test_get_pause_message_keyboard_no_current(self):
        kb = get_pause_message_keyboard()
        cbs = _callback_data_set(kb)
        for i in range(1, 6):
            assert f"pause_template_{i}" in cbs
        assert "pause_custom_message" in cbs
        assert "pause_toggle_support" in cbs

    def test_get_pause_message_keyboard_template_selected(self):
        template_text = "🔧 Бот тимчасово недоступний. Спробуйте пізніше."
        kb = get_pause_message_keyboard(current_message=template_text)
        btns = _all_buttons(kb)
        t1_btn = next(b for b in btns if b.callback_data == "pause_template_1")
        assert t1_btn.text == template_text

    def test_get_pause_message_keyboard_custom_selected(self):
        kb = get_pause_message_keyboard(current_message="Custom message not in templates")
        btns = _all_buttons(kb)
        custom_btn = next(b for b in btns if b.callback_data == "pause_custom_message")
        assert custom_btn.text == "✏️ Свій текст..."

    def test_get_pause_message_keyboard_show_support_button(self):
        kb = get_pause_message_keyboard(show_support_button=True)
        assert isinstance(kb.inline_keyboard, list)

    def test_get_growth_keyboard(self):
        kb = get_growth_keyboard()
        cbs = _callback_data_set(kb)
        assert "growth_metrics" in cbs
        assert "growth_stage" in cbs
        assert "growth_registration" in cbs
        assert "growth_events" in cbs
        assert "admin_analytics" in cbs

    def test_get_growth_stage_keyboard_default(self):
        kb = get_growth_stage_keyboard()
        cbs = _callback_data_set(kb)
        for s in range(5):
            assert f"growth_stage_{s}" in cbs

    def test_get_growth_stage_keyboard_selected(self):
        kb = get_growth_stage_keyboard(current_stage=2)
        btns = _all_buttons(kb)
        btn_2 = next(b for b in btns if b.callback_data == "growth_stage_2")
        assert btn_2.style == "success"
        btn_0 = next(b for b in btns if b.callback_data == "growth_stage_0")
        assert btn_0.style is None

    def test_get_growth_registration_keyboard_enabled(self):
        kb = get_growth_registration_keyboard(enabled=True)
        btns = _all_buttons(kb)
        status_btn = next(b for b in btns if b.callback_data == "growth_reg_status")
        assert "увімкнена" in status_btn.text
        toggle_btn = next(b for b in btns if b.callback_data == "growth_reg_toggle")
        assert "Вимкнути" in toggle_btn.text

    def test_get_growth_registration_keyboard_disabled(self):
        kb = get_growth_registration_keyboard(enabled=False)
        btns = _all_buttons(kb)
        status_btn = next(b for b in btns if b.callback_data == "growth_reg_status")
        assert "вимкнена" in status_btn.text
        toggle_btn = next(b for b in btns if b.callback_data == "growth_reg_toggle")
        assert "Увімкнути" in toggle_btn.text

    def test_get_restart_confirm_keyboard(self):
        kb = get_restart_confirm_keyboard()
        cbs = _callback_data_set(kb)
        assert "admin_restart_confirm" in cbs
        assert "admin_settings_menu" in cbs

    def test_get_users_menu_keyboard(self):
        kb = get_users_menu_keyboard()
        cbs = _callback_data_set(kb)
        assert "admin_users_stats" in cbs
        assert "admin_users_list_1" in cbs
        assert "admin_menu" in cbs

    def test_get_admin_router_keyboard_no_ip(self):
        kb = get_admin_router_keyboard(has_ip=False)
        cbs = _callback_data_set(kb)
        assert "admin_router_set_ip" in cbs
        assert "admin_router_toggle_notify" not in cbs

    def test_get_admin_router_keyboard_has_ip_notifications_on(self):
        kb = get_admin_router_keyboard(has_ip=True, notifications_on=True)
        cbs = _callback_data_set(kb)
        assert "admin_router_set_ip" in cbs
        assert "admin_router_toggle_notify" in cbs
        assert "admin_router_stats" in cbs
        assert "admin_router_refresh" in cbs
        btns = _all_buttons(kb)
        notif_btn = next(b for b in btns if b.callback_data == "admin_router_toggle_notify")
        assert "✓" in notif_btn.text

    def test_get_admin_router_keyboard_has_ip_notifications_off(self):
        kb = get_admin_router_keyboard(has_ip=True, notifications_on=False)
        btns = _all_buttons(kb)
        notif_btn = next(b for b in btns if b.callback_data == "admin_router_toggle_notify")
        assert "✗" in notif_btn.text

    def test_get_broadcast_cancel_keyboard(self):
        kb = get_broadcast_cancel_keyboard()
        cbs = _callback_data_set(kb)
        assert "broadcast_cancel" in cbs
        assert len(kb.inline_keyboard) == 1


# ===========================================================================
# channel.py
# ===========================================================================


class TestChannelKeyboards:
    def test_get_channel_pending_confirm_keyboard(self):
        kb = get_channel_pending_confirm_keyboard("ch123")
        cbs = _callback_data_set(kb)
        assert "channel_confirm_ch123" in cbs
        assert "settings_channel" in cbs

    def test_get_channel_connect_confirm_keyboard(self):
        kb = get_channel_connect_confirm_keyboard("ch456")
        cbs = _callback_data_set(kb)
        assert "connect_channel_ch456" in cbs
        assert "cancel_channel_connect" in cbs

    def test_get_channel_replace_confirm_keyboard(self):
        kb = get_channel_replace_confirm_keyboard("ch789")
        cbs = _callback_data_set(kb)
        assert "replace_channel_ch789" in cbs
        assert "keep_current_channel" in cbs

    def test_get_channel_menu_keyboard_no_channel(self):
        kb = get_channel_menu_keyboard(channel_id=None)
        cbs = _callback_data_set(kb)
        assert "channel_connect" in cbs
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs
        assert "channel_info" not in cbs

    def test_get_channel_menu_keyboard_with_channel_active(self):
        kb = get_channel_menu_keyboard(channel_id="ch001", channel_status="active")
        cbs = _callback_data_set(kb)
        assert "channel_info" in cbs
        assert "channel_edit_title" in cbs
        assert "channel_edit_description" in cbs
        assert "channel_format" in cbs
        assert "channel_test" in cbs
        assert "channel_disable" in cbs
        assert "channel_notifications" in cbs

    def test_get_channel_menu_keyboard_with_channel_blocked(self):
        kb = get_channel_menu_keyboard(channel_id="ch001", channel_status="blocked")
        cbs = _callback_data_set(kb)
        assert "channel_reconnect" in cbs
        assert "channel_disable" not in cbs

    def test_get_channel_menu_keyboard_public_with_username(self):
        kb = get_channel_menu_keyboard(
            channel_id="ch001", is_public=True, channel_username="mychannel"
        )
        btns = _all_buttons(kb)
        url_btn = next((b for b in btns if b.url is not None), None)
        assert url_btn is not None
        assert "mychannel" in url_btn.url

    def test_get_channel_menu_keyboard_public_no_username(self):
        kb = get_channel_menu_keyboard(
            channel_id="ch001", is_public=True, channel_username=None
        )
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 0

    def test_get_channel_menu_keyboard_private_with_username(self):
        kb = get_channel_menu_keyboard(
            channel_id="ch001", is_public=False, channel_username="mychannel"
        )
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 0


# ===========================================================================
# format.py
# ===========================================================================


class TestFormatKeyboards:
    def test_get_format_settings_keyboard(self):
        kb = get_format_settings_keyboard()
        cbs = _callback_data_set(kb)
        assert "format_schedule_settings" in cbs
        assert "format_power_settings" in cbs
        assert "settings_channel" in cbs
        assert "back_to_main" in cbs

    def test_get_format_schedule_keyboard_defaults(self):
        kb = get_format_schedule_keyboard()
        cbs = _callback_data_set(kb)
        assert "format_schedule_text" in cbs
        assert "format_toggle_delete" in cbs
        assert "format_toggle_piconly" in cbs

    def test_get_format_schedule_keyboard_delete_old_true(self):
        kb = get_format_schedule_keyboard(delete_old=True)
        assert isinstance(kb.inline_keyboard, list)

    def test_get_format_schedule_keyboard_picture_only_true(self):
        kb = get_format_schedule_keyboard(picture_only=True)
        assert isinstance(kb.inline_keyboard, list)

    def test_get_format_schedule_keyboard_both_true(self):
        kb = get_format_schedule_keyboard(delete_old=True, picture_only=True)
        assert isinstance(kb.inline_keyboard, list)

    def test_get_format_power_keyboard(self):
        kb = get_format_power_keyboard()
        cbs = _callback_data_set(kb)
        assert "format_power_off" in cbs
        assert "format_power_on" in cbs
        assert "format_reset_all_power" in cbs
        assert "format_menu" in cbs

    def test_get_test_publication_keyboard(self):
        kb = get_test_publication_keyboard()
        cbs = _callback_data_set(kb)
        assert "test_schedule" in cbs
        assert "test_power_on" in cbs
        assert "test_power_off" in cbs
        assert "test_custom" in cbs
        assert "settings_channel" in cbs


# ===========================================================================
# help.py
# ===========================================================================


class TestHelpKeyboards:
    def test_get_help_keyboard_no_urls(self):
        kb = get_help_keyboard()
        cbs = _callback_data_set(kb)
        assert "help_instructions" in cbs
        assert "back_to_main" in cbs
        # FAQ and support buttons should not appear
        assert "help_faq" not in cbs
        assert "help_support" not in cbs

    def test_get_help_keyboard_with_faq_url(self):
        kb = get_help_keyboard(faq_url="https://faq.example.com")
        cbs = _callback_data_set(kb)
        assert "help_faq" in cbs
        assert "help_support" not in cbs

    def test_get_help_keyboard_with_support_url(self):
        kb = get_help_keyboard(support_url="https://support.example.com")
        cbs = _callback_data_set(kb)
        assert "help_support" in cbs
        assert "help_faq" not in cbs

    def test_get_help_keyboard_with_both_urls(self):
        kb = get_help_keyboard(faq_url="https://faq.example.com", support_url="https://support.example.com")
        cbs = _callback_data_set(kb)
        assert "help_faq" in cbs
        assert "help_support" in cbs

    def test_get_help_keyboard_has_url_buttons(self):
        kb = get_help_keyboard()
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) >= 2  # Новини and Обговорення

    def test_get_faq_keyboard_no_url(self):
        kb = get_faq_keyboard()
        cbs = _callback_data_set(kb)
        assert "menu_help" in cbs
        assert "back_to_main" in cbs
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 0

    def test_get_faq_keyboard_with_url(self):
        kb = get_faq_keyboard(faq_url="https://faq.example.com")
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 1
        assert "faq.example.com" in url_btns[0].url

    def test_get_support_keyboard_no_url(self):
        kb = get_support_keyboard()
        cbs = _callback_data_set(kb)
        assert "menu_help" in cbs
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 0

    def test_get_support_keyboard_with_url(self):
        kb = get_support_keyboard(support_url="https://support.example.com")
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 1
        assert "support.example.com" in url_btns[0].url

    def test_get_instructions_keyboard(self):
        kb = get_instructions_keyboard()
        cbs = _callback_data_set(kb)
        assert "instr_region" in cbs
        assert "instr_notif" in cbs
        assert "instr_channel" in cbs
        assert "instr_ip" in cbs
        assert "instr_schedule" in cbs
        assert "instr_bot_settings" in cbs
        assert "menu_help" in cbs

    def test_get_instruction_section_keyboard(self):
        kb = get_instruction_section_keyboard()
        cbs = _callback_data_set(kb)
        assert "help_instructions" in cbs
        assert "back_to_main" in cbs


# ===========================================================================
# ip.py
# ===========================================================================


class TestIpKeyboards:
    def test_get_ip_monitoring_keyboard_no_ip(self):
        kb = get_ip_monitoring_keyboard_no_ip()
        cbs = _callback_data_set(kb)
        assert "ip_cancel_to_settings" in cbs
        assert len(kb.inline_keyboard) == 1

    def test_get_ip_management_keyboard(self):
        kb = get_ip_management_keyboard()
        cbs = _callback_data_set(kb)
        assert "ip_change" in cbs
        assert "ip_delete_confirm" in cbs
        assert "ip_ping_check" in cbs
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs

    def test_get_ip_change_confirm_keyboard(self):
        kb = get_ip_change_confirm_keyboard()
        cbs = _callback_data_set(kb)
        assert "ip_change_confirm" in cbs
        assert "ip_cancel_to_management" in cbs

    def test_get_ip_delete_confirm_keyboard(self):
        kb = get_ip_delete_confirm_keyboard()
        cbs = _callback_data_set(kb)
        assert "ip_delete_execute" in cbs
        assert "ip_cancel_to_management" in cbs

    def test_get_ip_deleted_keyboard(self):
        kb = get_ip_deleted_keyboard()
        cbs = _callback_data_set(kb)
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs

    def test_get_ip_saved_keyboard(self):
        kb = get_ip_saved_keyboard()
        cbs = _callback_data_set(kb)
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs

    def test_get_ip_saved_success_keyboard(self):
        kb = get_ip_saved_success_keyboard()
        cbs = _callback_data_set(kb)
        assert "settings_ip" in cbs
        assert "back_to_main" in cbs

    def test_get_ip_saved_fail_keyboard_no_support(self):
        kb = get_ip_saved_fail_keyboard()
        cbs = _callback_data_set(kb)
        assert "settings_ip" in cbs
        assert "back_to_main" in cbs
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 0

    def test_get_ip_saved_fail_keyboard_with_support(self):
        kb = get_ip_saved_fail_keyboard(support_url="https://support.example.com")
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 1
        assert "support.example.com" in url_btns[0].url

    def test_get_ip_ping_result_keyboard(self):
        kb = get_ip_ping_result_keyboard()
        cbs = _callback_data_set(kb)
        assert "settings_ip" in cbs
        assert "back_to_main" in cbs

    def test_get_ip_ping_fail_keyboard_no_support(self):
        kb = get_ip_ping_fail_keyboard()
        cbs = _callback_data_set(kb)
        assert "settings_ip" in cbs
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 0

    def test_get_ip_ping_fail_keyboard_with_support(self):
        kb = get_ip_ping_fail_keyboard(support_url="https://support.example.com")
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 1

    def test_get_ip_ping_error_keyboard_no_support(self):
        kb = get_ip_ping_error_keyboard()
        btns = _all_buttons(kb)
        assert len(btns) == 0

    def test_get_ip_ping_error_keyboard_with_support(self):
        kb = get_ip_ping_error_keyboard(support_url="https://support.example.com")
        btns = _all_buttons(kb)
        url_btns = [b for b in btns if b.url is not None]
        assert len(url_btns) == 1
        assert "support.example.com" in url_btns[0].url


# ===========================================================================
# main_menu.py
# ===========================================================================


class TestMainMenuKeyboards:
    def test_get_main_menu_defaults(self):
        kb = get_main_menu()
        cbs = _callback_data_set(kb)
        assert "menu_schedule" in cbs
        assert "menu_help" in cbs
        assert "settings_alerts" in cbs
        assert "settings_channel" in cbs
        assert "menu_settings" in cbs
        assert "channel_pause" not in cbs
        assert "channel_resume" not in cbs

    def test_get_main_menu_with_channel_not_paused(self):
        kb = get_main_menu(has_channel=True, channel_paused=False)
        cbs = _callback_data_set(kb)
        assert "channel_pause" in cbs
        assert "channel_resume" not in cbs

    def test_get_main_menu_with_channel_paused(self):
        kb = get_main_menu(has_channel=True, channel_paused=True)
        cbs = _callback_data_set(kb)
        assert "channel_resume" in cbs
        assert "channel_pause" not in cbs

    def test_get_main_menu_no_channel(self):
        kb = get_main_menu(has_channel=False)
        cbs = _callback_data_set(kb)
        assert "channel_pause" not in cbs
        assert "channel_resume" not in cbs

    def test_get_restoration_keyboard(self):
        kb = get_restoration_keyboard()
        cbs = _callback_data_set(kb)
        assert "restore_profile" in cbs
        assert "create_new_profile" in cbs

    def test_get_statistics_keyboard(self):
        kb = get_statistics_keyboard()
        cbs = _callback_data_set(kb)
        assert "stats_week" in cbs
        assert "stats_device" in cbs
        assert "stats_settings" in cbs
        assert "back_to_main" in cbs


# ===========================================================================
# notifications.py
# ===========================================================================


class TestNotificationsKeyboards:
    def test_get_reminder_keyboard(self):
        kb = get_reminder_keyboard()
        cbs = _callback_data_set(kb)
        assert "reminder_show_schedule" in cbs
        assert "reminder_dismiss" in cbs

    def test_get_notification_main_keyboard_defaults(self):
        kb = get_notification_main_keyboard()
        cbs = _callback_data_set(kb)
        assert "notif_toggle_schedule" in cbs
        assert "notif_time_60" in cbs
        assert "notif_time_30" in cbs
        assert "notif_time_15" in cbs
        assert "notif_toggle_fact_off" in cbs
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs

    def test_get_notification_main_keyboard_has_channel(self):
        kb = get_notification_main_keyboard(has_channel=True)
        cbs = _callback_data_set(kb)
        assert "notif_targets" in cbs

    def test_get_notification_main_keyboard_no_channel(self):
        kb = get_notification_main_keyboard(has_channel=False)
        cbs = _callback_data_set(kb)
        assert "notif_targets" not in cbs

    def test_get_notification_main_keyboard_custom_back(self):
        kb = get_notification_main_keyboard(back_cb="custom_back")
        cbs = _callback_data_set(kb)
        assert "custom_back" in cbs

    def test_get_notification_reminders_keyboard_defaults(self):
        kb = get_notification_reminders_keyboard()
        cbs = _callback_data_set(kb)
        assert "notif_toggle_remind_off" in cbs
        assert "notif_toggle_fact_off" in cbs
        assert "notif_toggle_remind_on" in cbs
        assert "notif_toggle_fact_on" in cbs
        assert "notif_time_15" in cbs
        assert "notif_time_30" in cbs
        assert "notif_time_60" in cbs

    def test_get_notification_reminders_keyboard_false_values(self):
        kb = get_notification_reminders_keyboard(
            remind_off=False, fact_off=False, remind_on=False, fact_on=False,
            remind_15m=False, remind_30m=False, remind_1h=False
        )
        assert isinstance(kb.inline_keyboard, list)

    def test_get_notification_targets_keyboard_no_ip(self):
        kb = get_notification_targets_keyboard(has_ip=False)
        cbs = _callback_data_set(kb)
        assert "notif_target_type_schedule" in cbs
        assert "notif_target_type_remind" in cbs
        assert "settings_ip" in cbs
        assert "notif_target_type_power" not in cbs

    def test_get_notification_targets_keyboard_has_ip(self):
        kb = get_notification_targets_keyboard(has_ip=True)
        cbs = _callback_data_set(kb)
        assert "notif_target_type_power" in cbs
        assert "settings_ip" not in cbs

    def test_get_notification_target_select_keyboard_bot_selected(self):
        kb = get_notification_target_select_keyboard("schedule", current_target="bot")
        cbs = _callback_data_set(kb)
        assert "notif_target_set_schedule_bot" in cbs
        assert "notif_target_set_schedule_channel" in cbs
        assert "notif_target_set_schedule_both" in cbs
        assert "notif_targets" in cbs

    def test_get_notification_target_select_keyboard_channel_selected(self):
        kb = get_notification_target_select_keyboard("remind", current_target="channel")
        cbs = _callback_data_set(kb)
        assert "notif_target_set_remind_bot" in cbs
        assert "notif_target_set_remind_channel" in cbs

    def test_get_notification_target_select_keyboard_both_selected(self):
        kb = get_notification_target_select_keyboard("power", current_target="both")
        cbs = _callback_data_set(kb)
        assert "notif_target_set_power_both" in cbs

    def test_get_notification_select_keyboard(self):
        kb = get_notification_select_keyboard()
        cbs = _callback_data_set(kb)
        assert "notif_select_bot" in cbs
        assert "notif_select_channel" in cbs
        assert "back_to_main" in cbs

    def test_get_channel_notification_keyboard_defaults(self):
        kb = get_channel_notification_keyboard()
        cbs = _callback_data_set(kb)
        assert "ch_notif_toggle_schedule" in cbs
        assert "ch_notif_time_60" in cbs
        assert "ch_notif_time_30" in cbs
        assert "ch_notif_time_15" in cbs
        assert "ch_notif_toggle_fact" in cbs
        assert "notif_main" in cbs
        assert "back_to_main" in cbs

    def test_get_channel_notification_keyboard_custom_values(self):
        kb = get_channel_notification_keyboard(
            schedule=False, fact_off=False,
            remind_15m=False, remind_30m=True, remind_1h=True
        )
        assert isinstance(kb.inline_keyboard, list)


# ===========================================================================
# schedule.py
# ===========================================================================


class TestScheduleKeyboard:
    def test_get_schedule_view_keyboard(self):
        kb = get_schedule_view_keyboard()
        cbs = _callback_data_set(kb)
        assert "my_queues" in cbs
        assert "schedule_check" in cbs
        assert "back_to_main" in cbs

    def test_get_schedule_view_keyboard_structure(self):
        kb = get_schedule_view_keyboard()
        assert len(kb.inline_keyboard) == 2
        assert len(kb.inline_keyboard[0]) == 2


# ===========================================================================
# settings.py
# ===========================================================================


class TestSettingsKeyboards:
    def test_get_settings_keyboard_not_admin(self):
        kb = get_settings_keyboard(is_admin=False)
        cbs = _callback_data_set(kb)
        assert "settings_region" in cbs
        assert "settings_ip" in cbs
        assert "settings_channel" in cbs
        assert "settings_alerts" in cbs
        assert "settings_cleanup" in cbs
        assert "settings_admin" not in cbs
        assert "settings_delete_data" in cbs
        assert "back_to_main" in cbs

    def test_get_settings_keyboard_is_admin(self):
        kb = get_settings_keyboard(is_admin=True)
        cbs = _callback_data_set(kb)
        assert "settings_admin" in cbs

    def test_get_cleanup_keyboard_defaults(self):
        kb = get_cleanup_keyboard()
        cbs = _callback_data_set(kb)
        assert "cleanup_toggle_commands" in cbs
        assert "cleanup_toggle_messages" in cbs
        assert "back_to_settings" in cbs
        assert "back_to_main" in cbs

    def test_get_cleanup_keyboard_all_enabled(self):
        kb = get_cleanup_keyboard(auto_delete_commands=True, auto_delete_bot_messages=True)
        assert isinstance(kb.inline_keyboard, list)

    def test_get_cleanup_keyboard_mixed(self):
        kb = get_cleanup_keyboard(auto_delete_commands=True, auto_delete_bot_messages=False)
        assert isinstance(kb.inline_keyboard, list)

    def test_get_delete_data_confirm_keyboard(self):
        kb = get_delete_data_confirm_keyboard()
        cbs = _callback_data_set(kb)
        assert "back_to_settings" in cbs
        assert "delete_data_step2" in cbs

    def test_get_delete_data_final_keyboard(self):
        kb = get_delete_data_final_keyboard()
        cbs = _callback_data_set(kb)
        assert "back_to_settings" in cbs
        assert "confirm_delete_data" in cbs

    def test_get_deactivate_confirm_keyboard(self):
        kb = get_deactivate_confirm_keyboard()
        cbs = _callback_data_set(kb)
        assert "confirm_deactivate" in cbs
        assert "back_to_settings" in cbs


# ===========================================================================
# wizard.py
# ===========================================================================


class TestWizardKeyboards:
    def test_get_region_keyboard_no_selection(self):
        kb = get_region_keyboard()
        cbs = _callback_data_set(kb)
        assert "region_kyiv" in cbs
        assert "region_kyiv-region" in cbs
        assert "region_dnipro" in cbs
        assert "region_odesa" in cbs

    def test_get_region_keyboard_selected(self):
        kb = get_region_keyboard(current_region="kyiv")
        btns = _all_buttons(kb)
        kyiv_btn = next(b for b in btns if b.callback_data == "region_kyiv")
        assert kyiv_btn.text is not None

    def test_get_queue_keyboard_non_kyiv(self):
        kb = get_queue_keyboard("dnipro")
        cbs = _callback_data_set(kb)
        assert "back_to_region" in cbs
        # Standard queues should be present
        assert "queue_1.1" in cbs
        assert "queue_6.2" in cbs

    def test_get_queue_keyboard_kyiv_page1(self):
        kb = get_queue_keyboard("kyiv", page=1)
        cbs = _callback_data_set(kb)
        assert "queue_page_2" in cbs
        assert "back_to_region" in cbs
        # Standard queues
        assert "queue_1.1" in cbs

    def test_get_queue_keyboard_kyiv_page2(self):
        kb = get_queue_keyboard("kyiv", page=2)
        cbs = _callback_data_set(kb)
        assert "queue_page_1" in cbs

    def test_get_queue_keyboard_kyiv_with_selection(self):
        kb = get_queue_keyboard("kyiv", page=1, current_queue="2.1")
        btns = _all_buttons(kb)
        btn = next(b for b in btns if b.callback_data == "queue_2.1")
        assert btn is not None

    def test_get_queue_keyboard_odesa(self):
        kb = get_queue_keyboard("odesa")
        cbs = _callback_data_set(kb)
        assert "queue_1.1" in cbs
        assert "back_to_region" in cbs

    def test_get_queue_keyboard_unknown_region(self):
        kb = get_queue_keyboard("unknown")
        cbs = _callback_data_set(kb)
        # Falls back to STANDARD_QUEUES
        assert "queue_1.1" in cbs
        assert "back_to_region" in cbs

    def test_get_confirm_keyboard(self):
        kb = get_confirm_keyboard()
        cbs = _callback_data_set(kb)
        assert "confirm_setup" in cbs
        assert "back_to_region" in cbs
        assert "back_to_main" in cbs

    def test_get_wizard_notify_target_keyboard(self):
        kb = get_wizard_notify_target_keyboard()
        cbs = _callback_data_set(kb)
        assert "wizard_notify_bot" in cbs
        assert "wizard_notify_channel" in cbs

    def test_get_wizard_bot_notification_keyboard_defaults(self):
        kb = get_wizard_bot_notification_keyboard()
        cbs = _callback_data_set(kb)
        assert "wizard_notif_toggle_schedule" in cbs
        assert "wizard_notif_time_60" in cbs
        assert "wizard_notif_time_30" in cbs
        assert "wizard_notif_time_15" in cbs
        assert "wizard_notif_toggle_fact" in cbs
        assert "wizard_notify_back" in cbs
        assert "wizard_bot_done" in cbs

    def test_get_wizard_bot_notification_keyboard_custom_values(self):
        kb = get_wizard_bot_notification_keyboard(
            schedule_changes=False, fact_off=False,
            remind_15m=False, remind_30m=True, remind_1h=True
        )
        assert isinstance(kb.inline_keyboard, list)

    def test_get_wizard_channel_notification_keyboard_defaults(self):
        kb = get_wizard_channel_notification_keyboard()
        cbs = _callback_data_set(kb)
        assert "wizard_ch_notif_toggle_schedule" in cbs
        assert "wizard_ch_notif_time_15" in cbs
        assert "wizard_channel_back" in cbs
        assert "wizard_channel_done" in cbs

    def test_get_wizard_channel_notification_keyboard_custom_values(self):
        kb = get_wizard_channel_notification_keyboard(
            schedule_changes=True, fact_off=True,
            remind_15m=True, remind_30m=False, remind_1h=False
        )
        assert isinstance(kb.inline_keyboard, list)


# ===========================================================================
# inline.py (re-export hub)
# ===========================================================================


class TestInlineReexports:
    def test_can_import_from_inline(self):
        from bot.keyboards.inline import (
            get_admin_keyboard,
            get_channel_menu_keyboard,
            get_help_keyboard,
            get_ip_management_keyboard,
            get_main_menu,
            get_notification_main_keyboard,
            get_schedule_view_keyboard,
            get_settings_keyboard,
            get_wizard_bot_notification_keyboard,
        )
        assert callable(get_admin_keyboard)
        assert callable(get_channel_menu_keyboard)
        assert callable(get_help_keyboard)
        assert callable(get_ip_management_keyboard)
        assert callable(get_main_menu)
        assert callable(get_notification_main_keyboard)
        assert callable(get_schedule_view_keyboard)
        assert callable(get_settings_keyboard)
        assert callable(get_wizard_bot_notification_keyboard)

    def test_emoji_constants_available(self):
        from bot.keyboards.inline import (
            E_ADMIN, E_ALERTS, E_BACK, E_BELL, E_BOT_NOTIF,
            E_CHANNEL, E_HELP, E_MENU, E_SCHEDULE, E_SUCCESS,
        )
        assert E_ADMIN is not None
        assert E_BACK is None  # E_BACK is explicitly None in common.py
        assert E_MENU is None  # E_MENU is explicitly None in common.py

    def test_common_helpers_accessible(self):
        from bot.keyboards.inline import _btn, _url_btn, _nav_row
        assert callable(_btn)
        assert callable(_url_btn)
        assert callable(_nav_row)


# ===========================================================================
# formatter/template.py
# ===========================================================================


class TestFormatTemplate:
    def test_simple_substitution(self):
        result = format_template("Hello {name}!", {"name": "World"})
        assert result == "Hello World!"

    def test_multiple_substitutions(self):
        result = format_template("{greeting}, {name}!", {"greeting": "Hi", "name": "Alice"})
        assert result == "Hi, Alice!"

    def test_empty_variables(self):
        result = format_template("No vars here.", {})
        assert result == "No vars here."

    def test_html_escaping(self):
        result = format_template("{value}", {"value": "<script>alert('xss')</script>"})
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_html_escaping_ampersand(self):
        result = format_template("{value}", {"value": "A & B"})
        assert "A &amp; B" == result

    def test_html_escaping_quotes(self):
        result = format_template("{value}", {"value": '"quoted"'})
        assert "<" not in result
        assert ">" not in result

    def test_br_tag_replaced_with_newline(self):
        result = format_template("Line1<br>Line2", {})
        assert result == "Line1\nLine2"

    def test_br_tag_with_substitution(self):
        result = format_template("{a}<br>{b}", {"a": "Hello", "b": "World"})
        assert result == "Hello\nWorld"

    def test_missing_variable_key_unchanged(self):
        result = format_template("Hello {unknown}!", {})
        assert result == "Hello {unknown}!"

    def test_numeric_value_converted_to_string(self):
        result = format_template("{count}", {"count": 42})
        assert result == "42"

    def test_get_current_datetime_for_template_keys(self):
        result = get_current_datetime_for_template()
        assert "timeStr" in result
        assert "dateStr" in result

    def test_get_current_datetime_for_template_format(self):
        result = get_current_datetime_for_template()
        time_str = result["timeStr"]
        date_str = result["dateStr"]
        assert re.match(r"^\d{2}:\d{2}$", time_str), f"Unexpected time format: {time_str}"
        assert re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_str), f"Unexpected date format: {date_str}"

    def test_get_current_datetime_for_template_custom_tz(self):
        result = get_current_datetime_for_template(tz_name="UTC")
        assert "timeStr" in result
        assert "dateStr" in result

    def test_get_current_datetime_for_template_default_kyiv(self):
        result_kyiv = get_current_datetime_for_template("Europe/Kyiv")
        result_default = get_current_datetime_for_template()
        # Both should return the same keys; values may differ by seconds but same format
        assert set(result_kyiv.keys()) == set(result_default.keys())
