"""DTEK emergency outage monitor.

Periodically polls the DTEK AJAX API for each supported region and notifies
users when an emergency outage starts, ends, or its time changes.

Key design decisions:
- One Playwright browser page per region (not per user) — max 4 pages per cycle.
- Playwright runs real Chromium, which bypasses Incapsula bot-protection that
  blocks plain HTTP requests.
- The browser navigates to the DTEK shutdowns page (establishing session cookies
  automatically), then executes the AJAX call from within the page JS context
  so CSRF tokens and cookies are handled by the browser automatically.
- State is persisted to DB so notifications are not re-sent after restart.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from playwright.async_api import async_playwright

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

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)


# ─── URL helpers ──────────────────────────────────────────────────────────


def _build_homepage_url(region: str) -> str | None:
    subdomain = _DTEK_SUBDOMAINS.get(region)
    if not subdomain:
        return None
    return f"https://www.dtek-{subdomain}.com.ua/ua/shutdowns"


# ─── Playwright fetcher ───────────────────────────────────────────────────

# JS executed inside the Playwright page to make the AJAX call.
# The browser context already has session cookies + CSRF cookie set,
# so the fetch() call succeeds where a plain HTTP POST would fail.
_AJAX_JS = """
async ([city, street, needsCity]) => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = meta ? meta.getAttribute('content') : '';

    // Try to read updateFact that DTEK embeds in the page JS
    let updateFact = '';
    try {
        const m = document.documentElement.innerHTML.match(/"updateFact":"([^"]+)"/);
        if (m) updateFact = m[1];
    } catch(e) {}

    const formData = new URLSearchParams();
    formData.append('method', 'getHomeNum');

    let idx = 0;
    if (needsCity && city) {
        formData.append('data[' + idx + '][name]', 'city');
        formData.append('data[' + idx + '][value]', city);
        idx++;
    }
    formData.append('data[' + idx + '][name]', 'street');
    formData.append('data[' + idx + '][value]', street);
    idx++;
    formData.append('data[' + idx + '][name]', 'updateFact');
    formData.append('data[' + idx + '][value]', updateFact);

    const resp = await fetch('/ua/ajax', {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRF-Token': csrfToken,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        },
        body: formData.toString(),
    });

    const text = await resp.text();
    return { status: resp.status, body: text, csrfLen: csrfToken.length, updateFact: updateFact };
}
"""


async def _fetch_region_data(
    browser,
    region: str,
    street: str,
    city: str | None,
) -> dict[str, Any] | None:
    """
    Open a fresh browser page, navigate to the DTEK shutdowns page,
    then perform the AJAX call from within the browser JS context.
    Returns parsed JSON dict, or a dict with '_error'/'_exception' key on failure.
    """
    homepage_url = _build_homepage_url(region)
    if not homepage_url:
        logger.warning("emergency_monitor: unknown region '%s'", region)
        return None

    needs_city = region in _REGIONS_NEEDING_CITY
    page = await browser.new_page()
    try:
        logger.info("emergency_monitor[pw]: GET %s (region=%s)", homepage_url, region)
        await page.goto(
            homepage_url,
            wait_until="domcontentloaded",
            timeout=settings.DTEK_REQUEST_TIMEOUT_S * 1000,
        )

        result = await page.evaluate(_AJAX_JS, [city, street, needs_city])

        logger.info(
            "emergency_monitor[pw]: POST region=%s status=%s csrf_len=%s updateFact=%r city=%r street=%r",
            region, result.get("status"), result.get("csrfLen"), result.get("updateFact"), city, street,
        )

        if result["status"] != 200:
            body = result.get("body", "")[:300]
            logger.warning(
                "emergency_monitor[pw]: DTEK POST %d for region %s. Body: %s",
                result["status"], region, body,
            )
            return {"_error": result["status"], "_body": body}

        return json.loads(result["body"])

    except Exception as e:
        exc_info = f"{type(e).__name__}: {e}"
        logger.warning("emergency_monitor[pw]: error for region %s: %s", region, exc_info)
        return {"_exception": exc_info}
    finally:
        await page.close()


# ─── House / outage helpers ───────────────────────────────────────────────


def _get_house_entry(data: dict[str, Any], house: str) -> dict | None:
    house_dict = data.get("data") or data.get("Data") or {}
    house_normalized = house.strip().upper()
    for key, entry in house_dict.items():
        if str(key).strip().upper() == house_normalized:
            return entry
    return None


def _find_outage_for_house(data: dict[str, Any], house: str) -> dict | None:
    """Return the outage entry only if there is an active emergency."""
    if not data.get("showCurOutageParam"):
        return None
    entry = _get_house_entry(data, house)
    if entry and entry.get("sub_type") and entry.get("start_date"):
        return entry
    return None


def _extract_queue(data: dict[str, Any], house: str) -> str | None:
    entry = _get_house_entry(data, house)
    if not entry:
        return None
    reasons = entry.get("sub_type_reason") or []
    if not reasons:
        return None
    raw = str(reasons[0])
    return raw[3:] if raw.upper().startswith("GPV") else raw


# ─── State change / notification logic ────────────────────────────────────


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
            if ns and ns.notify_emergency_off:
                text = (
                    f"🚨 {sub_type}\n"
                    f"⏰ {new_start} – {new_end}"
                )
                await _notify_user(bot, user.telegram_id, text)
        elif prev_start != new_start or prev_end != new_end:
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
    Main check: launch a Playwright Chromium browser, fetch DTEK data per
    unique (region, street, city) combo, then evaluate each user.
    """
    async with async_session() as db_session:
        users = await get_users_with_emergency_address(db_session)

    if not users:
        return

    # Group users by (region, street, city) — one browser page per group
    groups: dict[tuple[str, str, str | None], list] = {}
    for user in users:
        cfg = user.emergency_config
        key = (user.region, cfg.street or "", cfg.city)
        groups.setdefault(key, []).append(user)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            for (region, street, city), group_users in groups.items():
                try:
                    response = await _fetch_region_data(browser, region, street, city)
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
        finally:
            await browser.close()


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
