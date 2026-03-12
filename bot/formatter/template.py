from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def format_template(template: str, variables: dict[str, str]) -> str:
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value))
    result = result.replace("<br>", "\n")
    return result


def get_current_datetime_for_template(tz_name: str = "Europe/Kyiv") -> dict[str, str]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d.%m.%Y")
    return {"timeStr": time_str, "dateStr": date_str}
