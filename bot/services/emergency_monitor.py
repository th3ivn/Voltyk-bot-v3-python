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
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from playwright.async_api import Page, async_playwright

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
    "Chrome/143.0.0.0 Safari/537.36"
)

_TIMEOUT_MS = 30_000  # 30 s page / element timeout


def _build_homepage_url(region: str) -> str | None:
    subdomain = _DTEK_SUBDOMAINS.get(region)
    return f"https://www.dtek-{subdomain}.com.ua/ua/shutdowns" if subdomain else None


# ─── Playwright form interaction ──────────────────────────────────────────


async def _fill_and_pick(page: Page, inp_or_sel, list_sel: str, value: str) -> str | None:
    """
    Wait for the input to be editable, click it, clear it, then type *value*
    character-by-character to trigger JS autocomplete. Clicks the first suggestion
    and returns its canonical text.

    inp_or_sel can be either a CSS selector string or a Playwright Locator object.
    Accepts a hint list_sel for the dropdown container, but also tries common
    autocomplete list selectors as fallback.
    """
    try:
        inp = page.locator(inp_or_sel).first if isinstance(inp_or_sel, str) else inp_or_sel
        await inp.wait_for(state="editable", timeout=_TIMEOUT_MS)
        await inp.click()
        await inp.fill("")
        await inp.press_sequentially(value, delay=80)
    except Exception as e:
        label = inp_or_sel if isinstance(inp_or_sel, str) else repr(inp_or_sel)
        logger.warning("emergency_monitor[pw]: input %r not editable: %s", label, e)
        return None

    # Try the expected list selector and common alternatives so we're not
    # tied to a specific id/class that might differ across DTEK sites.
    autocomplete_selectors = [
        f"{list_sel} div",
        f"{list_sel} > *",
        "[id$='autocomplete-list'] div",
        ".autocomplete-items div",
        "[class*='autocomplete-item']",
        "[role='option']",
        "[role='listbox'] [role='option']",
        "[role='listbox'] div",
    ]
    for sel in autocomplete_selectors:
        try:
            item = page.locator(sel).first
            await item.wait_for(state="visible", timeout=3_000)
            canonical = (await item.inner_text()).strip()
            await item.click()
            logger.info("emergency_monitor[pw]: autocomplete '%s' → '%s' (list_sel=%s)", value, canonical, sel)
            return canonical
        except Exception:
            continue

    # All selectors failed — log form HTML for diagnostics
    try:
        html_snippet = await page.locator("form").first.inner_html()
        logger.warning(
            "emergency_monitor[pw]: no autocomplete for %r. Form HTML:\n%s",
            value, html_snippet[:3000],
        )
    except Exception as dbg_e:
        logger.warning("emergency_monitor[pw]: no autocomplete for %r; html dump failed: %s", value, dbg_e)
    return None


async def _fetch_region_data(
    browser,
    region: str,
    street: str,
    city: str | None,
) -> dict[str, Any] | None:
    """
    Open a fresh page, navigate to the DTEK shutdowns page, fill the form
    using autocomplete (which gives us the canonical address names), and
    intercept the /ua/ajax network response.
    """
    homepage_url = _build_homepage_url(region)
    if not homepage_url:
        logger.warning("emergency_monitor: unknown region '%s'", region)
        return None

    needs_city = region in _REGIONS_NEEDING_CITY
    page = await browser.new_page()

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

    try:
        logger.info("emergency_monitor[pw]: goto %s (region=%s city=%r street=%r)", homepage_url, region, city, street)
        await page.goto(homepage_url, wait_until="domcontentloaded", timeout=_TIMEOUT_MS)

        # ── Close popup/notification if present ──────────────────────────
        # DTEK sometimes shows an emergency notification modal on load that
        # covers the form. Try Escape first, then common close-button selectors.
        popup_closed = False
        for close_sel in (
            "button.popup__close",
            ".popup__close",
            ".modal__close",
            "button[class*='close']",
            "[aria-label='close']",
            "[aria-label='Close']",
            ".notification__close",
            ".alert__close",
            # broad fallback: any visible button whose text is × or ✕
            "button:has-text('×')",
            "button:has-text('✕')",
        ):
            try:
                btn = page.locator(close_sel).first
                await btn.wait_for(state="visible", timeout=2_000)
                await btn.click()
                logger.info("emergency_monitor[pw]: closed popup via selector %r", close_sel)
                await page.wait_for_timeout(500)
                popup_closed = True
                break
            except Exception:
                pass

        if not popup_closed:
            # Last resort: Escape key closes most modal dialogs
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

        # ── Fill city (regions that require it) ──────────────────────────
        # NOTE: #city / #street are often hidden <select> elements; the visible
        # interactive inputs are custom dropdown components whose <input> elements
        # share the placeholder text "вводити". We locate them by placeholder and
        # position (nth 0 = city, nth 1 = street) so we actually type into the
        # visible UI and trigger the autocomplete JavaScript.
        if needs_city and city:
            city_inp = page.get_by_placeholder("вводити", exact=False).nth(0)
            canonical_city = await _fill_and_pick(page, city_inp, "#cityautocomplete-list", city)
            if not canonical_city:
                screenshot_bytes = await page.screenshot(full_page=True)
                return {
                    "_exception": f"No AJAX response after autocomplete (city '{city}' not found in DTEK)",
                    "_debug_screenshot": screenshot_bytes,
                }
            # After city selection the street field becomes enabled asynchronously.
            await page.wait_for_timeout(800)

        # ── Fill street ───────────────────────────────────────────────────
        # Street is the 2nd "вводити" input when city is also present, 1st otherwise.
        street_idx = 1 if (needs_city and city) else 0
        street_inp = page.get_by_placeholder("вводити", exact=False).nth(street_idx)
        canonical_street = await _fill_and_pick(page, street_inp, "#streetautocomplete-list", street)
        if not canonical_street:
            screenshot_bytes = await page.screenshot(full_page=True)
            return {
                "_exception": f"No AJAX response after autocomplete (street '{street}' not found in DTEK)",
                "_debug_screenshot": screenshot_bytes,
            }

        # The street autocomplete click triggers the AJAX call automatically.
        # Wait up to 10 s for it to arrive.
        for _ in range(100):
            if intercepted:
                break
            await page.wait_for_timeout(100)

        if not intercepted:
            logger.warning("emergency_monitor[pw]: no AJAX response intercepted for region %s", region)
            return {"_exception": "No AJAX response after autocomplete (street not found in DTEK?)"}

        if intercepted["status"] != 200:
            body_preview = intercepted["body"][:300]
            logger.warning("emergency_monitor[pw]: DTEK POST %d for region %s: %s", intercepted["status"], region, body_preview)
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
                        logger.error("emergency_monitor: _handle_state_change error for user %s: %s", user.telegram_id, e)
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
