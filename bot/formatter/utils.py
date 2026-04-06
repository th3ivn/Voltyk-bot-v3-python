from __future__ import annotations

from datetime import datetime

from bot.config import settings

KYIV_TZ = settings.timezone


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
