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


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _future(hours: int = 1) -> datetime:
    return (datetime.now(KYIV_TZ) + timedelta(hours=hours)).replace(second=0, microsecond=0)


def _past(hours: int = 1) -> datetime:
    return (datetime.now(KYIV_TZ) - timedelta(hours=hours)).replace(second=0, microsecond=0)


# ─── format_next_event_message ───────────────────────────────────────────────


class TestFormatNextEventMessage:
    def test_none_returns_no_planned(self):
        assert "не заплановані" in format_next_event_message(None)

    def test_power_off_event(self):
        ev = {"type": "power_off", "minutes": 30, "time": _iso(_future()), "isPossible": False}
        result = format_next_event_message(ev)
        assert "відключення" in result.lower()
        assert "30 хв" in result

    def test_power_on_event(self):
        ev = {"type": "power_on", "minutes": 60, "time": _iso(_future()), "isPossible": False}
        result = format_next_event_message(ev)
        assert "включення" in result.lower()

    def test_possible_flag_shown(self):
        ev = {"type": "power_off", "minutes": 10, "time": _iso(_future()), "isPossible": True}
        result = format_next_event_message(ev)
        assert "Можливе" in result


# ─── format_timer_message ────────────────────────────────────────────────────


class TestFormatTimerMessage:
    def test_none_returns_no_planned(self):
        assert "не заплановані" in format_timer_message(None)

    def test_power_off_shows_countdown(self):
        ev = {"type": "power_off", "minutes": 45, "time": _iso(_future())}
        result = format_timer_message(ev)
        assert "45 хв" in result
        assert "відключення" in result.lower()

    def test_power_on_shows_countdown(self):
        ev = {"type": "power_on", "minutes": 120, "time": _iso(_future())}
        result = format_timer_message(ev)
        assert "2 год" in result
        assert "включення" in result.lower()


# ─── format_timer_popup ──────────────────────────────────────────────────────


class TestFormatTimerPopup:
    def test_no_event_no_schedule_no_data(self):
        result = format_timer_popup(None, None)
        assert "Сьогодні без відключень" in result
        assert "не опубліковані" in result

    def test_no_event_schedule_empty_events(self):
        result = format_timer_popup(None, {"events": []})
        assert "не опубліковані" in result

    def test_no_event_schedule_with_tomorrow_events(self):
        tomorrow = datetime.now(KYIV_TZ) + timedelta(days=1)
        start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
        schedule = {"events": [{"start": _iso(start), "end": _iso(end), "isPossible": False}]}
        result = format_timer_popup(None, schedule)
        assert "Завтра" in result
        assert "10:00" in result

    def test_no_event_schedule_with_today_only_events(self):
        """schedule has events but all are today → tomorrow list is empty → line 79."""
        today = datetime.now(KYIV_TZ)
        start = today.replace(hour=10, minute=0, second=0, microsecond=0)
        end = today.replace(hour=12, minute=0, second=0, microsecond=0)
        schedule = {"events": [{"start": _iso(start), "end": _iso(end), "isPossible": False}]}
        result = format_timer_popup(None, schedule)
        assert "не опубліковані" in result

    def test_power_off_event(self):
        ev = {
            "type": "power_off",
            "minutes": 30,
            "time": _iso(_future()),
            "endTime": _iso(_future(2)),
        }
        result = format_timer_popup(ev)
        assert "Світло зараз є" in result
        assert "30 хв" in result

    def test_power_on_event(self):
        ev = {"type": "power_on", "minutes": 20, "time": _iso(_future())}
        result = format_timer_popup(ev)
        assert "Світло зараз" in result or "Включення" in result or "20 хв" in result
