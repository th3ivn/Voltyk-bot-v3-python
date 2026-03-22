"""
Admin debug command: /dtek_debug

Opens the DTEK krem shutdowns page via Playwright and sends step-by-step
screenshots + full form HTML to the admin so the exact element structure
can be inspected without server terminal access.
"""
from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from playwright.async_api import async_playwright

from bot.config import settings
from bot.utils.logger import get_logger

router = Router(name="dtek_debug")
logger = get_logger(__name__)

_URL = "https://www.dtek-krem.com.ua/ua/shutdowns"
_CITY = "Нижча Дубечня"


@router.message(Command("dtek_debug"))
async def dtek_debug(message: Message) -> None:
    if not settings.is_admin(message.from_user.id):
        return

    await message.answer("🔍 Запускаю діагностику ДТЕК, зачекайте ~30с...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        )

        try:
            await page.goto(_URL, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2_000)

            # ── Close popup ──────────────────────────────────────────────
            for sel in (
                "button.popup__close", ".popup__close", ".modal__close",
                "button[class*='close']", "[aria-label='close']",
                "button:has-text('×')", "button:has-text('✕')",
            ):
                try:
                    btn = page.locator(sel).first
                    await btn.wait_for(state="visible", timeout=2_000)
                    await btn.click()
                    await page.wait_for_timeout(500)
                    break
                except Exception:
                    pass

            # ── Step 1: initial page screenshot ──────────────────────────
            shot1 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot1, "step1_initial.png"),
                caption="📸 Крок 1: сторінка після закриття попапу",
            )

            # ── Gather DOM info ───────────────────────────────────────────
            inputs_info: list[dict] = await page.evaluate("""() =>
                [...document.querySelectorAll('input,select,textarea')].map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    className: el.className || '',
                    visible: el.offsetParent !== null,
                    disabled: el.disabled,
                    value: el.value || '',
                }))
            """)

            roles_info: list[dict] = await page.evaluate("""() =>
                [...document.querySelectorAll('[role]')].map(el => ({
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    id: el.id || '',
                    className: el.className || '',
                    text: el.textContent.trim().slice(0, 60),
                    visible: el.offsetParent !== null,
                }))
            """)

            try:
                form_html = await page.locator("form").first.inner_html()
            except Exception:
                form_html = await page.locator("body").inner_html()
                form_html = form_html[:8000]

            # Send HTML as a file
            report = "=== INPUTS ===\n"
            report += "\n".join(str(i) for i in inputs_info)
            report += "\n\n=== ROLES ===\n"
            report += "\n".join(str(r) for r in roles_info)
            report += "\n\n=== FORM HTML ===\n"
            report += form_html

            await message.answer_document(
                BufferedInputFile(report.encode("utf-8"), "dtek_form.txt"),
                caption="📄 Inputs, ARIA roles та HTML форми",
            )

            # ── Step 2: click #city and type ─────────────────────────────
            # DOM confirmed: #city is a plain <input type="text">
            city_inp = page.locator("#city").first
            is_visible = await city_inp.is_visible()
            is_disabled = await city_inp.is_disabled()
            caption2 = (
                f"📸 Крок 2: після кліку на #city\n"
                f"visible={is_visible} disabled={is_disabled}"
            )
            await city_inp.click()
            await page.wait_for_timeout(300)
            shot2 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot2, "step2_after_click.png"),
                caption=caption2,
            )

            # ── Step 3: type city name ────────────────────────────────────
            await city_inp.fill("")
            await city_inp.press_sequentially(_CITY, delay=80)
            await page.wait_for_timeout(2_000)
            shot3 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot3, "step3_after_type.png"),
                caption=f"📸 Крок 3: після введення «{_CITY}»\nЧи з'явився список підказок?",
            )

            # ── Step 4: CLICK city suggestion (click works for city) ─────────
            city_text = None
            for sel in (
                "#cityautocomplete-list div",
                "[id$='autocomplete-list'] div",
                ".autocomplete-items div",
                "[class*='autocomplete-item']",
                "[role='option']",
            ):
                try:
                    item = page.locator(sel).first
                    await item.wait_for(state="visible", timeout=3_000)
                    city_text = (await item.inner_text()).strip()
                    await item.click()
                    break
                except Exception:
                    continue

            await page.wait_for_timeout(1_000)
            shot4 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot4, "step4_after_city_pick.png"),
                caption=f"📸 Крок 4: після кліку на підказку міста\ntext={city_text}",
            )

            if not city_text:
                try:
                    ac_html = await page.locator("body").inner_html()
                    await message.answer_document(
                        BufferedInputFile(ac_html[:6000].encode("utf-8"), "autocomplete_html.txt"),
                        caption="❌ Підказку міста не знайдено — HTML",
                    )
                except Exception:
                    pass
                return

            # ── Step 5: fill street ───────────────────────────────────────
            _STREET = "Деснянська"
            await page.wait_for_timeout(800)
            street_inp = page.locator("#street").first
            street_visible = await street_inp.is_visible()
            street_disabled = await street_inp.is_disabled()
            await message.answer(
                f"ℹ️ #street: visible={street_visible} disabled={street_disabled}"
            )

            if not street_disabled:
                await street_inp.click()
                await street_inp.fill("")
                await street_inp.press_sequentially(_STREET, delay=80)
                await page.wait_for_timeout(2_000)
                shot5 = await page.screenshot(full_page=True)
                await message.answer_photo(
                    BufferedInputFile(shot5, "step5_after_street_type.png"),
                    caption=f"📸 Крок 5: після введення вулиці «{_STREET}»",
                )
            else:
                await message.answer("❌ #street досі disabled після вибору міста")
                return

            # ── Step 6: ArrowDown+Enter to select street suggestion ───────────
            street_text = None
            for sel in (
                "#streetautocomplete-list div",
                "[id$='autocomplete-list'] div",
                ".autocomplete-items div",
                "[class*='autocomplete-item']",
                "[role='option']",
            ):
                try:
                    item = page.locator(sel).first
                    await item.wait_for(state="visible", timeout=3_000)
                    street_text = (await item.inner_text()).strip()
                    break
                except Exception:
                    continue

            if not street_text:
                try:
                    body_html = await page.locator("body").inner_html()
                    await message.answer_document(
                        BufferedInputFile(body_html[:6000].encode("utf-8"), "street_autocomplete.txt"),
                        caption="❌ Підказку вулиці не знайдено — HTML",
                    )
                except Exception:
                    pass
                return

            if street_text:
                await street_inp.press("ArrowDown")
                await page.wait_for_timeout(300)
                await street_inp.press("Enter")
                await page.wait_for_timeout(2_000)

            shot6 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot6, "step6_after_street_pick.png"),
                caption=f"📸 Крок 6: після вибору вулиці (ArrowDown+Enter)\ntext={street_text}",
            )

            # ── Step 7: inspect #house structure ─────────────────────────
            _HOUSE = "1"
            house_inp = page.locator("#house").first

            # wait up to 8s for house to appear in DOM
            try:
                await house_inp.wait_for(state="attached", timeout=8_000)
            except Exception:
                pass

            # dump outerHTML + state of #house and surrounding form area
            house_info: dict = await page.evaluate("""() => {
                const el = document.getElementById('house');
                if (!el) return {found: false};
                return {
                    found: true,
                    tag: el.tagName,
                    type: el.type || '',
                    disabled: el.disabled,
                    placeholder: el.placeholder || '',
                    className: el.className || '',
                    value: el.value || '',
                    outerHTML: el.outerHTML.slice(0, 500),
                    parentHTML: el.parentElement ? el.parentElement.outerHTML.slice(0, 1000) : '',
                };
            }""")
            await message.answer_document(
                BufferedInputFile(
                    str(house_info).encode("utf-8"),
                    "house_info.txt",
                ),
                caption=f"📄 #house element info\nfound={house_info.get('found')} tag={house_info.get('tag')} disabled={house_info.get('disabled')}",
            )

            # ── Step 8: type house number and watch autocomplete ──────────
            try:
                await house_inp.click()
                await house_inp.fill("")
                await house_inp.press_sequentially(_HOUSE, delay=80)
                await page.wait_for_timeout(2_000)
            except Exception as e:
                await message.answer(f"⚠️ Не вдалося клікнути/ввести в #house: {html.escape(str(e))}")

            shot8 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot8, "step8_house_typing.png"),
                caption=f"📸 Крок 8: після введення «{_HOUSE}» у #house — чи з'явився список?",
            )

            # dump autocomplete list if present
            house_ac_info: list[dict] = await page.evaluate("""() =>
                [...document.querySelectorAll('[id*="house"][id*="autocomplete"] div, [id*="house"][id*="list"] div, [id*="house"] .autocomplete-items div')].map(el => ({
                    id: el.id || '',
                    text: el.textContent.trim().slice(0, 80),
                    visible: el.offsetParent !== null,
                }))
            """)
            await message.answer_document(
                BufferedInputFile(
                    str(house_ac_info).encode("utf-8") if house_ac_info else b"empty",
                    "house_autocomplete_list.txt",
                ),
                caption=f"📄 House autocomplete items: {len(house_ac_info)} знайдено",
            )

            # ── Step 9: ArrowDown+Enter to pick house ─────────────────────
            house_text = None
            for sel in (
                "#houseautocomplete-list div",
                "[id*='house'][id*='autocomplete'] div",
                "[id*='house'][id*='list'] div",
                ".autocomplete-items div",
                "[role='option']",
            ):
                try:
                    item = page.locator(sel).first
                    await item.wait_for(state="visible", timeout=3_000)
                    house_text = (await item.inner_text()).strip()
                    break
                except Exception:
                    continue

            if house_text:
                await house_inp.press("ArrowDown")
                await page.wait_for_timeout(300)
                await house_inp.press("Enter")
                await page.wait_for_timeout(2_500)

            shot9 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot9, "step9_after_house_pick.png"),
                caption=f"📸 Крок 9: після вибору будинку\nhouse_text={house_text}\nЧи оновився графік?",
            )

            await message.answer(
                "✅ Діагностика завершена! Перевір графік відключень на скріншоті вище."
            )

        except Exception as e:
            logger.exception("dtek_debug error: %s", e)
            await message.answer(f"❌ Помилка діагностики: {html.escape(str(e))}")
        finally:
            await browser.close()
