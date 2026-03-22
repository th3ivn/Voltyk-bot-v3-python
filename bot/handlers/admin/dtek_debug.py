"""
Admin debug command: /dtek_debug

Opens the DTEK krem shutdowns page via Playwright and sends step-by-step
screenshots + full form HTML to the admin so the exact element structure
can be inspected without server terminal access.
"""
from __future__ import annotations

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

            # ── Step 2: click first combobox ─────────────────────────────
            combobox_count = await page.get_by_role("combobox").count()
            caption2 = f"📸 Крок 2: після кліку на поле міста\n(combobox знайдено: {combobox_count})"

            if combobox_count > 0:
                await page.get_by_role("combobox").nth(0).click()
            else:
                triggers = page.get_by_text("Почніть вводити", exact=False)
                cnt = await triggers.count()
                caption2 += f"\n(тригерів 'Почніть вводити': {cnt})"
                if cnt > 0:
                    await triggers.nth(0).click()

            await page.wait_for_timeout(800)
            shot2 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot2, "step2_after_click.png"),
                caption=caption2,
            )

            # ── Step 3: type city name ────────────────────────────────────
            await page.keyboard.type(_CITY, delay=80)
            await page.wait_for_timeout(2_000)
            shot3 = await page.screenshot(full_page=True)
            await message.answer_photo(
                BufferedInputFile(shot3, "step3_after_type.png"),
                caption=f"📸 Крок 3: після введення «{_CITY}»\nЧи з'явився список підказок?",
            )

        except Exception as e:
            logger.exception("dtek_debug error: %s", e)
            await message.answer(f"❌ Помилка діагностики: {e}")
        finally:
            await browser.close()
