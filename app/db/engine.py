"""SQLAlchemy async engine factory for PostgreSQL (Railway / Neon) via asyncpg."""

import ssl as _ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


def prepare_database_url(url: str) -> tuple[str, dict]:
    """Strip sslmode from the URL query params and return (cleaned_url, connect_args).

    asyncpg does not accept the ``sslmode`` query parameter that some PostgreSQL
    DATABASE_URLs (e.g. Neon) include.  This helper removes it and converts it to
    an ``ssl`` entry in ``connect_args`` that asyncpg understands.
    Railway PostgreSQL URLs without ``sslmode`` pass through unchanged.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    connect_args: dict = {}

    sslmode = params.pop("sslmode", [None])[0]
    if sslmode and sslmode != "disable":
        # Use the default SSL context so server certificates are verified.
        connect_args["ssl"] = _ssl.create_default_context()

    new_query = urlencode({k: v[0] for k, v in params.items()})
    cleaned = urlunparse(parsed._replace(query=new_query))
    return cleaned, connect_args


def build_engine() -> AsyncEngine:
    """Create and return an async SQLAlchemy engine.

    Uses asyncpg driver with connection pool configured from settings.
    pool_pre_ping is enabled for connection health checks (required for Railway
    and Neon serverless PostgreSQL alike).
    """
    url, connect_args = prepare_database_url(settings.DATABASE_URL)
    return create_async_engine(
        url,
        echo=settings.DEBUG,
        pool_size=settings.DB_POOL_MIN,
        max_overflow=settings.DB_POOL_MAX - settings.DB_POOL_MIN,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args=connect_args,
    )


engine: AsyncEngine = build_engine()
