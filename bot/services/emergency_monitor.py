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
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import aiohttp
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


# ─── HTTP session cache ───────────────────────────────────────────────────


@dataclass
class _DTEKSession:
    subdomain: str
    city_canonical: str        # e.g. "м. Вишгород" (from autocomplete)
    street_canonical: str      # e.g. "вул. Грушевського"
    cookies: list[dict] = field(default_factory=list)
    csrf_token: str = ""
    acquired_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_valid(self) -> bool:
        return (datetime.now(UTC) - self.acquired_at).total_seconds() < 3600


# key: (region, city, street) — same grouping key used in _check_all_users
_session_cache: dict[tuple[str, str | None, str], _DTEKSession] = {}

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

def _build_homepage_url(region: str) -> str | None:
    subdomain = _DTEK_SUBDOMAINS.get(region)
    return f"https://www.dtek-{subdomain}.com.ua/ua/shutdowns" if subdomain else None


# ─── City autocomplete best-match selection ───────────────────────────────

# Ukrainian settlement-type prefixes to strip before comparing with user input
_UA_PREFIX_RE = re.compile(
    r"^(м\.|с\.|смт\.|сел\.|с-ще\.|хут\.|мкр\.)\s*",
    re.IGNORECASE,
)


def _normalize_city_suggestion(text: str) -> str:
    """Strip settlement prefix (м., с., etc.) and district suffix (in parentheses)."""
    main = text.split("(")[0]            # drop "...  (Вишгородська громада)"
    main = _UA_PREFIX_RE.sub("", main)   # drop "м.", "с.", "смт.", etc.
    return main.strip().lower()


async def _pick_best_city(page, user_input: str, sel: str, timeout: int = 5_000):
    """
    Wait for city autocomplete suggestions, then pick the best match for user_input.

    Priority:
      0 — exact match after normalization (e.g. "вишгород" == "вишгород")
      1 — starts with user input
      2 — user input contained in suggestion
      3 — fallback: first suggestion (original behaviour)

    Returns (element_handle, display_text) or (None, None) on timeout.
    """
    try:
        await page.wait_for_selector(sel, timeout=timeout)
    except Exception:
        return None, None

    items = await page.query_selector_all(sel)
    if not items:
        return None, None

    query = user_input.strip().lower()
    best_item = items[0]
    best_text = (await items[0].inner_text()).strip()
    best_priority = 3  # start at fallback

    for el in items:
        text = (await el.inner_text()).strip()
        norm = _normalize_city_suggestion(text)
        if norm == query:
            priority = 0
        elif norm.startswith(query):
            priority = 1
        elif query in norm:
            priority = 2
        else:
            priority = 3

        if priority < best_priority:
            best_priority = priority
            best_item = el
            best_text = text

        if best_priority == 0:
            break  # can't do better than exact match

    return best_item, best_text


# ─── Direct HTTP fetch (session reuse) ───────────────────────────────────


async def _fetch_via_http(session: _DTEKSession, house: str) -> dict[str, Any] | None:
    """POST directly to /ua/ajax using a cached Incapsula session (no Playwright)."""
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    url = f"https://www.dtek-{session.subdomain}.com.ua/ua/ajax"
    cookie_jar = {c["name"]: c["value"] for c in session.cookies}
    post_data = (
        "method=getHomeNum"
        f"&data%5B0%5D%5Bname%5D=city&data%5B0%5D%5Bvalue%5D={quote(session.city_canonical)}"
        f"&data%5B1%5D%5Bname%5D=street&data%5B1%5D%5Bvalue%5D={quote(session.street_canonical)}"
        f"&data%5B2%5D%5Bname%5D=updateFact&data%5B2%5D%5Bvalue%5D={quote(timestamp)}"
    )
    headers = {
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "accept": "application/json, text/javascript, */*; q=0.01",
        "x-csrf-token": session.csrf_token,
        "x-requested-with": "XMLHttpRequest",
        "referer": f"https://www.dtek-{session.subdomain}.com.ua/ua/shutdowns",
        "origin": f"https://www.dtek-{session.subdomain}.com.ua",
        "user-agent": _UA,
    }
    try:
        async with aiohttp.ClientSession(cookies=cookie_jar) as client:
            async with client.post(
                url, data=post_data, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.warning(
                    "emergency_monitor[http]: POST %d for %s/%s",
                    resp.status, session.subdomain, session.street_canonical,
                )
    except Exception as e:
        logger.warning("emergency_monitor[http]: request failed: %s", e)
    return None


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

    # Collect the intercepted AJAX request + response here
    intercepted: dict[str, Any] = {}
    intercepted_req: dict[str, Any] = {}

    async def _on_request(request):
        if "/ua/ajax" in request.url:
            intercepted_req["csrf"] = request.headers.get("x-csrf-token", "")

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

    page.on("request", _on_request)
    page.on("response", _on_response)

    # Canonical names discovered via autocomplete (used for session caching)
    city_text: str = ""
    street_text: str = ""

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

        # ── Dismiss any popup/modal (Esc works on DTEK attention modals) ──
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)

        # ── Fill city (regions that require it) ──────────────────────────
        if needs_city and city:
            city_inp = page.locator("#city").first
            await city_inp.click()
            await page.wait_for_timeout(300)  # let JS focus handler fire
            await city_inp.fill("")
            await city_inp.press_sequentially(city, delay=40)

            # Pick best-matching suggestion (not just first) to avoid wrong-city selection
            # e.g. "Вишгород" → first result may be "с. Лісовичі (Вишгородська)" not "м. Вишгород"
            item, _city_text = await _pick_best_city(page, city, _CITY_SEL)
            if item:
                await item.click()

            if not _city_text:
                logger.warning("emergency_monitor[pw]: city '%s' not found in autocomplete", city)
                screenshot_bytes = await page.screenshot(full_page=True)
                return {
                    "_exception": f"No AJAX response after autocomplete (city '{city}' not found in DTEK)",
                    "_debug_screenshot": screenshot_bytes,
                }

            city_text = _city_text
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
            pass  # street_text stays "" → caught by the check below

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

        # ── Cache session for future HTTP-only requests ───────────────────
        subdomain = _DTEK_SUBDOMAINS.get(region, "")
        csrf = intercepted_req.get("csrf", "")
        if subdomain and csrf and street_text:
            try:
                cookies = await page.context.cookies()
                _session_cache[(region, city, street)] = _DTEKSession(
                    subdomain=subdomain,
                    city_canonical=city_text,
                    street_canonical=street_text,
                    cookies=cookies,
                    csrf_token=csrf,
                    acquired_at=datetime.now(UTC),
                )
                logger.info(
                    "emergency_monitor[pw]: session cached for %s/%s city=%r",
                    region, street_text, city_text,
                )
            except Exception as e:
                logger.warning("emergency_monitor[pw]: failed to cache session: %s", e)

        return json.loads(intercepted["body"])

    except Exception as e:
        exc_info = f"{type(e).__name__}: {e}"
        logger.warning("emergency_monitor[pw]: error for region %s: %s", region, exc_info)
        return {"_exception": exc_info}
    finally:
        await page.close()


# ─── Smart fetch: HTTP cache → Playwright fallback ───────────────────────


async def _fetch_region_data_smart(
    browser,
    region: str,
    street: str,
    city: str | None,
    house: str,
) -> dict[str, Any] | None:
    """Try a cached HTTP session first; fall back to Playwright on miss or failure."""
    cache_key = (region, city, street)
    session = _session_cache.get(cache_key)
    if session and session.is_valid():
        result = await _fetch_via_http(session, house)
        if result is not None:
            logger.info("emergency_monitor[http]: cache hit for %s/%s", region, street)
            return result
        logger.warning(
            "emergency_monitor[http]: cache hit but request failed for %s/%s — falling back to Playwright",
            region, street,
        )
        _session_cache.pop(cache_key, None)

    return await _fetch_region_data(browser, region, street, city, house)


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
                    response = await _fetch_region_data_smart(browser, region, street, city, house)
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
