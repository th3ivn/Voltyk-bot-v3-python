"""Tests for bot/formatter/schedule.py."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.formatter.schedule import (
    _format_duration_from_ms,
    _total_str,
    format_schedule_message,
)

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def _kyiv_now() -> datetime:
    return datetime.now(KYIV_TZ)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_event(start: datetime, end: datetime, is_possible: bool = False) -> dict:
    return {"start": _iso(start), "end": _iso(end), "isPossible": is_possible}


def _today_events(hour_start: int = 10, hour_end: int = 12) -> list[dict]:
    now = _kyiv_now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return [_make_event(today.replace(hour=hour_start), today.replace(hour=hour_end))]


def _tomorrow_events(hour_start: int = 14, hour_end: int = 16) -> list[dict]:
    now = _kyiv_now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return [_make_event(tomorrow.replace(hour=hour_start), tomorrow.replace(hour=hour_end))]


# ─── _format_duration_from_ms ─────────────────────────────────────────────


class TestFormatDurationFromMs:
    def test_zero_minutes(self):
        assert _format_duration_from_ms(0) == "0 хв"

    def test_30_minutes(self):
        assert _format_duration_from_ms(30 * 60 * 1000) == "30 хв"

    def test_exactly_one_hour(self):
        assert _format_duration_from_ms(60 * 60 * 1000) == "1 год"

    def test_one_hour_30_minutes(self):
        assert _format_duration_from_ms(90 * 60 * 1000) == "1 год 30 хв"

    def test_two_hours(self):
        assert _format_duration_from_ms(120 * 60 * 1000) == "2 год"


# ─── _total_str ───────────────────────────────────────────────────────────


class TestTotalStr:
    def test_zero(self):
        assert _total_str(0) == "0 хв"

    def test_45_minutes(self):
        assert _total_str(45) == "45 хв"

    def test_60_minutes_is_one_hour(self):
        assert _total_str(60) == "1 год"

    def test_90_minutes(self):
        assert _total_str(90) == "1 год 30 хв"

    def test_120_minutes(self):
        assert _total_str(120) == "2 год"


# ─── format_schedule_message ──────────────────────────────────────────────


class TestFormatScheduleMessage:
    def test_missing_region_returns_error(self):
        msg = format_schedule_message("", "1.1", {"hasData": True, "events": []})
        assert "Помилка" in msg

    def test_missing_queue_returns_error(self):
        msg = format_schedule_message("kyiv", "", {"hasData": True, "events": []})
        assert "Помилка" in msg

    def test_invalid_schedule_data_type_returns_error(self):
        msg = format_schedule_message("kyiv", "1.1", None)
        assert "Помилка" in msg

    def test_no_data_shows_no_outages(self):
        schedule_data = {"hasData": False, "events": []}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "Відключень не заплановано" in msg

    def test_no_data_uses_planned_emoji_for_daily(self):
        schedule_data = {"hasData": False, "events": []}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, is_daily_planned=True)
        assert "📅" in msg

    def test_no_data_uses_bulb_emoji_for_non_daily(self):
        schedule_data = {"hasData": False, "events": []}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, is_daily_planned=False)
        assert "💡" in msg

    def test_today_events_shown(self):
        events = _today_events(hour_start=10, hour_end=12)
        schedule_data = {"hasData": True, "events": events}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "10:00" in msg
        assert "12:00" in msg

    def test_today_events_total_time_shown(self):
        events = _today_events(hour_start=10, hour_end=12)
        schedule_data = {"hasData": True, "events": events}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "Загалом без світла" in msg
        assert "2 год" in msg

    def test_tomorrow_events_shown(self):
        events = _tomorrow_events(hour_start=14, hour_end=16)
        schedule_data = {"hasData": True, "events": events}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "14:00" in msg
        assert "16:00" in msg
        assert "завтра" in msg.lower()

    def test_no_today_events_shows_no_outages_today(self):
        events = _tomorrow_events()
        schedule_data = {"hasData": True, "events": events}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "Відключень не заплановано" in msg

    def test_possible_event_shows_warning_emoji(self):
        now = _kyiv_now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = [_make_event(today.replace(hour=10), today.replace(hour=11), is_possible=True)]
        schedule_data = {"hasData": True, "events": events}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "⚠️" in msg

    def test_new_event_marked_with_new_emoji(self):
        now = _kyiv_now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = today.replace(hour=10)
        end = today.replace(hour=11)
        events = [_make_event(start, end)]
        schedule_data = {"hasData": True, "events": events}
        changes = {"added": [{"start": _iso(start), "end": _iso(end)}], "removed": []}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, changes=changes)
        assert "🆕" in msg

    def test_removed_today_event_shown_with_cancel_mark(self):
        now = _kyiv_now()
        today_str = now.strftime("%Y-%m-%d")
        removed_event = {
            "start": f"{today_str}T10:00:00",
            "end": f"{today_str}T11:00:00",
        }
        schedule_data = {"hasData": True, "events": []}
        changes = {"added": [], "removed": [removed_event]}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, changes=changes)
        assert "❌" in msg
        assert "скасовано" in msg

    def test_tomorrow_appeared_update_type(self):
        events = _tomorrow_events()
        schedule_data = {"hasData": True, "events": events}
        update_type = {"tomorrowAppeared": True}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, update_type=update_type)
        assert "Зʼявився" in msg

    def test_tomorrow_updated_update_type(self):
        events = _tomorrow_events()
        schedule_data = {"hasData": True, "events": events}
        update_type = {"tomorrowUpdated": True}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, update_type=update_type)
        assert "Оновлено" in msg

    def test_today_unchanged_with_tomorrow_shown(self):
        events = _today_events() + _tomorrow_events()
        schedule_data = {"hasData": True, "events": events}
        update_type = {"todayUnchanged": True, "tomorrowAppeared": True}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, update_type=update_type)
        assert "без змін" in msg

    def test_today_updated_update_type(self):
        events = _today_events()
        schedule_data = {"hasData": True, "events": events}
        update_type = {"todayUpdated": True}
        msg = format_schedule_message("kyiv", "1.1", schedule_data, update_type=update_type)
        assert "Оновлено" in msg

    def test_queue_shown_in_header(self):
        schedule_data = {"hasData": False, "events": []}
        msg = format_schedule_message("kyiv", "2.2", schedule_data)
        assert "2.2" in msg

    def test_both_today_and_tomorrow_events(self):
        events = _today_events(10, 11) + _tomorrow_events(14, 16)
        schedule_data = {"hasData": True, "events": events}
        msg = format_schedule_message("kyiv", "1.1", schedule_data)
        assert "10:00" in msg
        assert "14:00" in msg

    def test_tomorrow_cancelled_with_removed_events(self):
        """Lines 109, 125-130, 134: tomorrowCancelled header + removed_tomorrow loop
        + 'Відключень не заплановано' when no active tomorrow events remain."""
        now = _kyiv_now()
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        removed_event = {
            "start": f"{tomorrow_str}T10:00:00+03:00",
            "end": f"{tomorrow_str}T12:00:00+03:00",
        }
        schedule_data = {"hasData": True, "events": []}
        changes = {"removed": [removed_event]}
        update_type = {"tomorrowCancelled": True}

        msg = format_schedule_message("kyiv", "1.1", schedule_data, changes=changes, update_type=update_type)

        assert "Скасовано" in msg          # line 109 tomorrowCancelled header
        assert "❌" in msg                 # lines 125-130 removed_tomorrow loop
        assert "скасовано" in msg          # lines 125-130 loop body
        assert "Відключень не заплановано" in msg  # line 134 else branch

    def test_today_updated_combined_with_tomorrow_change(self):
        """Line 145: todayUpdated + tomorrowAppeared → short 'на сьогодні:' header."""
        events = _today_events() + _tomorrow_events()
        schedule_data = {"hasData": True, "events": events}
        update_type = {"todayUpdated": True, "tomorrowAppeared": True}

        msg = format_schedule_message("kyiv", "1.1", schedule_data, update_type=update_type)

        # Line 145 branch produces the short header without the full date string
        assert "на сьогодні:" in msg
