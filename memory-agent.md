# Memory Agent Log — Voltyk Bot v4 (Python Rewrite з нуля)

**Дата старту:** 12 березня 2026  
**Мета:** Повний rewrite з нуля на Python + aiogram 3 + Neon + Celery.  
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
- [x] PR-1: Скелет проєкту + Конфігурація + Моделі БД + Celery + Alembic + Docker (12 березня 2026)
  - Створено повну структуру папок: app/, alembic/, handlers, keyboards, middleware, services, tasks, utils
  - config.py: pydantic-settings з усіма змінними; ADMIN_IDS автоматично парситься з "123,456" → list[int]
  - SQLAlchemy 2.0 моделі (13 таблиць): users, channels, pending_channels, schedule_history, schedule_checks, bot_notifications, channel_notifications, power_history, tickets, admin_routers, settings, pause_logs, daily_metrics
  - Всі моделі: Mapped[] + mapped_column(), UUID PK (де потрібно), proper indexes під 100k DAU
  - BotNotification і ChannelNotification — окремі сутності (Правило №3)
  - db/engine.py: create_async_engine з asyncpg, pool_pre_ping=True для Neon serverless
  - db/session.py: async_sessionmaker (expire_on_commit=False)
  - tasks/celery_app.py: Celery + Redis, json serializer, Europe/Kyiv, beat_schedule: check-channels о 03:00 (Правило №3), task_routes для notifications/schedule/channels черг
  - bot.py: aiogram Bot (HTML parse_mode) + Dispatcher з RedisStorage для FSM
  - main.py: polling або webhook залежно від WEBHOOK_URL, startup/shutdown hooks (DB dispose, bot session close)
  - alembic/env.py: async migrations, автоімпорт всіх моделей для autogenerate
  - pyproject.toml: всі залежності, ruff конфіг, pytest налаштування
  - .env.example, .gitignore, Dockerfile (multi-stage), docker-compose.yml (bot + celery_worker + celery_beat + redis)
  - Рішення: Settings модель (key-value) для глобальних налаштувань бота; DailyMetrics unique constraint на date; ScheduleHistory unique на (region_id, group_id, date)
  - Весь код з нуля, коментарі англійською, .env.example коментарі українською
- [x] PR-2: /start handler + registration FSM + region/queue selection + main menu (12 березня 2026)
  - Додано поле `queue` (String(8)) до моделі User для зберігання черги у форматі "3.2", "15.1" тощо
  - Створено app/constants/regions.py: REGIONS, REGION_CODE_TO_ID, QUEUES, KYIV_QUEUES, REGION_QUEUES, get_queues_for_region()
  - Створено app/states/registration.py: RegistrationFSM з трьома станами (choosing_region, choosing_queue, confirming)
  - Створено app/middleware/database.py: DatabaseMiddleware — ін'єктує async DB сесію в data["session"] кожного хендлера
  - Створено app/services/user_service.py: get_or_create_user (upsert через ON CONFLICT), get_user, update_user_region
  - Створено app/keyboards/inline.py: get_region_keyboard, get_queue_keyboard (з пагінацією для Київ), get_confirm_keyboard, get_main_menu, get_blocked_keyboard
  - Створено app/handlers/start.py: /start хендлер + повний FSM флоу реєстрації (region → queue → confirm → main menu)
  - Правило №3 дотримано: заблоковані користувачі бачать "🚫 Ви заблоковані." З кнопкою
  - Оновлено app/handlers/__init__.py: register_all_handlers(dp)
  - Оновлено app/bot.py: реєструє DatabaseMiddleware + всі хендлери через register_all_handlers
  - Оновлено app/main.py: run_migrations() на старті — Alembic upgrade head через executor
  - Створено alembic/versions/20260312_2056_f7036c5d8d16_initial_migration.py: всі таблиці + queue колонка
  - Рішення: region_id як int (1-4), group_id як int (число до крапки в "3.2"), queue як raw рядок; пагінація Київ — 5 сторінок (стор 1: стандартні 12, стор 2-5: extra 54 по 12 шт.)