"""Tests for bot/formatter/messages.py."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.formatter.messages import (
    build_channel_notification_message,
    build_notification_settings_message,
    format_live_status_message,
    format_main_menu_message,
    has_any_notification_enabled,
)
from tests.conftest import make_channel_config, make_notification_settings, make_user


# ─── has_any_notification_enabled ────────────────────────────────────────


class TestHasAnyNotificationEnabled:
    def test_none_returns_false(self):
        assert has_any_notification_enabled(None) is False

    def test_all_enabled_returns_true(self):
        ns = make_notification_settings(
            notify_schedule_changes=True,
            notify_remind_off=True,
            notify_fact_off=True,
            notify_remind_on=True,
            notify_fact_on=True,
        )
        assert has_any_notification_enabled(ns) is True

    def test_all_disabled_returns_false(self):
        ns = make_notification_settings(
            notify_schedule_changes=False,
            notify_remind_off=False,
            notify_fact_off=False,
            notify_remind_on=False,
            notify_fact_on=False,
        )
        assert has_any_notification_enabled(ns) is False

    def test_single_enabled_returns_true(self):
        ns = make_notification_settings(
            notify_schedule_changes=False,
            notify_remind_off=False,
            notify_fact_off=True,
            notify_remind_on=False,
            notify_fact_on=False,
        )
        assert has_any_notification_enabled(ns) is True

    def test_only_schedule_changes_enabled(self):
        ns = make_notification_settings(
            notify_schedule_changes=True,
            notify_remind_off=False,
            notify_fact_off=False,
            notify_remind_on=False,
            notify_fact_on=False,
        )
        assert has_any_notification_enabled(ns) is True


# ─── format_live_status_message ──────────────────────────────────────────


class TestFormatLiveStatusMessage:
    def test_with_ip_channel_and_notifications(self):
        user = make_user(router_ip="192.168.1.1")
        msg = format_live_status_message(user)
        assert "підключено ✅" in msg  # IP connected
        assert "Моніторинг активний" in msg
        assert "1.1" in msg  # queue

    def test_without_ip_shows_hint(self):
        user = make_user(router_ip=None)
        msg = format_live_status_message(user)
        assert "не підключено" in msg
        assert "Додайте IP" in msg
        assert "Моніторинг активний" not in msg

    def test_without_channel_shows_not_connected(self):
        user = make_user(channel_config=None)
        msg = format_live_status_message(user)
        # channel shows "не підключено" (without ✅)
        assert "📺 Канал: не підключено" in msg

    def test_channel_config_with_no_channel_id(self):
        cc = make_channel_config(channel_id=None)
        user = make_user(channel_config=cc)
        msg = format_live_status_message(user)
        assert "📺 Канал: не підключено" in msg

    def test_notifications_disabled(self):
        ns = make_notification_settings(
            notify_schedule_changes=False,
            notify_remind_off=False,
            notify_fact_off=False,
            notify_remind_on=False,
            notify_fact_on=False,
        )
        user = make_user(router_ip="192.168.1.1", notification_settings=ns)
        msg = format_live_status_message(user)
        assert "вимкнено" in msg
        assert "Моніторинг активний" not in msg

    def test_region_name_override(self):
        user = make_user(region="kyiv")
        msg = format_live_status_message(user, region_name="Київ (тест)")
        assert "Київ (тест)" in msg

    def test_region_lookup_from_constants(self):
        user = make_user(region="kyiv")
        msg = format_live_status_message(user)
        assert "Київ" in msg

    def test_unknown_region_falls_back_to_code(self):
        user = make_user(region="unknown-region")
        msg = format_live_status_message(user)
        assert "unknown-region" in msg

    def test_contains_queue_in_header(self):
        user = make_user(queue="3.2")
        msg = format_live_status_message(user)
        assert "3.2" in msg


# ─── format_main_menu_message ────────────────────────────────────────────


class TestFormatMainMenuMessage:
    def test_basic_structure(self):
        user = make_user()
        msg = format_main_menu_message(user)
        assert "Головне меню" in msg
        assert "Регіон:" in msg
        assert "Канал:" in msg
        assert "Сповіщення:" in msg

    def test_with_channel_connected(self):
        user = make_user()
        msg = format_main_menu_message(user)
        assert "підключено ✅" in msg

    def test_without_channel(self):
        user = make_user(channel_config=None)
        msg = format_main_menu_message(user)
        assert "не підключено" in msg

    def test_notifications_enabled(self):
        user = make_user()
        msg = format_main_menu_message(user)
        assert "увімкнено ✅" in msg

    def test_notifications_disabled(self):
        ns = make_notification_settings(
            notify_schedule_changes=False,
            notify_remind_off=False,
            notify_fact_off=False,
            notify_remind_on=False,
            notify_fact_on=False,
        )
        user = make_user(notification_settings=ns)
        msg = format_main_menu_message(user)
        assert "вимкнено" in msg

    def test_region_and_queue_shown(self):
        user = make_user(region="kyiv", queue="2.1")
        msg = format_main_menu_message(user)
        assert "Київ" in msg
        assert "2.1" in msg


# ─── build_notification_settings_message ─────────────────────────────────


class TestBuildNotificationSettingsMessage:
    def test_all_enabled_shows_checkmarks(self):
        ns = make_notification_settings(
            notify_schedule_changes=True,
            notify_remind_off=True,
            notify_fact_off=True,
            notify_remind_on=True,
            notify_fact_on=True,
            remind_15m=True,
            remind_30m=True,
            remind_1h=True,
        )
        msg = build_notification_settings_message(ns)
        assert msg.count("✅") >= 5
        assert "❌" not in msg

    def test_all_disabled_shows_crosses(self):
        ns = make_notification_settings(
            notify_schedule_changes=False,
            notify_remind_off=False,
            notify_fact_off=False,
            notify_remind_on=False,
            notify_fact_on=False,
            remind_15m=False,
            remind_30m=False,
            remind_1h=False,
        )
        msg = build_notification_settings_message(ns)
        assert "✅" not in msg
        assert msg.count("❌") >= 5

    def test_contains_section_headers(self):
        ns = make_notification_settings()
        msg = build_notification_settings_message(ns)
        assert "Оновлення графіків" in msg
        assert "Нагадування" in msg

    def test_mixed_settings(self):
        ns = make_notification_settings(
            notify_schedule_changes=True,
            remind_1h=False,
            remind_30m=False,
            remind_15m=True,
        )
        msg = build_notification_settings_message(ns)
        assert "✅" in msg
        assert "❌" in msg


# ─── build_channel_notification_message ──────────────────────────────────


class TestBuildChannelNotificationMessage:
    def test_all_enabled(self):
        cc = make_channel_config(
            ch_notify_schedule=True,
            ch_remind_1h=True,
            ch_remind_30m=True,
            ch_remind_15m=True,
            ch_notify_fact_off=True,
        )
        msg = build_channel_notification_message(cc)
        assert msg.count("✅") >= 4
        assert "❌" not in msg

    def test_all_disabled(self):
        cc = make_channel_config(
            ch_notify_schedule=False,
            ch_remind_1h=False,
            ch_remind_30m=False,
            ch_remind_15m=False,
            ch_notify_fact_off=False,
        )
        msg = build_channel_notification_message(cc)
        assert "✅" not in msg
        assert msg.count("❌") >= 4

    def test_contains_channel_header(self):
        cc = make_channel_config()
        msg = build_channel_notification_message(cc)
        assert "Сповіщення каналу" in msg

    def test_contains_schedule_updates_row(self):
        cc = make_channel_config()
        msg = build_channel_notification_message(cc)
        assert "Оновлення графіків" in msg
