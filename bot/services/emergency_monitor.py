"""DTEK emergency outage monitor.

Periodically polls the DTEK AJAX API for each supported region and notifies
users when an emergency outage starts, ends, or its time changes.

Key design decisions:
- One HTTP request per region (not per user) — max 4 requests per cycle.
- Uses a two-step flow: GET homepage to obtain CSRF token, then POST AJAX.
- State is persisted to DB so notifications are not re-sent after restart.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import aiohttp
import sentry_sdk
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.config import settings
from bot.db.queries import (
    get_users_with_emergency_address,
    upsert_user_emergency_state,
)
from bot.db.session import async_session
from bot.utils.helpers import retry_bot_call
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_running = False

# ─── DTEK region config ───────────────────────────────────────────────────

_DTEK_SUBDOMAINS: dict[str, str] = {
    "kyiv": "kem",
    "kyiv-region": "krem",
    "dnipro": "dnem",
    "odesa": "oem",
}

# Regions where city field must be included in the POST body
_REGIONS_NEEDING_CITY = {"kyiv-region", "dnipro", "odesa"}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-Requested-With": "XMLHttpRequest",
}


# ─── DTEK fetcher ─────────────────────────────────────────────────────────


def _build_ajax_url(region: str) -> str | None:
    subdomain = _DTEK_SUBDOMAINS.get(region)
    if not subdomain:
        return None
    return f"https://www.dtek-{subdomain}.com.ua/ua/ajax"


def _build_homepage_url(region: str) -> str | None:
    subdomain = _DTEK_SUBDOMAINS.get(region)
    if not subdomain:
        return None
    return f"https://www.dtek-{subdomain}.com.ua/ua/shutdowns"


def _extract_csrf_token(html: str) -> str | None:
    """Extract <meta name='csrf-token' content='...'> from HTML."""
    import re
    match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
    if match:
        return match.group(1)
    return None


# Ukrainian settlement and street type prefixes used in DTEK canonical names
_LOCATION_PREFIXES = (
    "с.", "м.", "смт.", "сщ.", "с-щ.", "кмт.", "сел.",
    "вул.", "пр.", "просп.", "пров.", "б-р", "бульв.", "пл.", "шосе",
)


def _extract_locations_from_html(html: str) -> list[str]:
    """Extract canonical city/street names embedded in the DTEK page HTML.

    DTEK uses client-side autocomplete, so all location names are embedded
    in the page (inside <option> elements or JS data structures).
    Returns a deduplicated list of found names, or empty list.
    """
    import re

    candidates: list[str] = []

    # Pattern 1: <option ...>Value</option> or <option value="Value">
    for m in re.findall(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>', html):
        m = m.strip()
        if m:
            candidates.append(m)
    for m in re.findall(r'<option[^>]*>([^<]+)</option>', html):
        m = m.strip()
        if m:
            candidates.append(m)

    # Pattern 2: JSON/JS string values that look like Ukrainian location names
    # e.g. "с. Нижча Дубечня" or 'вул. Деснянська'
    for m in re.findall(r'["\']([А-ЯІЇЄа-яіїє][^\n"\']{1,80})["\']', html):
        m = m.strip()
        if m:
            candidates.append(m)

    # Filter to only Ukrainian location names (must start with a known prefix)
    result: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c_low = c.strip().lower()
        if any(c_low.startswith(p + " ") or c_low.startswith(p.rstrip(".") + " ") for p in _LOCATION_PREFIXES):
            if c_low not in seen:
                seen.add(c_low)
                result.append(c.strip())

    return result


def _normalize_location(user_input: str, candidates: list[str]) -> str:
    """Find canonical DTEK location name for user-provided input.

    Tries exact match first, then match after stripping the type prefix
    (e.g. user enters "Нижча Дубечня", finds "с. Нижча Дубечня").
    Falls back to original input if no match is found.
    """
    import re

    if not candidates:
        return user_input

    user_clean = user_input.strip().lower()

    # 1. Exact match (case-insensitive)
    for c in candidates:
        if c.strip().lower() == user_clean:
            return c

    # 2. Match after stripping the type prefix ("с. ", "вул. ", etc.)
    for c in candidates:
        name_part = re.sub(r'^[А-ЯІЇЄа-яіїє][а-яіїє\-]*\.\s*', '', c.strip(), count=1).strip().lower()
        if name_part == user_clean:
            return c

    # 3. Substring match (user input is contained in candidate)
    for c in candidates:
        if user_clean in c.strip().lower():
            return c

    logger.debug("emergency_monitor: no canonical match for %r in %d candidates", user_input, len(candidates))
    return user_input


def _build_post_body(region: str, street: str, city: str | None) -> dict[str, str]:
    """Build the form data dict for the DTEK AJAX POST request."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now_str = datetime.now(kyiv_tz).strftime("%d.%m.%Y %H:%M")

    data: dict[str, str] = {"method": "getHomeNum"}

    idx = 0
    if region in _REGIONS_NEEDING_CITY and city:
        data[f"data[{idx}][name]"] = "city"
        data[f"data[{idx}][value]"] = city
        idx += 1

    data[f"data[{idx}][name]"] = "street"
    data[f"data[{idx}][value]"] = street
    idx += 1

    data[f"data[{idx}][name]"] = "updateFact"
    data[f"data[{idx}][value]"] = now_str

    return data


async def _fetch_region_data(
    session: aiohttp.ClientSession,
    region: str,
    street: str,
    city: str | None,
) -> dict[str, Any] | None:
    """
    Fetch DTEK emergency data for a given region/street combo.
    Returns the parsed JSON dict, or None on failure.
    """
    homepage_url = _build_homepage_url(region)
    ajax_url = _build_ajax_url(region)
    if not homepage_url or not ajax_url:
        logger.warning("emergency_monitor: unknown region '%s'", region)
        return None

    csrf_token = None
    locations: list[str] = []
    try:
        async with session.get(
            homepage_url,
            headers=_BROWSER_HEADERS,
            timeout=aiohttp.ClientTimeout(total=settings.DTEK_REQUEST_TIMEOUT_S),
            ssl=False,
        ) as resp:
            if resp.status == 200:
                html = await resp.text()
                csrf_token = _extract_csrf_token(html)
                if not csrf_token:
                    logger.debug("emergency_monitor: no CSRF token found for region %s", region)
                locations = _extract_locations_from_html(html)
                logger.debug("emergency_monitor: extracted %d location candidates for region %s", len(locations), region)
    except Exception as e:
        logger.warning("emergency_monitor: GET homepage failed for region %s: %s", region, e)

    # Normalize city and street to canonical DTEK names (e.g. "Нижча Дубечня" → "с. Нижча Дубечня")
    normalized_city = _normalize_location(city, locations) if city else city
    normalized_street = _normalize_location(street, locations)
    if normalized_city != city:
        logger.debug("emergency_monitor: city normalized: %r → %r", city, normalized_city)
    if normalized_street != street:
        logger.debug("emergency_monitor: street normalized: %r → %r", street, normalized_street)

    post_data = _build_post_body(region, normalized_street, normalized_city)
    headers = dict(_BROWSER_HEADERS)
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    headers["Referer"] = homepage_url
    headers["Origin"] = homepage_url.rsplit("/ua/", 1)[0]
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token

    try:
        async with session.post(
            ajax_url,
            data=post_data,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=settings.DTEK_REQUEST_TIMEOUT_S),
            ssl=False,
        ) as resp:
            if resp.status != 200:
                body_preview = (await resp.text())[:300]
                logger.warning(
                    "emergency_monitor: DTEK POST returned %d for region %s. Body: %s",
                    resp.status, region, body_preview,
                )
                return {"_error": resp.status, "_body": body_preview}
            return await resp.json(content_type=None)
    except Exception as e:
        exc_type = type(e).__name__
        exc_msg = str(e)
        logger.warning(
            "emergency_monitor: POST AJAX exception for region %s: %s: %s",
            region, exc_type, exc_msg,
        )
        return {"_exception": f"{exc_type}: {exc_msg}"}


def _get_house_entry(data: dict[str, Any], house: str) -> dict | None:
    """
    Find the house entry in the DTEK response.
    Handles both 'data' (lowercase, current format) and 'Data' (legacy format).
    """
    house_dict = data.get("data") or data.get("Data") or {}
    house_normalized = house.strip().upper()
    for key, entry in house_dict.items():
        if str(key).strip().upper() == house_normalized:
            return entry
    return None


def _find_outage_for_house(data: dict[str, Any], house: str) -> dict | None:
    """
    Search the DTEK response for the user's house number.
    Returns the entry only if there is an active emergency (non-empty sub_type + start_date).
    """
    if not data.get("showCurOutageParam"):
        return None
    entry = _get_house_entry(data, house)
    if entry and entry.get("sub_type") and entry.get("start_date"):
        return entry
    return None


def _extract_queue(data: dict[str, Any], house: str) -> str | None:
    """
    Extract the scheduled outage queue (черга) for a house from the DTEK response.
    Returns e.g. '3.1' parsed from 'GPV3.1', or None if not found.
    """
    entry = _get_house_entry(data, house)
    if not entry:
        return None
    reasons = entry.get("sub_type_reason") or []
    if not reasons:
        return None
    raw = str(reasons[0])  # e.g. "GPV3.1"
    return raw[3:] if raw.upper().startswith("GPV") else raw


# ─── State change logic ───────────────────────────────────────────────────


async def _notify_user(bot: Bot, telegram_id: str, text: str) -> None:
    try:
        await retry_bot_call(lambda: bot.send_message(chat_id=telegram_id, text=text))
    except TelegramForbiddenError:
        logger.info("emergency_monitor: user %s blocked the bot", telegram_id)
    except TelegramBadRequest as e:
        logger.warning("emergency_monitor: TelegramBadRequest for user %s: %s", telegram_id, e)
    except Exception as e:
        logger.error("emergency_monitor: notify error for user %s: %s", telegram_id, e)


async def _handle_state_change(
    bot: Bot,
    user,
    current_outage: dict | None,
) -> None:
    """
    Compare current outage data with stored state and send notification if changed.
    Updates the persistent state in DB.
    """
    prev = user.emergency_state
    prev_status = prev.status if prev else "none"
    prev_start = prev.start_date if prev else None
    prev_end = prev.end_date if prev else None

    ns = user.notification_settings

    if current_outage:
        new_start = current_outage.get("start_date")
        new_end = current_outage.get("end_date")
        sub_type = current_outage.get("sub_type", "Аварійне відключення")

        if prev_status == "none":
            # Outage appeared
            if ns and ns.notify_emergency_off:
                text = (
                    f"🚨 {sub_type}\n"
                    f"⏰ {new_start} – {new_end}"
                )
                await _notify_user(bot, user.telegram_id, text)
        elif prev_start != new_start or prev_end != new_end:
            # Outage times updated
            if ns and ns.notify_emergency_off:
                text = (
                    f"🔄 Оновлено терміни аварійного відключення\n"
                    f"Було: {prev_start} – {prev_end}\n"
                    f"Стало: {new_start} – {new_end}"
                )
                await _notify_user(bot, user.telegram_id, text)

        async with async_session() as db_session:
            async with db_session.begin():
                await upsert_user_emergency_state(
                    db_session,
                    user.id,
                    status="active",
                    start_date=new_start,
                    end_date=new_end,
                    detected_at=datetime.now(UTC) if prev_status == "none" else prev.detected_at if prev else None,
                )
    else:
        if prev_status == "active":
            # Outage ended
            if ns and ns.notify_emergency_on:
                text = "✅ Аварійне відключення завершено"
                await _notify_user(bot, user.telegram_id, text)

        if prev_status != "none" or prev is None:
            async with async_session() as db_session:
                async with db_session.begin():
                    await upsert_user_emergency_state(
                        db_session,
                        user.id,
                        status="none",
                        start_date=None,
                        end_date=None,
                    )


# ─── Main check loop ──────────────────────────────────────────────────────


async def _check_all_users(bot: Bot) -> None:
    """
    Main check: fetch DTEK data per unique (region, street, city) combo,
    then evaluate each user against the cached response.
    """
    async with async_session() as db_session:
        users = await get_users_with_emergency_address(db_session)

    if not users:
        return

    # Group users by (region, street, city) — one DTEK request per group
    groups: dict[tuple[str, str, str | None], list] = {}
    for user in users:
        cfg = user.emergency_config
        key = (user.region, cfg.street or "", cfg.city)
        groups.setdefault(key, []).append(user)

    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(connector=connector) as http_session:
        for (region, street, city), group_users in groups.items():
            try:
                response = await _fetch_region_data(http_session, region, street, city)
            except Exception as e:
                logger.error("emergency_monitor: _fetch_region_data error [%s]: %s", region, e)
                response = None

            for user in group_users:
                cfg = user.emergency_config
                house = cfg.house or ""
                current_outage = _find_outage_for_house(response or {}, house) if response else None
                try:
                    await _handle_state_change(bot, user, current_outage)
                except Exception as e:
                    logger.error(
                        "emergency_monitor: _handle_state_change error for user %s: %s",
                        user.telegram_id, e,
                    )


async def emergency_monitor_loop(bot: Bot) -> None:
    """Background loop for DTEK emergency outage monitoring."""
    global _running
    _running = True
    interval = settings.DTEK_CHECK_INTERVAL_S
    logger.info("🚨 Emergency monitor starting (interval=%ds)", interval)

    while _running:
        try:
            await _check_all_users(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("emergency_monitor: cycle error: %s", e)
            sentry_sdk.capture_exception(e)

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break

    logger.info("🚨 Emergency monitor stopped")


def stop_emergency_monitor() -> None:
    """Signal the emergency monitor loop to stop."""
    global _running
    _running = False
    logger.info("🚨 Emergency monitor stop requested")
