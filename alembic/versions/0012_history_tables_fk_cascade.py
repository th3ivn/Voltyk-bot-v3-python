"""Add ON DELETE CASCADE to history table FKs

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-05

outage_history, power_history and schedule_history were created without
ON DELETE CASCADE on their user_id FK. The application worked around this
by explicitly deleting rows in delete_user_data(), but the DB schema had no
defence-in-depth: a direct DELETE on users (manual admin query, future code)
would raise a FK violation without this migration.

Strategy: drop the old FK constraint, recreate with ON DELETE CASCADE using
NOT VALID so the lock is minimal (no full table scan to re-check existing
rows), then validate in a separate ALTER TABLE which takes a lighter
SHARE UPDATE EXCLUSIVE lock instead of ACCESS EXCLUSIVE.

Guards: each step is wrapped in a table/constraint existence check so the
migration is safe to run against a fresh database (no tables yet) or any
environment where the tables were created without these constraints.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op


def _table_exists(name: str) -> bool:
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


def _constraint_exists(table: str, constraint: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.table_constraints "
            "  WHERE table_schema='public' AND table_name=:t AND constraint_name=:c"
            ")"
        ),
        {"t": table, "c": constraint},
    )
    return bool(result.scalar())


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# (table_name, fk_constraint_name)
_TABLES = [
    ("outage_history", "outage_history_user_id_fkey"),
    ("power_history", "power_history_user_id_fkey"),
    ("schedule_history", "schedule_history_user_id_fkey"),
]


def upgrade() -> None:
    for table, constraint in _TABLES:
        if not _table_exists(table):
            continue

        # Drop old FK (no ON DELETE CASCADE) — only if it actually exists.
        if _constraint_exists(table, constraint):
            op.drop_constraint(constraint, table, type_="foreignkey")

        # Recreate with ON DELETE CASCADE using NOT VALID to avoid an
        # ACCESS EXCLUSIVE lock that would block reads during the scan.
        op.create_foreign_key(
            constraint,
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
            postgresql_not_valid=True,
        )

        # Validate in a separate statement — takes SHARE UPDATE EXCLUSIVE,
        # which does not block concurrent reads or writes.
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")


def downgrade() -> None:
    for table, constraint in reversed(_TABLES):
        if not _table_exists(table):
            continue
        if _constraint_exists(table, constraint):
            op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            "users",
            ["user_id"],
            ["id"],
        )
