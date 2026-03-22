"""
Admin debug command: /dtek_spy

Runs the same Playwright form flow as the emergency monitor but also intercepts
the raw REQUEST to /ua/ajax so we can see the exact POST body (fields & values).
This is used to reverse-engineer the endpoint for a future direct-HTTP approach.

Usage: /dtek_spy <city> <street> <house>
Example: /dtek_spy Вишгород Грушевського 1
"""
from __future__ import annotations

import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from playwright.async_api import async_playwright

from bot.config import settings
from bot.utils.logger import get_logger

router = Router(name="dtek_spy")
logger = get_logger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
_BASE_URL = "https://www.dtek-krem.com.ua/ua/shutdowns"


@router.message(Command("dtek_spy"))
async def dtek_spy(message: Message) -> None:
    if not settings.is_admin(message.from_user.id):
        return

    args = (message.text or "").split(maxsplit=3)[1:]
    if len(args) < 3:
        await message.answer(
            "Використання: /dtek_spy <місто> <вулиця> <будинок>\n"
            "Приклад: /dtek_spy Вишгород Грушевського 1"
        )
        return

    city_input, street_input, house_input = args[0], args[1], args[2]

    await message.answer(
        f"🔍 Запускаю spy-діагностику...\n"
        f"Місто: {city_input} | Вулиця: {street_input} | Будинок: {house_input}"
    )

    intercepted_req: dict = {}
    intercepted_res: dict = {}

    t_start = time.monotonic()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions"],
        )
        page = await browser.new_page(user_agent=_UA)

        # ── Intercept /ua/ajax request AND response ───────────────────────
        async def _on_request(req):
            if "/ua/ajax" in req.url:
                intercepted_req["method"] = req.method
                intercepted_req["url"] = req.url
                intercepted_req["headers"] = dict(req.headers)
                try:
                    intercepted_req["post_data"] = req.post_data
                except Exception:
                    intercepted_req["post_data"] = None

        async def _on_response(resp):
            if "/ua/ajax" in resp.url:
                intercepted_res["status"] = resp.status
                try:
                    intercepted_res["body"] = await resp.text()
                except Exception as e:
                    intercepted_res["body"] = f"(error reading body: {e})"

        page.on("request", _on_request)
        page.on("response", _on_response)

        # ── Block heavy resources ─────────────────────────────────────────
        async def _abort_heavy(route):
            if route.request.resource_type in {"image", "font", "media"}:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _abort_heavy)

        try:
            await page.goto(_BASE_URL, wait_until="domcontentloaded", timeout=30_000)

            try:
                await page.wait_for_selector("#street, #city", timeout=10_000)
                await page.wait_for_timeout(400)
            except Exception:
                await page.wait_for_timeout(2_000)

            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

            # ── City ──────────────────────────────────────────────────────
            city_inp = page.locator("#city").first
            await city_inp.click()
            await page.wait_for_timeout(300)
            await city_inp.fill("")
            await city_inp.press_sequentially(city_input, delay=40)

            # Pick best-match suggestion
            city_text = None
            try:
                await page.wait_for_selector(
                    "#cityautocomplete-list div, [id$='autocomplete-list'] div, .autocomplete-items div, [role='option']",
                    timeout=5_000,
                )
                items = await page.query_selector_all(
                    "#cityautocomplete-list div, [id$='autocomplete-list'] div, .autocomplete-items div, [role='option']"
                )
                query = city_input.strip().lower()
                best, best_priority = None, 3
                for el in items:
                    text = (await el.inner_text()).strip()
                    norm = text.split("(")[0]
                    import re
                    norm = re.sub(r"^(м\.|с\.|смт\.|сел\.)\s*", "", norm, flags=re.IGNORECASE).strip().lower()
                    if norm == query:
                        p = 0
                    elif norm.startswith(query):
                        p = 1
                    elif query in norm:
                        p = 2
                    else:
                        p = 3
                    if p < best_priority:
                        best_priority, best, city_text = p, el, text
                    if best_priority == 0:
                        break
                if best:
                    await best.click()
            except Exception as e:
                await message.answer(f"⚠️ Місто не знайдено в автокомпліті: {e}")
                return

            await page.wait_for_timeout(400)

            # ── Street ────────────────────────────────────────────────────
            street_inp = page.locator("#street").first
            await street_inp.click()
            await street_inp.fill("")
            await street_inp.press_sequentially(street_input, delay=40)

            street_text = None
            try:
                item = await page.wait_for_selector(
                    "#streetautocomplete-list div, [id$='autocomplete-list'] div, .autocomplete-items div, [role='option']",
                    timeout=5_000,
                )
                street_text = (await item.inner_text()).strip()
            except Exception:
                pass

            if not street_text:
                await message.answer(f"⚠️ Вулицю '{street_input}' не знайдено в автокомпліті")
                return

            await street_inp.press("ArrowDown")
            await page.wait_for_timeout(300)
            await street_inp.press("Enter")

            # ── House ─────────────────────────────────────────────────────
            house_inp = page.locator("#house").first
            try:
                await house_inp.wait_for(state="visible", timeout=8_000)
            except Exception:
                pass

            await house_inp.scroll_into_view_if_needed()
            try:
                await house_inp.click()
                await house_inp.fill("")
            except Exception:
                await house_inp.click(force=True)
                await house_inp.fill("", force=True)
            await house_inp.press_sequentially(house_input, delay=40)

            house_text = None
            try:
                item = await page.wait_for_selector(
                    "#houseautocomplete-list div, [id*='house'][id*='autocomplete'] div, .autocomplete-items div, [role='option']",
                    timeout=5_000,
                )
                house_text = (await item.inner_text()).strip()
            except Exception:
                pass

            if house_text:
                await house_inp.press("ArrowDown")
                await page.wait_for_timeout(300)
                await house_inp.press("Enter")

            # ── Wait for AJAX ─────────────────────────────────────────────
            import asyncio
            for _ in range(200):
                if intercepted_req and intercepted_res:
                    break
                await asyncio.sleep(0.05)

            elapsed = time.monotonic() - t_start

        except Exception as e:
            logger.exception("dtek_spy error: %s", e)
            await message.answer(f"❌ Помилка: {e}")
            return
        finally:
            await browser.close()

    # ── Report ────────────────────────────────────────────────────────────
    summary = (
        f"⏱ Час: {elapsed:.1f}с\n"
        f"🏙 Місто (автокомпліт): {city_text}\n"
        f"🛣 Вулиця (автокомпліт): {street_text}\n"
        f"🏠 Будинок (автокомпліт): {house_text}\n\n"
        f"📡 AJAX Request:\n"
        f"  method: {intercepted_req.get('method', 'не перехоплено')}\n"
        f"  url: {intercepted_req.get('url', '—')}\n"
        f"  post_data: {intercepted_req.get('post_data', '—')}\n\n"
        f"📥 AJAX Response:\n"
        f"  status: {intercepted_res.get('status', 'не перехоплено')}\n"
    )
    await message.answer(summary)

    # Send full request details as file
    req_detail = (
        f"=== REQUEST ===\n"
        f"method: {intercepted_req.get('method')}\n"
        f"url: {intercepted_req.get('url')}\n"
        f"post_data:\n{intercepted_req.get('post_data')}\n\n"
        f"headers:\n"
        + "\n".join(f"  {k}: {v}" for k, v in (intercepted_req.get("headers") or {}).items())
        + "\n\n=== RESPONSE (перші 2000 символів) ===\n"
        + (intercepted_res.get("body") or "")[:2000]
    )
    await message.answer_document(
        BufferedInputFile(req_detail.encode("utf-8"), "dtek_ajax_spy.txt"),
        caption="📄 Повні деталі AJAX запиту та відповіді",
    )
