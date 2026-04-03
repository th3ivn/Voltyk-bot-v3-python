from __future__ import annotations

import ssl as ssl_module
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings


def _prepare_database_url(url: str) -> tuple[str, dict]:
    """Normalise DATABASE_URL for asyncpg and return (clean_url, connect_args).

    • Auto-converts ``postgresql://`` scheme to ``postgresql+asyncpg://``.
    • Railway internal URLs (hostname contains ``railway.internal``) skip SSL
      entirely — the internal network is already encrypted at transport level.
    • External URLs with ``sslmode=require/verify-*`` get an SSL context with
      disabled hostname verification (Neon / hosted PostgreSQL compatibility).
    • Strips asyncpg-incompatible params (``sslmode``, ``channel_binding``).
    """
    # ── scheme normalisation ─────────────────────────────────────────
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    parsed = urlparse(url)
    connect_args: dict = {}

    is_railway_internal = parsed.hostname and "railway.internal" in parsed.hostname

    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)

        if "sslmode" in params:
            sslmode = params.pop("sslmode")[0]
            # Railway internal network — no SSL needed
            if not is_railway_internal and sslmode in (
                "require", "verify-ca", "verify-full", "prefer",
            ):
                ssl_ctx = ssl_module.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl_module.CERT_NONE
                connect_args["ssl"] = ssl_ctx

        params.pop("channel_binding", None)

        clean_query = urlencode({k: v[0] for k, v in params.items()})
        parsed = parsed._replace(query=clean_query)

    return urlunparse(parsed), connect_args


_clean_url, _connect_args = _prepare_database_url(settings.DATABASE_URL)

# Prevent runaway queries from holding connections indefinitely
_connect_args.setdefault("command_timeout", 30)

engine = create_async_engine(
    _clean_url,
    pool_size=30,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args=_connect_args,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session


async def init_db() -> None:
    from bot.db.base import Base  # noqa: F811

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
