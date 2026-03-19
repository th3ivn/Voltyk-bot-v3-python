# Memory Agent Log — Voltyk Bot v4 (Python Rewrite з нуля)

**Дата старту:** 12 березня 2026  
**Мета:** Повний rewrite з нуля на Python + aiogram 3 + Railway PostgreSQL + Celery.  
**Старий референс:** https://github.com/th3ivn/Voltyk-bot  
**Правило №1 (основне):**  
НІКОЛИ не копіювати жодного рядка старого коду. Все пиши з нуля.  
Але функціонал, користувацький інтерфейс, тексти повідомлень, кнопки (inline + reply), розташування кнопок, всі екрани та повна послідовність екранів і user flows (FSM transitions) — мають бути **100% ідентичними** тому, що бачить користувач у старому боті. Жодного зайвого чи пропущеного екрану.

**Правило №2 (дуже жорстке — обов'язково!):**  
Ніяких костилів, хаків , workarounds, тимчасових фіксів чи "швидких рішень".  
Всі рішення мають бути **професійними, чисто написаними, продакшн-рівня** за сучасними best practices (aiogram 3, SQLAlchemy 2.0, Celery 5, asyncpg тощо).  
Якщо існує стандартне, правильне рішення — використовувати тільки його.  
Якщо щось не вписується в архітектуру — краще переробити правильно, ніж ставити костиль.  
Агент зобов'язаний завжди перевіряти це правило перед кожним PR і після нього.

**Правило №3 (виправлення старих проблем):**  
- Ніякого автоблокування каналів через зміну назви/фото/опису. Перевірка каналів — ТІЛЬКИ один раз на добу о 03:00 (окремий Celery task).  
- Якщо користувач заблокований — текст «Ви заблоковані» З кнопками (кнопки залишаються).  
- Всі публікації графіків і сповіщень — тільки через Celery queue з retry (5 спроб, exponential backoff).  
- Сповіщення розділені: bot_notifications і channel_notifications — незалежні сутності.  
- База даних — повністю нова структура, оптимізована під 100k DAU щодня.

**Інструкція для себе перед кожним PR:**
- Прочитай ве��ь цей файл від початку до кінця.
- Після PR дописуй новий розділ з датою, номером PR, що саме зроблено, які рішення прийнято і чому.
- Завжди перевіряй відповідність усім трьом правилам вище.

**Історія змін (агент дописує сюди):**
- [x] PR-1: Повний rewrite з нуля (12 березня 2026)
- [x] PR-2: Виправлення UTF-16 offsets, edit_media, animated emoji (13 березня 2026)
- [x] PR-3: Оновлення aiogram до 3.26, фінальне виправлення date_time entity та _send_schedule_photo (13 березня 2026)
- [x] PR-4: Критичне виправлення — бот не сповіщав про оновлення графіка (18 березня 2026)
- [x] PR-5: Оптимізація HTTP client, Sentry SDK, CI/CD pipeline (19 березня 2026)
- [x] PR-6: GitHub Commits API замість file polling (19 березня 2026)
- [x] PR-7: datetime.utcnow() deprecation, ThrottleMiddleware memory leak, DB sessions, retry 429, graceful shutdown (19 березня 2026)

---

## PR-1: Повний rewrite Voltyk Bot v4 (12 березня 2026)

### Що зроблено:
1. **Повна архітектура проекту** — модульна структура з чітким розділенням:
   - `bot/config.py` — pydantic-settings для конфігурації
   - `bot/db/` — SQLAlchemy 2.0 async моделі (13 таблиць)
   - `bot/keyboards/inline.py` — всі inline клавіатури (60+ функцій)
   - `bot/handlers/` — всі хендлери розділені по модулях
   - `bot/formatter/` — форматування повідомлень
   - `bot/services/` — API, scheduler, power monitor
   - `bot/tasks/` — Celery tasks
   - `bot/middlewares/` — DB session, maintenance, throttle
   - `bot/states/fsm.py` — FSM стани для всіх діалогів

2. **База даних** — повністю нова, нормалізована структура:
   - `users` — основна таблиця
   - `user_notification_settings` — bot_notifications (незалежна сутність)
   - `user_channel_config` — channel_notifications (незалежна сутність)
   - `user_power_tracking` — стан світла
   - `user_message_tracking` — ID повідомлень
   - `tickets` + `ticket_messages` — система тікетів
   - `pending_channels`, `pause_log`, `admin_routers` тощо
   - Оптимізація: індекси, foreign keys з CASCADE

3. **Handlers (100% UI match):**
   - /start + wizard (region → queue → notify_target → notifications → done)
   - Головне меню (Графік, Допомога, Статистика, Таймер, Налаштування)
   - Налаштування (Регіон, IP, Канал, Сповіщення, Очищення, Видалення даних)
   - Канал (підключення, branding, формат, тест, пауза, сповіщення)
   - Адмін (аналітика, користувачі, тікети, розсилка, система, інтервали, debounce, пауза, роутер, підтримка, тех.роботи, growth)
   - Feedback, Region Request, Schedule commands

4. **Celery tasks (Правило №3):**
   - `validate_all_channels` — тільки щоденно о 03:00 (без автоблокування!)
   - `check_all_schedules` — перевірка графіків
   - `publish_schedule` — публікація з retry (5 спроб, exponential backoff)
   - `send_bot_notification` / `send_channel_notification` — розділені!

5. **Docker + Railway** — Dockerfile, docker-compose.yml, railway.json

### Рішення і чому:
- **aiogram 3 FSM** замість ручного state manager — стандартний підхід, менше коду
- **SQLAlchemy 2.0 async** — professional ORM замість raw SQL
- **Normalized DB** — notification_settings та channel_config окремі таблиці (не 40+ колонок в users)
- **Celery** замість BullMQ — Python-native, async-compatible
- **pydantic-settings** — type-safe конфігурація з валідацією

### Відповідність правилам:
- ✅ Правило №1: жодного рядка скопійовано, всі тексти/кнопки/flows ідентичні
- ✅ Правило №2: професійний код, best practices (aiogram 3, SQLAlchemy 2.0, Celery 5)
- ✅ Правило №3: канали перевіряються тільки о 03:00, Celery queue з retry, розділені сповіщення

---

## PR-2: Виправлення критичних багів (13 березня 2026)

### Що зроблено:
1. **`bot/utils/html_to_entities.py`** — Додана функція `_utf16_len(s)` яка повертає `len(s.encode("utf-16-le")) // 2`. Виправлені всі entity offset/length обчислення: `len(text)` → `_utf16_len(text)`. Причина: Telegram Bot API вимагає UTF-16 code unit offsets, а Python `len()` повертає Unicode codepoints. Емодзі (💡, ✅, 🔄, 🪫 тощо) = 2 UTF-16 code units але 1 Python codepoint. Через зсув offset `date_time` entity не застосовувалась і Telegram показував сирий unix timestamp.
2. **`bot/utils/html_to_entities.py` `append_timestamp`** — Оновлені offsets через `_utf16_len`. `custom_emoji` та `date_time` entities тепер правильно накладаються на 🔄 та timestamp string.
3. **`bot/handlers/menu.py`** — `_send_schedule_photo` переписана: при `edit_photo=True` завжди спочатку пробує `edit_media` (незалежно від типу поточного повідомлення), при невдачі — fallback delete+send. `menu_schedule` змінено на `edit_photo=True`.

### Рішення і чому:
- `s.encode("utf-16-le")` — стандартний Python спосіб отримати UTF-16LE bytes, `// 2` дає кількість 16-bit code units
- `edit_media` always first — відповідає логіці старого JS бота (`handleMenuSchedule` в `src/handlers/menu.js`)

### Відповідність правилам:
- ✅ Правило №1: UI ідентичний старому боту — "X секунд тому", анімоване emoji, edit замість delete+send
- ✅ Правило №2: Чистий код без костилів
- ✅ Правило №3: Без змін у логіці каналів/Celery

---

## PR-3: Оновлення aiogram до 3.26, фінальне виправлення date_time entity та _send_schedule_photo (13 березня 2026)

### Що зроблено:
1. **`pyproject.toml`** — підняти мінімальну версію aiogram з `>=3.13,<4` до `>=3.26,<4`. Причина: `date_time` entity (поля `unix_time`, `date_time_format`) та підтримка `custom_emoji_id` в `MessageEntity` з'явились тільки в aiogram 3.26.0 (Bot API 9.5). До цього Telegram отримував невалідну entity і показував сирий unix timestamp (`1773397524`) замість "X хвилин тому", а анімоване emoji 🔄 не рендерилось.
2. **`bot/handlers/menu.py`** — `_send_schedule_photo` переписана: fallback delete+send виведений за межі блоку `if edit_photo:` (структурне виправлення для відповідності логіці старого JS бота). Оновлений docstring чітко описує поведінку при `edit_photo=True` і `False`.

### Рішення і чому:
- Мінімальна вимога aiogram `>=3.26` — це офіційна версія з підтримкою Bot API 9.5, яка вперше дає `MessageEntity(type="date_time", unix_time=..., date_time_format="r")`. Без неї `unix_time`/`date_time_format` ігнорувались — Telegram рендерив сирий timestamp.
- Структура `_send_schedule_photo`: fallback поза `if edit_photo:` — відповідає паттерну старого JS бота `handleMenuSchedule`, де fallback завжди спільний (DRY, читабельніше).

### Відповідність правилам:
- ✅ Правило №1: "X секунд тому" і анімоване 🔄 тепер відображаються коректно; переход меню→графік без flicker (edit_media)
- ✅ Правило №2: Оновлення залежності до актуальної версії — єдине правильне рішення, без костилів
- ✅ Правило №3: Без змін у логіці каналів/Celery
---

## PR-4: Критичне виправлення — бот не сповіщав про оновлення графіка (18 березня 2026)

### Суть проблеми:
Бот повністю ігнорував зміни графіку відключень. Жодне сповіщення не надсилалось ні в особисті чати, ні в канали.

### Кореневі причини (4 баги):

**БАГ №1 (GitHub CDN кеш):** URL `raw.githubusercontent.com` кешується CDN з TTL до 5 хвилин. Бот не додавав cache-busting параметри, тому навіть при реальному HTTP-запиті отримував застарілі дані.

**БАГ №2 (In-memory кеш scheduler):** `fetch_schedule_data` не мав опції `force_refresh`. Scheduler викликав функцію з `cache_ttl_s=interval_s`, але TTL = interval-5s. Оскільки цикл теж спить interval секунд — кеш майже завжди "свіжий" при наступному виклику. Scheduler ніколи не отримував реальні свіжі дані.

**БАГ №3 (Timezone):** `datetime.fromtimestamp(ts)` використовував системний TZ (UTC на Railway), а не Kyiv. Це зсувало дати на ±2-3 год, що давало неправильні ISO дати в events і некоректні хеші. `find_next_event` і formatter також використовували `datetime.now()` (UTC) замість Kyiv TZ.

**БАГ №4 (Зображення CDN кеш):** `fetch_schedule_image` теж не обходив GitHub CDN кеш.

### Що зроблено:

#### `bot/services/api.py`:
1. Додано `import time` та `from zoneinfo import ZoneInfo`, константа `KYIV_TZ`
2. `fetch_schedule_data`: новий параметр `force_refresh: bool = False` — якщо `True`, in-memory кеш ігнорується; cache-busting `?_cb=<unix_ms>` у URL; заголовок `Cache-Control: no-cache, no-store`
3. `fetch_schedule_image`: cache-busting `?_cb=<unix_ms>` у URL; заголовок `Cache-Control: no-cache, no-store`
4. `parse_schedule_for_queue`: `datetime.fromtimestamp(ts)` → `datetime.fromtimestamp(ts, tz=KYIV_TZ)` для `today_date` та `tomorrow_date`
5. `find_next_event`: `datetime.now()` → `datetime.now(KYIV_TZ)` для коректного TZ-aware порівняння

#### `bot/services/scheduler.py`:
1. `_check_single_queue`: `fetch_schedule_data(region, cache_ttl_s=interval_s)` → `fetch_schedule_data(region, force_refresh=True)` — scheduler завжди отримує свіжі дані
2. `flush_pending_notifications`: `fetch_schedule_data(region)` → `fetch_schedule_data(region, force_refresh=True)` — daily flush теж отримує свіжі дані

#### `bot/formatter/schedule.py`:
1. Додано `from zoneinfo import ZoneInfo`, константа `KYIV_TZ`
2. Новий хелпер `_parse_event_dt(dt)`: нормалізує datetime до tz-aware KYIV_TZ — підтримує як нові (tz-aware ISO) так і старі (tz-naive ISO) формати для backward compatibility з даними в DB
3. `format_schedule_message`: `datetime.now()` → `datetime.now(KYIV_TZ)`; всі парсинги та порівняння подій через `_parse_event_dt()`
4. `format_schedule_for_channel`: `datetime.now()` → `datetime.now(KYIV_TZ)`; парсинги та порівняння подій через `_parse_event_dt()`

### Рішення і чому:
- `?_cb=<unix_ms>` — стандартний cache-busting pattern; змінюється при кожному запиті, CDN не може закешувати
- `Cache-Control: no-cache, no-store` — повідомляє proxy/CDN не кешувати відповідь
- `force_refresh=True` — чистий API-design: scheduler завжди потребує свіжих даних, user-facing запити можуть використовувати кеш
- `datetime.fromtimestamp(ts, tz=KYIV_TZ)` — стандартний Python спосіб отримати tz-aware datetime для конкретного TZ
- `_parse_event_dt()` — defensive programming: підтримує обидва формати (tz-aware і tz-naive) без помилок

### Відповідність правилам:
- ✅ Правило №1: UI ідентичний — тексти, кнопки, flows не змінено
- ✅ Правило №2: Всі рішення production-рівня, жодних костилів
- ✅ Правило №3: bot_notifications і channel_notifications незалежні; логіка каналів не змінена

---

## PR-5: Оптимізація HTTP client, Sentry SDK, CI/CD pipeline (19 березня 2026)

### Що зроблено:

#### PR #74 — Оптимізація HTTP client та DB sessions (`bot/services/api.py`, `bot/services/scheduler.py`, `bot/app.py`):
1. Shared `aiohttp.ClientSession` з `TCPConnector(limit=20)` — одна сесія на весь lifetime бота (init/close через `on_startup`/`on_shutdown`).
2. Retry delays зменшено з `[5, 15, 45]` до `[1, 3]` секунд — менше простою при тимчасових збоях.
3. `scheduler.py`: злито 3→1 та 2→1 зайвих DB сесії в `_check_single_queue`.

#### PR #75 — Sentry SDK (`bot/app.py`, `.env.example`):
1. `sentry_sdk.init(...)` з `AsyncioIntegration` + `AioHttpIntegration` в `on_startup`, активується тільки якщо `SENTRY_DSN` задано.
2. `traces_sample_rate=0.1` — мінімальне трейсування без перевантаження квоти.

#### PR #76 — CI/CD pipeline (`.github/workflows/ci.yml`):
1. GitHub Actions: ruff lint + auto-delete merged branches.
2. Ruff як єдиний linter/formatter — стандарт для Python 3.12+.

#### PR #77 — Ruff lint fix:
Виправлено `I001` (unsorted imports) та `W292` (no newline at EOF) — чистка після PR #76.

### Рішення і чому:
- Shared `ClientSession` — офіційна рекомендація aiohttp: одна сесія на застосунок, не одна на запит.
- `TCPConnector(limit=20)` — обмеження пулу з'єднань, запобігає file descriptor exhaustion.
- Sentry `init` в `on_startup` (не на рівні модуля) — Sentry не ініціалізується при тестах та Alembic міграціях.

### Відповідність правилам:
- ✅ Правило №1: UI не змінено
- ✅ Правило №2: Shared session — стандарт aiohttp; Sentry — офіційний SDK
- ✅ Правило №3: Без змін у логіці каналів/сповіщень

---

## PR-6: GitHub Commits API замість file polling (19 березня 2026)

### Суть проблеми:
`fetch_schedule_data` перевіряв зміни графіку через `?_cb=` cache-busting на raw.githubusercontent.com. CDN GitHub кешує raw-файли з TTL до 5 хвилин навіть з різними query params. Детектор змін міг пропускати оновлення.

### Що зроблено (`bot/services/api.py`, `bot/services/scheduler.py`, `bot/config.py`):
1. Новий метод `fetch_schedule_commit_sha(region)` — запитує `api.github.com/repos/.../commits?path=<file>&per_page=1` і повертає SHA останнього коміту для файлу графіку.
2. `_check_single_queue` в `scheduler.py` — порівнює `commit_sha` замість хешу вмісту файлу.
3. `bot/config.py`: нові поля `GITHUB_TOKEN` (optional), `GITHUB_REPO`, `GITHUB_BRANCH` — конфігурабельний репозиторій.
4. Rate limit: GitHub API дає 60 req/год без токену, 5000 — з токеном. При наявності `GITHUB_TOKEN` — автентифікований запит.

### Рішення і чому:
- GitHub Commits API (`/repos/{owner}/{repo}/commits`) — офіційний, не кешований CDN endpoint.
- SHA коміту — детермінований, стабільний ідентифікатор зміни файлу (краще за хеш вмісту, який залежить від CDN).
- `per_page=1` — мінімальна відповідь, тільки останній коміт.

### Відповідність правилам:
- ✅ Правило №1: UI не змінено
- ✅ Правило №2: Офіційний GitHub REST API, без хаків
- ✅ Правило №3: Логіка сповіщень не змінена; детектор змін надійніший

---

## PR-7: Серія технічних виправлень (19 березня 2026)

### PR #79 — `datetime.utcnow()` deprecation (`bot/db/`, `bot/services/`, `bot/tasks/`):
- `datetime.utcnow()` deprecated з Python 3.12 і повертає naive datetime.
- Замінено всі 5 входжень на `datetime.now(UTC)` (tz-aware, `from datetime import UTC`).
- Причина: naive datetimes при порівнянні з tz-aware викидають `TypeError`; в майбутніх Python буде `DeprecationWarning → Error`.

### PR #80 — ThrottleMiddleware memory leak (`bot/middlewares/throttle.py`):
- `_last_call: dict[int, float]` ніколи не очищувався — при 100k DAU займав ~8 MB/добу.
- Додано `_cleanup_interval = 300` (5 хв) і `_cleanup_threshold = 600` (10 хв TTL для неактивних юзерів).
- Cleanup викликається в `__call__` раз на 5 хвилин через `time.monotonic()` — без додаткового фонового таску.

### PR #81 — Оптимізація DB сесій в scheduler (`bot/services/scheduler.py`):
- `_check_single_queue`: 4–5 окремих `async with session_factory() as db:` злито у 3 логічні фази:
  1. Read: хеш + сьогоднішній/вчорашній snapshot.
  2. Write: оновлення хешу + upsert snapshot + черга сповіщень.
  3. Read: активні юзери для розсилки.
- Причина: кожен `session_factory()` — окреме з'єднання з пулу. 4–5 з'єднань × N черг = навантаження на PostgreSQL connection pool.

### PR #82 — Retry на TelegramRetryAfter (429) (`bot/utils/helpers.py`):
- Новий хелпер `retry_bot_call(coro_fn)` — ловить `TelegramRetryAfter`, спить `retry_after + 1` секунд, робить одну повторну спробу.
- Без retry 429 мовчки дропав повідомлення (виняток ловився у верхньому `except Exception`).
- Один retry (не безмежний цикл) — відповідає Telegram рекомендаціям: при flood control достатньо однієї повторної спроби.

### PR #83 — Graceful shutdown (`bot/app.py`):
- `on_shutdown`: після `task.cancel()` для всіх `_bg_tasks` додано `await asyncio.gather(*_bg_tasks, return_exceptions=True)`.
- Причина: `task.cancel()` лише планує CancelledError — без await таски ще виконуються під час teardown DB/HTTP. `return_exceptions=True` — щоб `CancelledError` не переривав shutdown.

### Відповідність правилам:
- ✅ Правило №1: UI не змінено
- ✅ Правило №2: Всі рішення стандартні — UTC-aware datetime, monotonic cleanup, connection pool efficiency, офіційний retry pattern
- ✅ Правило №3: Логіка каналів/сповіщень не змінена
