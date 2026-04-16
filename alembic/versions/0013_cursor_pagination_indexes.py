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

Strategy:
- CREATE INDEX CONCURRENTLY — builds the index without holding an Access
  Exclusive lock on the table, so reads and writes are not blocked during the
  build.  This requires the statement to run outside an explicit transaction
  block; we therefore COMMIT the Alembic transaction before issuing the DDL.
- IF NOT EXISTS — makes the upgrade idempotent: safe on fresh databases and
  on re-runs after a partial failure.
- DROP INDEX CONCURRENTLY IF EXISTS in downgrade — symmetric approach, no lock.
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_INDEX_NAME = "idx_users_region_queue_active"
_TABLE_NAME = "users"


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    # autocommit_block() is the correct Alembic >= 1.7 API: it commits the
    # current transaction, executes the DDL in autocommit mode, and works
    # with both sync (psycopg2) and async (asyncpg) SQLAlchemy drivers —
    # unlike raw op.execute("COMMIT") which is unreliable with asyncpg.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
            f"ON {_TABLE_NAME} (is_active, region, queue, id)"
        )


def downgrade() -> None:
    # DROP INDEX CONCURRENTLY is also a non-transactional statement.
    with op.get_context().autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}"
        )
