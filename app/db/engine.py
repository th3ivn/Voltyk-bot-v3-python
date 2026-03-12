"""SQLAlchemy async engine factory for Neon PostgreSQL (asyncpg)."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


def build_engine() -> AsyncEngine:
    """Create and return an async SQLAlchemy engine.

    Uses asyncpg driver with connection pool configured from settings.
    Neon serverless PostgreSQL requires pool_pre_ping for connection health checks.
    """
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_size=settings.DB_POOL_MIN,
        max_overflow=settings.DB_POOL_MAX - settings.DB_POOL_MIN,
        pool_pre_ping=True,
        pool_recycle=300,
    )


engine: AsyncEngine = build_engine()
