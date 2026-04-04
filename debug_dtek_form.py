"""
Run this script on the server to inspect the DTEK form HTML structure.

    python debug_dtek_form.py

It will:
  1. Open https://www.dtek-krem.com.ua/ua/shutdowns
  2. Close any popup
  3. Save a screenshot BEFORE any interaction   → /tmp/step1_page.png
  4. Click the first visible field (city)
  5. Save a screenshot AFTER click              → /tmp/step2_after_city_click.png
  6. Type "Нижча Дубечня"
  7. Save a screenshot AFTER typing             → /tmp/step3_after_city_type.png
  8. Print the FULL form HTML to the terminal (copy-paste it here!)
"""

import asyncio
from playwright.async_api import async_playwright

URL = "https://www.dtek-krem.com.ua/ua/shutdowns"
CITY_VALUE = "Нижча Дубечня"


async def main():
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
        print(f"[1] Opening {URL} ...")
        await page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)

        # ── Close popup ──────────────────────────────────────────────────
        for sel in (
            "button.popup__close", ".popup__close", ".modal__close",
            "button[class*='close']", "[aria-label='close']", "[aria-label='Close']",
            "button:has-text('×')", "button:has-text('✕')",
        ):
            try:
                btn = page.locator(sel).first
                await btn.wait_for(state="visible", timeout=2_000)
                await btn.click()
                print(f"[popup] closed via {sel!r}")
                await page.wait_for_timeout(500)
                break
            except Exception:
                pass

        await page.screenshot(path="/tmp/step1_page.png", full_page=True)
        print("[screenshot] /tmp/step1_page.png  ← initial page state")

        # ── Print all inputs / selects / roles on the page ───────────────
        print("\n[DOM] All <input> elements:")
        inputs = await page.evaluate("""() => {
            return [...document.querySelectorAll('input')].map(el => ({
                tag: el.tagName,
                type: el.type,
                id: el.id,
                name: el.name,
                placeholder: el.placeholder,
                className: el.className,
                visible: el.offsetParent !== null,
                disabled: el.disabled,
            }));
        }""")
        for inp in inputs:
            print("  ", inp)

        print("\n[DOM] All elements with role=combobox / listbox / option:")
        roles = await page.evaluate("""() => {
            return [...document.querySelectorAll('[role]')].map(el => ({
                tag: el.tagName,
                role: el.getAttribute('role'),
                id: el.id,
                className: el.className,
                text: el.textContent.slice(0, 80).trim(),
                visible: el.offsetParent !== null,
            }));
        }""")
        for r in roles:
            print("  ", r)

        print("\n[DOM] Full form HTML:")
        try:
            form_html = await page.locator("form").first.inner_html()
            print(form_html)
        except Exception as e:
            print(f"  (no form found: {e})")
            body_html = await page.locator("body").inner_html()
            print(body_html[:5000])

        # ── Try clicking the first combobox ──────────────────────────────
        combobox_count = await page.get_by_role("combobox").count()
        print(f"\n[combobox] count = {combobox_count}")

        if combobox_count > 0:
            cb = page.get_by_role("combobox").nth(0)
            print("[combobox] clicking nth(0) ...")
            await cb.click()
            await page.wait_for_timeout(800)
            await page.screenshot(path="/tmp/step2_after_city_click.png", full_page=True)
            print("[screenshot] /tmp/step2_after_city_click.png  ← after clicking city field")

            print(f"[keyboard] typing {CITY_VALUE!r} ...")
            await page.keyboard.type(CITY_VALUE, delay=80)
            await page.wait_for_timeout(2_000)
            await page.screenshot(path="/tmp/step3_after_city_type.png", full_page=True)
            print("[screenshot] /tmp/step3_after_city_type.png  ← after typing city")
        else:
            print("[combobox] none found — trying get_by_text('Почніть вводити') ...")
            triggers = page.get_by_text("Почніть вводити", exact=False)
            cnt = await triggers.count()
            print(f"  'Почніть вводити' text elements count = {cnt}")
            if cnt > 0:
                await triggers.nth(0).click()
                await page.wait_for_timeout(800)
                await page.screenshot(path="/tmp/step2_after_city_click.png", full_page=True)
                print("[screenshot] /tmp/step2_after_city_click.png")
                await page.keyboard.type(CITY_VALUE, delay=80)
                await page.wait_for_timeout(2_000)
                await page.screenshot(path="/tmp/step3_after_city_type.png", full_page=True)
                print("[screenshot] /tmp/step3_after_city_type.png")

        await browser.close()
        print("\n[done] Check /tmp/step*.png and copy the HTML above.")


asyncio.run(main())
