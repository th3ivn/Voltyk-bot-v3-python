"""Add composite index for cursor-based pagination on users

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-15

Cursor-based pagination iterates over the users table with a query of the form:

    SELECT ... FROM users
    WHERE is_active = true AND region = $1 AND queue = $2 AND id > $3
    ORDER BY id
    LIMIT 1000

The existing indexes (idx_users_region_queue, idx_users_active_region) do not
cover all four predicates simultaneously, so Postgres falls back to either a
partial index scan or a sequential scan on large result sets.

A single covering index on (is_active, region, queue, id) satisfies all WHERE
conditions as equality/range lookups and provides the ORDER BY id order for
free — no extra sort step is needed.

Note: CREATE INDEX CONCURRENTLY cannot run inside an Alembic transaction block,
and its async-driver compatibility (asyncpg + run_sync) is fragile across
Alembic versions.  A regular CREATE INDEX is used here instead; it holds an
Access Exclusive lock only for the duration of the build, which is acceptable
for most deployments.  On very large tables, run this migration during a
maintenance window or apply the index manually with CONCURRENTLY before running
alembic upgrade head.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_INDEX_NAME = "idx_users_region_queue_active"
_TABLE_NAME = "users"


def _table_exists(name: str) -> bool:
    """Return True if the table exists in the public schema (online mode only)."""
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t)"
        ),
        {"t": name},
    )
    return bool(result.scalar())


def upgrade() -> None:
    if not _table_exists(_TABLE_NAME):
        return
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
        f"ON {_TABLE_NAME} (is_active, region, queue, id)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
