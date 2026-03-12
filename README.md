# Voltyk Bot v3 — Python Rewrite

Telegram bot for electricity schedule notifications in Ukraine.

## Stack

| Layer | Technology |
|---|---|
| Bot framework | [aiogram 3](https://docs.aiogram.dev/) |
| Database | [Neon PostgreSQL](https://neon.tech/) (serverless) |
| ORM / migrations | SQLAlchemy 2.0 + Alembic |
| DB driver | asyncpg |
| Task queue | Celery 5 + Redis |
| Config | pydantic-settings |
| Python | ≥ 3.11 |

## Features

- Electricity schedule notifications per region and group
- Channel notification support (separate queue)
- Daily channel verification at 03:00 via Celery Beat (no auto-blocking)
- Blocked users see a message with buttons preserved
- All notifications sent via Celery queue with 5-retry exponential backoff
- Optimised for 100 000 DAU (connection pooling, proper DB indexes)

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/th3ivn/Voltyk-bot-v3-python.git
cd Voltyk-bot-v3-python
cp .env.example .env
# Fill in BOT_TOKEN and DATABASE_URL in .env
```

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Start the bot (polling)

```bash
python -m app.main
```

### Docker

```bash
docker-compose up --build
```

This starts:
- `bot` — aiogram polling worker
- `celery_worker` — Celery task worker
- `celery_beat` — Celery Beat scheduler
- `redis` — Redis broker

> **Note:** PostgreSQL (Neon) is external. Configure `DATABASE_URL` in `.env`.

## Project Structure

```
app/
├── main.py          # Entry point
├── config.py        # pydantic-settings configuration
├── bot.py           # Bot + Dispatcher factory
├── db/
│   ├── engine.py    # Async SQLAlchemy engine
│   ├── session.py   # AsyncSession factory
│   └── models/      # SQLAlchemy 2.0 models
├── handlers/        # aiogram routers
├── keyboards/       # Inline + reply keyboards
├── middleware/      # aiogram middleware
├── services/        # Business logic
├── tasks/
│   └── celery_app.py  # Celery instance + Beat schedule
└── utils/
alembic/             # Database migrations
```

## Development

```bash
# Lint
ruff check app/

# Tests
pytest tests/ -v

# Generate a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

## License

MIT
