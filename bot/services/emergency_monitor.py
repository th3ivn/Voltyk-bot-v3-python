"""DTEK emergency outage monitor.

Periodically polls the DTEK AJAX API for each supported region and notifies
users when an emergency outage starts, ends, or its time changes.

Key design decisions:
- Uses Playwright (real Chromium) to bypass Incapsula bot-protection.
- Interacts with the DTEK form via autocomplete (fill → select first suggestion)
  so the canonical DTEK name is always used regardless of how the user typed it
  (e.g. "Деснянська" → autocomplete finds "вул. Деснянська").
- Intercepts the /ua/ajax network response directly via page.route().
- State is persisted to DB so notifications are not re-sent after restart.
- Playwright flow mirrors dtek_debug handler exactly (same selectors, same waits).
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

_REGIONS_NEEDING_CITY = {"kyiv-region", "dnipro", "odesa"}

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

_TIMEOUT_MS = 30_000  # 30 s page / element timeout

# Combined CSS selectors — Playwright checks all simultaneously (much faster than sequential loops)
_CITY_SEL = (
    "#cityautocomplete-list div, "
    "[id$='autocomplete-list'] div, "
    ".autocomplete-items div, "
    "[class*='autocomplete-item'], "
    "[role='option']"
)
_STREET_SEL = (
    "#streetautocomplete-list div, "
    "[id$='autocomplete-list'] div, "
    ".autocomplete-items div, "
    "[class*='autocomplete-item'], "
    "[role='option']"
)
_HOUSE_SEL = (
    "#houseautocomplete-list div, "
    "[id*='house'][id*='autocomplete'] div, "
    "[id*='house'][id*='list'] div, "
    ".autocomplete-items div, "
    "[role='option']"
)
# Combined popup close selector — one wait_for_selector instead of 7 sequential timeouts
_POPUP_SEL = (
    "button.popup__close, "
    ".popup__close, "
    ".modal__close, "
    "button[class*='close'], "
    "[aria-label='close']"
)


def _build_homepage_url(region: str) -> str | None:
    subdomain = _DTEK_SUBDOMAINS.get(region)
    return f"https://www.dtek-{subdomain}.com.ua/ua/shutdowns" if subdomain else None


# ─── Playwright form interaction ──────────────────────────────────────────


async def _fetch_region_data(
    browser,
    region: str,
    street: str,
    city: str | None,
    house: str = "",
) -> dict[str, Any] | None:
    """
    Open a fresh page, navigate to the DTEK shutdowns page, fill the form
    using autocomplete, and intercept the /ua/ajax network response.

    Optimised for speed:
    - Blocks images/fonts/media (saves ~3s on page load)
    - Combined CSS selectors — Playwright checks all simultaneously (saves ~6s vs sequential loops)
    - Single popup wait_for_selector (saves ~12s vs 7 sequential 2s timeouts)
    - Adaptive form-ready wait instead of fixed 2s sleep (saves up to 1s)
    - Reduced keypress delay 80ms → 40ms (saves ~1s per field)
    - Reduced inter-step waits (AJAX poll replaces house post-Enter sleep)
    """
    homepage_url = _build_homepage_url(region)
    if not homepage_url:
        logger.warning("emergency_monitor: unknown region '%s'", region)
        return None

    needs_city = region in _REGIONS_NEEDING_CITY
    page = await browser.new_page(user_agent=_UA)

    # Collect the intercepted AJAX response here
    intercepted: dict[str, Any] = {}

    async def _on_response(response):
        if "/ua/ajax" in response.url:
            try:
                body = await response.text()
                intercepted["status"] = response.status
                intercepted["body"] = body
                logger.info(
                    "emergency_monitor[pw]: intercepted /ua/ajax status=%d body_len=%d",
                    response.status, len(body),
                )
            except Exception as e:
                logger.warning("emergency_monitor[pw]: failed to read ajax response: %s", e)

    page.on("response", _on_response)

    # ── Block heavy resources (images, fonts, media) to speed up page load ──
    async def _abort_heavy(route):
        if route.request.resource_type in {"image", "font", "media"}:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", _abort_heavy)

    try:
        logger.info(
            "emergency_monitor[pw]: goto %s (region=%s city=%r street=%r)",
            homepage_url, region, city, street,
        )
        await page.goto(homepage_url, wait_until="domcontentloaded", timeout=_TIMEOUT_MS)

        # Wait for form fields to appear instead of a fixed 2s sleep
        try:
            await page.wait_for_selector("#street, #city", timeout=10_000)
            await page.wait_for_timeout(400)  # small buffer for JS event listeners
        except Exception:
            await page.wait_for_timeout(2_000)  # fallback to fixed wait

        # ── Close popup if present (one combined selector, 1.5s max) ─────
        try:
            btn = await page.wait_for_selector(_POPUP_SEL, timeout=1_500)
            await btn.click()
            await page.wait_for_timeout(300)
        except Exception:
            pass  # no popup — move on immediately

        # ── Fill city (regions that require it) ──────────────────────────
        if needs_city and city:
            city_inp = page.locator("#city").first
            await city_inp.click()
            await page.wait_for_timeout(300)  # let JS focus handler fire
            await city_inp.fill("")
            await city_inp.press_sequentially(city, delay=40)

            # Wait for autocomplete — combined selector fires as soon as ANY match appears
            try:
                item = await page.wait_for_selector(_CITY_SEL, timeout=5_000)
                city_text = (await item.inner_text()).strip()
                await item.click()
            except Exception:
                city_text = None

            if not city_text:
                logger.warning("emergency_monitor[pw]: city '%s' not found in autocomplete", city)
                screenshot_bytes = await page.screenshot(full_page=True)
                return {
                    "_exception": f"No AJAX response after autocomplete (city '{city}' not found in DTEK)",
                    "_debug_screenshot": screenshot_bytes,
                }

            logger.info("emergency_monitor[pw]: city '%s' → '%s'", city, city_text)
            await page.wait_for_timeout(400)  # let street field become active

        # ── Fill street ───────────────────────────────────────────────────
        street_inp = page.locator("#street").first
        await street_inp.click()
        await street_inp.fill("")
        await street_inp.press_sequentially(street, delay=40)

        try:
            item = await page.wait_for_selector(_STREET_SEL, timeout=5_000)
            street_text = (await item.inner_text()).strip()
        except Exception:
            street_text = None

        if not street_text:
            logger.warning("emergency_monitor[pw]: street '%s' not found in autocomplete", street)
            screenshot_bytes = await page.screenshot(full_page=True)
            return {
                "_exception": f"Street '{street}' not found in DTEK autocomplete",
                "_debug_screenshot": screenshot_bytes,
            }

        logger.info("emergency_monitor[pw]: street '%s' → '%s' (ArrowDown+Enter)", street, street_text)
        await street_inp.press("ArrowDown")
        await page.wait_for_timeout(300)
        await street_inp.press("Enter")
        # No fixed sleep here — house wait_for below is the gate

        # ── Select house number ───────────────────────────────────────────
        if house:
            house_inp = page.locator("#house").first
            try:
                await house_inp.wait_for(state="visible", timeout=8_000)
            except Exception:
                logger.warning("emergency_monitor[pw]: #house not visible after 8s, trying anyway")

            try:
                await house_inp.scroll_into_view_if_needed()
                try:
                    await house_inp.click()
                    await house_inp.fill("")
                except Exception:
                    await house_inp.click(force=True)
                    await house_inp.fill("", force=True)
                await house_inp.press_sequentially(house, delay=40)

                try:
                    item = await page.wait_for_selector(_HOUSE_SEL, timeout=5_000)
                    house_text = (await item.inner_text()).strip()
                except Exception:
                    house_text = None

                if house_text:
                    logger.info("emergency_monitor[pw]: house '%s' → '%s'", house, house_text)
                    await house_inp.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    await house_inp.press("Enter")
                    # AJAX poll below replaces the fixed 2500ms sleep
                else:
                    logger.warning(
                        "emergency_monitor[pw]: house '%s' not found in autocomplete, proceeding", house,
                    )
            except Exception as e:
                logger.warning("emergency_monitor[pw]: house '%s' interaction failed: %s", house, e)

        # ── Wait for AJAX response ────────────────────────────────────────
        # Poll at 50ms intervals for up to 10s; usually fires within 200–500ms
        for _ in range(200):
            if intercepted:
                break
            await asyncio.sleep(0.05)

        if not intercepted:
            logger.warning(
                "emergency_monitor[pw]: no AJAX response intercepted for region %s", region,
            )
            return {"_exception": "No AJAX response after house selection (house not found in DTEK?)"}

        if intercepted["status"] != 200:
            body_preview = intercepted["body"][:300]
            logger.warning(
                "emergency_monitor[pw]: DTEK POST %d for region %s: %s",
                intercepted["status"], region, body_preview,
            )
            return {"_error": intercepted["status"], "_body": body_preview}

        return json.loads(intercepted["body"])

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
                await _notify_user(bot, user.telegram_id, f"🚨 {sub_type}\n⏰ {new_start} – {new_end}")
        elif prev_start != new_start or prev_end != new_end:
            if ns and ns.notify_emergency_off:
                await _notify_user(
                    bot, user.telegram_id,
                    f"🔄 Оновлено терміни аварійного відключення\nБуло: {prev_start} – {prev_end}\nСтало: {new_start} – {new_end}",
                )

        async with async_session() as db_session:
            async with db_session.begin():
                await upsert_user_emergency_state(
                    db_session, user.id,
                    status="active", start_date=new_start, end_date=new_end,
                    detected_at=datetime.now(UTC) if prev_status == "none" else (prev.detected_at if prev else None),
                )
    else:
        if prev_status == "active":
            if ns and ns.notify_emergency_on:
                await _notify_user(bot, user.telegram_id, "✅ Аварійне відключення завершено")

        if prev_status != "none" or prev is None:
            async with async_session() as db_session:
                async with db_session.begin():
                    await upsert_user_emergency_state(
                        db_session, user.id, status="none", start_date=None, end_date=None,
                    )


# ─── Main check loop ──────────────────────────────────────────────────────


async def _check_all_users(bot: Bot) -> None:
    async with async_session() as db_session:
        users = await get_users_with_emergency_address(db_session)

    if not users:
        return

    groups: dict[tuple[str, str, str | None], list] = {}
    for user in users:
        cfg = user.emergency_config
        key = (user.region, cfg.street or "", cfg.city)
        groups.setdefault(key, []).append(user)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--no-first-run",
                "--disable-sync",
            ],
        )
        try:
            for (region, street, city), group_users in groups.items():
                house = group_users[0].emergency_config.house or ""
                try:
                    response = await _fetch_region_data(browser, region, street, city, house)
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
    global _running
    _running = False
    logger.info("🚨 Emergency monitor stop requested")
