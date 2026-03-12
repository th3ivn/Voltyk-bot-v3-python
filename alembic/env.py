"""Alembic environment configuration for async SQLAlchemy (asyncpg).

Imports all models so Alembic can detect schema changes automatically.
"""

import asyncio
from logging.config import fileConfig

# Load .env so DATABASE_URL is available without a running app
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

load_dotenv()

from app.config import settings
from app.db.engine import prepare_database_url
from app.db.models import Base

# Alembic Config object
config = context.config

# Strip asyncpg-incompatible sslmode param before setting the URL
_clean_url, _ = prepare_database_url(settings.DATABASE_URL)

# Override sqlalchemy.url with the value from pydantic settings
config.set_main_option("sqlalchemy.url", _clean_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection required)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    url, connect_args = prepare_database_url(settings.DATABASE_URL)
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (requires async engine)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
