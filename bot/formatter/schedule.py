from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.constants.regions import REGIONS

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def _parse_event_dt(dt: datetime | str) -> datetime:
    """Parse an event datetime string to a timezone-aware Kyiv datetime.

    Handles both offset-aware ISO strings (new format, from api.py) and
    offset-naive ISO strings (legacy format, from old cached/DB data).
    """
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KYIV_TZ)
    return dt.astimezone(KYIV_TZ)

DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]


def _format_time(dt: datetime | str) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime("%H:%M")


def _format_date(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y")


def _format_duration_from_ms(ms: float) -> str:
    total_minutes = int(ms / 60000)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours} год {minutes} хв" if minutes > 0 else f"{hours} год"
    return f"{minutes} хв"


def _total_str(total_minutes: float) -> str:
    hours = int(total_minutes) // 60
    mins = round(total_minutes % 60)
    if hours > 0:
        return f"{hours} год {mins} хв" if mins > 0 else f"{hours} год"
    return f"{mins} хв"


def format_schedule_message(
    region: str,
    queue: str,
    schedule_data: dict,
    next_event: dict | None = None,
    changes: dict | None = None,
    update_type: dict | None = None,
    is_daily_planned: bool = False,
) -> str:
    if not region or not queue:
        return "⚠️ Помилка: відсутні дані про регіон або чергу"

    if not schedule_data or not isinstance(schedule_data, dict):
        return "⚠️ Помилка: невірний формат даних графіка"

    lines: list[str] = []
    now = datetime.now(KYIV_TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_name = DAY_NAMES[now.weekday()]
    today_date = _format_date(now)

    events = schedule_data.get("events", [])
    has_data = schedule_data.get("hasData", False)

    # Choose the base emoji: 📅 for daily planned messages, 💡 for change notifications
    base_emoji = "📅" if is_daily_planned else "💡"

    if not has_data:
        lines.append(
            f"<i>{base_emoji} Графік відключень <b>на сьогодні, {today_date} ({today_name}),</b> для черги {queue}:</i>"
        )
        lines.append("")
        lines.append('<tg-emoji emoji-id="5870509845911702494">✅</tg-emoji> Відключень не заплановано')
        return "\n".join(lines)

    tomorrow_start = today_start + timedelta(days=1)
    day_after_tomorrow = tomorrow_start + timedelta(days=1)
    tomorrow_name = DAY_NAMES[tomorrow_start.weekday()]
    tomorrow_date = _format_date(tomorrow_start)

    new_event_keys: set[str] = set()
    if changes and changes.get("added"):
        for ev in changes["added"]:
            key = f"{ev['start']}_{ev['end']}"
            new_event_keys.add(key)

    today_events = []
    tomorrow_events = []
    for ev in events:
        start = _parse_event_dt(ev["start"])
        if today_start <= start < tomorrow_start:
            today_events.append(ev)
        elif tomorrow_start <= start < day_after_tomorrow:
            tomorrow_events.append(ev)

    today_total = sum(
        (_parse_event_dt(e["end"]) - _parse_event_dt(e["start"])).total_seconds() / 60
        for e in today_events
    )
    tomorrow_total = sum(
        (_parse_event_dt(e["end"]) - _parse_event_dt(e["start"])).total_seconds() / 60
        for e in tomorrow_events
    )

    if tomorrow_events:
        if update_type and update_type.get("tomorrowAppeared"):
            header = f"<i>💡 Зʼявився графік відключень <b>на завтра, {tomorrow_date} ({tomorrow_name}),</b> для черги {queue}:</i>"
        else:
            header = f"<i>💡 Графік відключень <b>на завтра, {tomorrow_date} ({tomorrow_name}),</b> для черги {queue}:</i>"
        lines.append(header)
        lines.append("")
        for ev in tomorrow_events:
            s = _format_time(ev["start"])
            e = _format_time(ev["end"])
            dur = (_parse_event_dt(ev["end"]) - _parse_event_dt(ev["start"])).total_seconds() * 1000
            dur_str = _format_duration_from_ms(dur)
            key = f"{ev['start']}_{ev['end']}"
            is_new = key in new_event_keys
            possible = " ⚠️" if ev.get("isPossible") else ""
            new_mark = " 🆕" if is_new else ""
            lines.append(f"🪫 <b>{s} - {e} (~{dur_str})</b>{possible}{new_mark}")
        lines.append(f"Загалом без світла:<b> ~{_total_str(tomorrow_total)}</b>")
        lines.append("")

    if today_events:
        if update_type and update_type.get("todayUnchanged") and tomorrow_events:
            header = f"<i>💡 Графік відключень <b>на сьогодні, {today_date} ({today_name}),</b> без змін:</i>"
        elif update_type and update_type.get("todayUpdated") and update_type.get("tomorrowAppeared"):
            header = "<i>💡 Оновлено графік <b>на сьогодні:</b></i>"
        elif update_type and update_type.get("todayUpdated"):
            header = f"<i>💡 Оновлено графік відключень <b>на сьогодні, {today_date} ({today_name}),</b> для черги {queue}:</i>"
        else:
            header = f"<i>{base_emoji} Графік відключень <b>на сьогодні, {today_date} ({today_name}),</b> для черги {queue}:</i>"
        lines.append(header)
        lines.append("")
        for ev in today_events:
            s = _format_time(ev["start"])
            e = _format_time(ev["end"])
            dur = (_parse_event_dt(ev["end"]) - _parse_event_dt(ev["start"])).total_seconds() * 1000
            dur_str = _format_duration_from_ms(dur)
            key = f"{ev['start']}_{ev['end']}"
            is_new = key in new_event_keys
            possible = " ⚠️" if ev.get("isPossible") else ""
            new_mark = " 🆕" if is_new else ""
            lines.append(f"🪫 <b>{s} - {e} (~{dur_str})</b>{possible}{new_mark}")
        lines.append(f"Загалом без світла:<b> ~{_total_str(today_total)}</b>")
    else:
        lines.append(
            f"<i>{base_emoji} Графік відключень <b>на сьогодні, {today_date} ({today_name}),</b> для черги {queue}:</i>"
        )
        lines.append("")
        lines.append('<tg-emoji emoji-id="5870509845911702494">✅</tg-emoji> Відключень не заплановано')

    return "\n".join(lines)
