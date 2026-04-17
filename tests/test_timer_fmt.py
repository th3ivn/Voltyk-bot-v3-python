"""Tests for bot/formatter/timer.py."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.formatter.timer import (
    format_next_event_message,
    format_timer_message,
    format_timer_popup,
)

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def _make_power_off_event(minutes: int = 30, time_str: str = "14:00", end_str: str = "16:00") -> dict:
    now = datetime.now(KYIV_TZ)
    event_time = (now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    end_time = (event_time + timedelta(hours=2)).replace(second=0, microsecond=0)
    return {
        "type": "power_off",
        "time": event_time.isoformat(),
        "endTime": end_time.isoformat(),
        "minutes": minutes,
        "isPossible": False,
    }


def _make_power_on_event(minutes: int = 45) -> dict:
    now = datetime.now(KYIV_TZ)
    event_time = (now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    start_time = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
    return {
        "type": "power_on",
        "time": event_time.isoformat(),
        "startTime": start_time.isoformat(),
        "minutes": minutes,
        "isPossible": False,
    }


def _make_tomorrow_events() -> list[dict]:
    now = datetime.now(KYIV_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        {
            "start": tomorrow.replace(hour=10).isoformat(),
            "end": tomorrow.replace(hour=12).isoformat(),
            "isPossible": False,
        }
    ]


# ─── format_next_event_message ───────────────────────────────────────────


class TestFormatNextEventMessage:
    def test_none_returns_no_outages_message(self):
        msg = format_next_event_message(None)
        assert "не заплановані" in msg

    def test_power_off_event_shows_next_outage_header(self):
        event = _make_power_off_event(minutes=30)
        msg = format_next_event_message(event)
        assert "Наступне відключення" in msg

    def test_power_off_event_shows_red_indicator(self):
        event = _make_power_off_event(minutes=30)
        msg = format_next_event_message(event)
        assert "🔴" in msg

    def test_power_off_event_shows_minutes(self):
        event = _make_power_off_event(minutes=30)
        msg = format_next_event_message(event)
        assert "30 хв" in msg

    def test_power_off_event_shows_time(self):
        now = datetime.now(KYIV_TZ)
        event_time = (now + timedelta(minutes=30)).replace(second=0, microsecond=0)
        event = {
            "type": "power_off",
            "time": event_time.isoformat(),
            "endTime": None,
            "minutes": 30,
            "isPossible": False,
        }
        msg = format_next_event_message(event)
        assert event_time.strftime("%H:%M") in msg

    def test_power_off_possible_shows_warning(self):
        event = _make_power_off_event(minutes=30)
        event["isPossible"] = True
        msg = format_next_event_message(event)
        assert "⚠️" in msg
        assert "Можливе відключення" in msg

    def test_power_on_event_shows_next_power_on_header(self):
        event = _make_power_on_event(minutes=45)
        msg = format_next_event_message(event)
        assert "Наступне включення" in msg

    def test_power_on_event_shows_green_indicator(self):
        event = _make_power_on_event(minutes=45)
        msg = format_next_event_message(event)
        assert "🟢" in msg

    def test_power_on_event_shows_minutes(self):
        event = _make_power_on_event(minutes=90)
        msg = format_next_event_message(event)
        assert "1 год 30 хв" in msg

    def test_power_on_possible_shows_warning(self):
        event = _make_power_on_event(minutes=10)
        event["isPossible"] = True
        msg = format_next_event_message(event)
        assert "⚠️" in msg
        assert "Можливе включення" in msg

    def test_hours_shown_for_large_minutes(self):
        event = _make_power_off_event(minutes=120)
        msg = format_next_event_message(event)
        assert "2 год" in msg


# ─── format_timer_message ─────────────────────────────────────────────────


class TestFormatTimerMessage:
    def test_none_returns_no_outages(self):
        msg = format_timer_message(None)
        assert "не заплановані" in msg

    def test_power_off_compact_header(self):
        event = _make_power_off_event(minutes=30)
        msg = format_timer_message(event)
        assert "Відключення через:" in msg

    def test_power_off_shows_red_countdown(self):
        event = _make_power_off_event(minutes=30)
        msg = format_timer_message(event)
        assert "🔴" in msg
        assert "30 хв" in msg

    def test_power_on_compact_header(self):
        event = _make_power_on_event(minutes=45)
        msg = format_timer_message(event)
        assert "Включення через:" in msg

    def test_power_on_shows_green_countdown(self):
        event = _make_power_on_event(minutes=45)
        msg = format_timer_message(event)
        assert "🟢" in msg
        assert "45 хв" in msg

    def test_compact_output_has_3_lines(self):
        event = _make_power_off_event(minutes=30)
        msg = format_timer_message(event)
        lines = msg.strip().split("\n")
        assert len(lines) == 3


# ─── format_timer_popup ──────────────────────────────────────────────────


class TestFormatTimerPopup:
    def test_no_event_no_tomorrow_shows_celebration(self):
        msg = format_timer_popup(None, schedule_data=None)
        assert "🎉" in msg
        assert "Сьогодні без відключень" in msg

    def test_no_event_no_tomorrow_data_shows_no_data_notice(self):
        msg = format_timer_popup(None, schedule_data=None)
        assert "не опубліковані" in msg

    def test_no_event_with_tomorrow_events_shows_tomorrow(self):
        tomorrow_events = _make_tomorrow_events()
        schedule_data = {"hasData": True, "events": tomorrow_events}
        msg = format_timer_popup(None, schedule_data=schedule_data)
        assert "Завтра:" in msg
        assert "10:00" in msg

    def test_no_event_with_empty_schedule_events(self):
        schedule_data = {"hasData": True, "events": []}
        msg = format_timer_popup(None, schedule_data=schedule_data)
        assert "не опубліковані" in msg

    def test_power_off_event_shows_power_is_on(self):
        event = _make_power_off_event(minutes=30)
        msg = format_timer_popup(event)
        assert "🟢" in msg
        assert "Світло зараз є" in msg

    def test_power_off_event_shows_countdown(self):
        event = _make_power_off_event(minutes=30)
        msg = format_timer_popup(event)
        assert "Вимкнення через" in msg
        assert "30 хв" in msg

    def test_power_off_event_shows_time_range(self):
        event = _make_power_off_event(minutes=30)
        msg = format_timer_popup(event)
        assert "Очікуємо" in msg

    def test_power_off_missing_end_time_shows_question_mark(self):
        event = _make_power_off_event(minutes=30)
        event["endTime"] = None
        msg = format_timer_popup(event)
        assert "?" in msg

    def test_power_on_event_shows_no_power(self):
        event = _make_power_on_event(minutes=45)
        msg = format_timer_popup(event)
        assert "🔴" in msg
        assert "Світла немає" in msg

    def test_power_on_event_shows_countdown(self):
        event = _make_power_on_event(minutes=45)
        msg = format_timer_popup(event)
        assert "До увімкнення" in msg
        assert "45 хв" in msg

    def test_power_on_event_shows_current_period(self):
        event = _make_power_on_event(minutes=45)
        msg = format_timer_popup(event)
        assert "Поточне" in msg

    def test_power_on_missing_start_time_shows_question_mark(self):
        event = _make_power_on_event(minutes=45)
        event["startTime"] = None
        msg = format_timer_popup(event)
        assert "?" in msg
