# Memory Agent Log — Voltyk Bot v3 (Python Rewrite)

**Дата старту:** 12 березня 2026  
**Мета:** Повний rewrite з нуля на Python + aiogram 3 + Neon + Celery.  
**Старий референс:** https://github.com/th3ivn/Voltyk-bot  
**Правило №1:** НІКОЛИ не копіювати жодного рядка старого коду. Тільки функціонал і 100% ідентичні тексти/кнопки/екрани/послідовність.

**Інструкція для себе перед кожним PR:**
- Прочитай весь цей файл від початку до кінця.
- Після PR дописуй новий розділ.
- Обов’язково додай блок «Ключові сніпети» з прикладами коду (5–15 рядків на найважливіші зміни).
- Завжди перевіряй: немає автоблокування, перевірка каналів тільки о 03:00, екрани та флоу 100% як у старому боті.

**Історія змін (агент дописує сюди):**
- [x] PR-1: структура + Docker + Neon + /start wizard
- [ ] PR-2: БД моделі + Alembic
...

──────────────────────────────────
**Ключові сніпети (агент додає сюди після кожного PR)**

### PR-1 (12 березня 2026)
**Що зроблено:**
- Повна структура проєкту: src/bot/, src/core/, src/db/, src/queues/, src/tasks/
- Dockerfile (multi-stage) + docker-compose.yml (Redis + Celery worker + Celery beat)
- railway.json, .env.example, pyproject.toml
- aiogram 3 webhook + healthcheck (src/bot/main.py)
- FSM wizard: WizardStates (region → queue → notify_target → channel_setup → confirm)
- /start handler з точними текстами та кнопками як у старому боті
- Inline keyboards: region (2 колонки), queue (3 або 4 в рядку, Kyiv — 5 сторінок), notify target, main menu
- SQLAlchemy async engine (Neon Postgres)
- Alembic конфігурація
- Celery + Redis + Beat (channel check о 03:00)
- 13 тестів (constants + keyboards)

**Ключовий сніпет — WizardStates:**
```python
class WizardStates(StatesGroup):
    region = State()
    queue = State()
    notify_target = State()
    channel_setup = State()
    confirm = State()
```

**Ключовий сніпет — /start (new user wizard step 1):**
```python
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.set_state(WizardStates.region)
    await state.update_data(mode="new")
    await message.answer(
        '<tg-emoji emoji-id="5472055112702629499">👋</tg-emoji> Вітаю! Я СвітлоБот ⚡\n\n'
        "Слідкую за відключеннями світла і одразу\n"
        "повідомлю, як тільки щось зміниться.\n\n"
        "Налаштування займе ~1 хвилину.\n\n"
        "📍 Крок 1 із 3 — Оберіть свій регіон:",
        parse_mode="HTML", reply_markup=get_region_keyboard(),
    )
```

**Ключовий сніпет — Region keyboard:**
```python
def get_region_keyboard() -> InlineKeyboardMarkup:
    # Row 1: Київ | Київщина
    # Row 2: Дніпропетровщина | Одещина
    # Row 3: 🏙 Запропонувати регіон
```

**Ключовий сніпет — Celery Beat (03:00 channel check):**
```python
celery_app.conf.update(
    beat_schedule={
        "daily-channel-check": {
            "task": "src.tasks.channel_check.check_all_channels",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
```

**Ключовий сніпет — DB engine (async):**
```python
_engine = create_async_engine(settings.database_url, pool_size=settings.db_pool_size)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
```
