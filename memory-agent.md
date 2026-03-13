# Memory Agent Log — Voltyk Bot v4 (Python Rewrite з нуля)

**Дата старту:** 12 березня 2026  
**Мета:** Повний rewrite з нуля на Python + aiogram 3 + Railway PostgreSQL + Celery.  
**Старий референс:** https://github.com/th3ivn/Voltyk-bot  
**Правило №1 (основне):**  
НІКОЛИ не копіювати жодного рядка старого коду. Все пиши з нуля.  
Але функціонал, користувацький інтерфейс, тексти повідомлень, кнопки (inline + reply), розташування кнопок, всі екрани та повна послідовність екранів і user flows (FSM transitions) — мають бути **100% ідентичними** тому, що бачить користувач у старому боті. Жодного зайвого чи пропущеного екрану.

**Правило №2 (дуже жорстке — обов'язково!):**  
Ніяких костилів, хаків, workarounds, тимчасових фіксів чи "швидких рішень".  
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