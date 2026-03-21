#!/usr/bin/env python3
"""
Debug script: manually test DTEK emergency outage check.

Usage:
    python debug_dtek_check.py --region kyiv-region --street "Деснянська" --house "1"
    python debug_dtek_check.py --region kyiv-region --street "Деснянська" --house "1" --city "Дубечня"
"""
import argparse
import asyncio
import json
import re
import sys
from typing import Any

import aiohttp

DTEK_SUBDOMAINS = {
    "kyiv": "kem",
    "kyiv-region": "krem",
    "dnipro": "dnem",
    "odesa": "oem",
}

REGIONS_NEEDING_CITY = {"kyiv-region", "dnipro", "odesa"}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "uk-UA,uk;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}


def build_urls(region: str):
    sub = DTEK_SUBDOMAINS.get(region)
    if not sub:
        print(f"❌ Невідомий регіон: {region}")
        print(f"   Доступні: {list(DTEK_SUBDOMAINS.keys())}")
        sys.exit(1)
    return (
        f"https://www.dtek-{sub}.com.ua/ua/shutdowns",
        f"https://www.dtek-{sub}.com.ua/ua/ajax",
    )


def extract_csrf(html: str) -> str | None:
    m = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None


def build_post_body(region: str, street: str, city: str | None) -> dict:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now_str = datetime.now(kyiv_tz).strftime("%d.%m.%Y, %H:%M:%S")

    data: dict[str, str] = {"method": "getHomeNum"}
    idx = 0
    if region in REGIONS_NEEDING_CITY and city:
        data[f"data[{idx}][name]"] = "city"
        data[f"data[{idx}][value]"] = city
        idx += 1
    data[f"data[{idx}][name]"] = "street"
    data[f"data[{idx}][value]"] = street
    idx += 1
    data[f"data[{idx}][name]"] = "updateFact"
    data[f"data[{idx}][value]"] = now_str
    return data


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True, choices=list(DTEK_SUBDOMAINS.keys()))
    parser.add_argument("--street", required=True)
    parser.add_argument("--house", required=True)
    parser.add_argument("--city", default=None)
    args = parser.parse_args()

    homepage_url, ajax_url = build_urls(args.region)

    print(f"\n{'='*60}")
    print(f"Регіон  : {args.region}")
    print(f"Місто   : {args.city or '(не вказано)'}")
    print(f"Вулиця  : {args.street}")
    print(f"Будинок : {args.house}")
    print(f"{'='*60}")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:

        # Step 1: GET homepage → CSRF token
        print(f"\n[1] GET {homepage_url}")
        csrf_token = None
        try:
            async with session.get(homepage_url, headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"    HTTP status: {resp.status}")
                if resp.status == 200:
                    html = await resp.text()
                    csrf_token = extract_csrf(html)
                    if csrf_token:
                        print(f"    ✅ CSRF token знайдено: {csrf_token[:20]}...")
                    else:
                        print("    ⚠️  CSRF token не знайдено в HTML (продовжуємо без нього)")
                else:
                    print(f"    ❌ Сайт повернув {resp.status}")
                    await resp.read()
        except Exception as e:
            print(f"    ❌ Помилка GET: {e}")

        # Step 2: POST AJAX
        post_body = build_post_body(args.region, args.street, args.city)
        headers = dict(BROWSER_HEADERS)
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["Referer"] = homepage_url
        headers["Origin"] = homepage_url.rsplit("/ua/", 1)[0]
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token

        print(f"\n[2] POST {ajax_url}")
        print(f"    Тіло запиту: {json.dumps(post_body, ensure_ascii=False)}")
        try:
            async with session.post(ajax_url, data=post_body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                print(f"    HTTP status: {resp.status}")
                raw_text = await resp.text()

                if resp.status != 200:
                    print(f"    ❌ Помилка відповіді")
                    print(f"    Тіло: {raw_text[:500]}")
                    return

                try:
                    data: dict[str, Any] = json.loads(raw_text)
                except json.JSONDecodeError:
                    print(f"    ❌ Відповідь не є JSON:")
                    print(f"    {raw_text[:500]}")
                    return

                print(f"\n[3] Відповідь DTEK:")
                print(f"    showCurOutageParam: {data.get('showCurOutageParam')}")

                outage_data = data.get("Data") or {}
                if not data.get("showCurOutageParam"):
                    print("\n    ✅ showCurOutageParam = False/None")
                    print("       → Аварійних відключень для цієї вулиці НЕМАЄ")
                else:
                    print(f"\n    ⚠️  showCurOutageParam = True → є аварійні дані")
                    print(f"    Будинки у відповіді: {list(outage_data.keys()) or '(порожньо)'}")

                    house_normalized = args.house.strip().upper()
                    found = None
                    for key, val in outage_data.items():
                        if str(key).strip().upper() == house_normalized:
                            found = val
                            break

                    if found:
                        print(f"\n    🚨 Будинок {args.house} ЗНАЙДЕНО у аварійних відключеннях!")
                        print(f"    Дані: {json.dumps(found, ensure_ascii=False, indent=6)}")
                    else:
                        print(f"\n    ✅ Будинок {args.house} НЕ знайдено серед аварійних")
                        if outage_data:
                            print(f"       Є інші будинки: {list(outage_data.keys())[:10]}")
                            print(f"       (можливо номер будинку написаний інакше?)")

                print(f"\n[4] Повна відповідь JSON (для аналізу):")
                print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

        except Exception as e:
            print(f"    ❌ Помилка POST: {e}")

    print(f"\n{'='*60}")
    print("Перевірку завершено.")


if __name__ == "__main__":
    asyncio.run(main())
