from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def _format_time(dt: datetime | str) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime("%H:%M")


def _format_time_remaining(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours} год {mins} хв" if mins > 0 else f"{hours} год"
    return f"{mins} хв"


def format_next_event_message(next_event: dict | None) -> str:
    if not next_event:
        return "✅ Наступні відключення не заплановані"

    lines: list[str] = []
    if next_event["type"] == "power_off":
        lines.append("⏰ <b>Наступне відключення</b>")
        lines.append(f"🔴 Через: {_format_time_remaining(next_event['minutes'])}")
        lines.append(f"🕐 Час: {_format_time(next_event['time'])}")
        if next_event.get("isPossible"):
            lines.append("⚠️ Можливе відключення")
    else:
        lines.append("⏰ <b>Наступне включення</b>")
        lines.append(f"🟢 Через: {_format_time_remaining(next_event['minutes'])}")
        lines.append(f"🕐 Час: {_format_time(next_event['time'])}")
        if next_event.get("isPossible"):
            lines.append("⚠️ Можливе включення")

    return "\n".join(lines)


def format_timer_message(next_event: dict | None) -> str:
    if not next_event:
        return "✅ Наступні відключення не заплановані"

    lines: list[str] = []
    if next_event["type"] == "power_off":
        lines.append("⏰ <b>Відключення через:</b>")
        lines.append(f"🔴 {_format_time_remaining(next_event['minutes'])}")
    else:
        lines.append("⏰ <b>Включення через:</b>")
        lines.append(f"🟢 {_format_time_remaining(next_event['minutes'])}")
    lines.append(f"🕐 {_format_time(next_event['time'])}")
    return "\n".join(lines)


def format_timer_popup(next_event: dict | None, schedule_data: dict | None = None) -> str:
    lines: list[str] = []

    if not next_event:
        lines.append("🎉 Сьогодні без відключень!")
        lines.append("")
        if schedule_data and schedule_data.get("events"):
            tomorrow = datetime.now(KYIV_TZ) + timedelta(days=1)
            tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_end = tomorrow_start + timedelta(days=1)

            def _parse_ev_dt(v) -> datetime:
                dt = datetime.fromisoformat(v) if isinstance(v, str) else v
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=KYIV_TZ)

            tomorrow_events = [
                ev
                for ev in schedule_data["events"]
                if tomorrow_start <= _parse_ev_dt(ev["start"]) < tomorrow_end
            ]
            if tomorrow_events:
                lines.append("📅 Завтра:")
                for ev in tomorrow_events:
                    lines.append(f"• {_format_time(ev['start'])}–{_format_time(ev['end'])}")
            else:
                lines.append("ℹ️ Дані на завтра ще не опубліковані")
        else:
            lines.append("ℹ️ Дані на завтра ще не опубліковані")
    elif next_event["type"] == "power_off":
        lines.append("За графіком зараз:")
        lines.append("🟢 Світло зараз є")
        lines.append("")
        lines.append(f"⏳ Вимкнення через {_format_time_remaining(next_event['minutes'])}")
        start = _format_time(next_event["time"])
        end = _format_time(next_event["endTime"]) if next_event.get("endTime") else "?"
        lines.append(f"📅 Очікуємо - {start}–{end}")
    else:
        lines.append("За графіком зараз:")
        lines.append("🔴 Світла немає")
        lines.append("")
        lines.append(f"⏳ До увімкнення {_format_time_remaining(next_event['minutes'])}")
        start = _format_time(next_event["startTime"]) if next_event.get("startTime") else "?"
        end = _format_time(next_event["time"])
        lines.append(f"📅 Поточне - {start}–{end}")

    return "\n".join(lines)
