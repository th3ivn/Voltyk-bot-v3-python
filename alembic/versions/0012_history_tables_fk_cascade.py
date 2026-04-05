"""Add ON DELETE CASCADE to history table FKs

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-05

outage_history, power_history and schedule_history were created without
ON DELETE CASCADE on their user_id FK. The application worked around this
by explicitly deleting rows in delete_user_data(), but the DB-level constraint
provides defence-in-depth: a direct DELETE on users (e.g. manual admin query
or a future code path that bypasses delete_user_data) would raise a FK
violation without this migration.

Strategy: drop the old FK constraint, recreate with ON DELETE CASCADE.
PostgreSQL requires the constraint to be named; we use a deterministic name
that matches SQLAlchemy's default naming convention.
"""

from __future__ import annotations

from alembic import op


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# (table, constraint_name, column)
_TABLES = [
    ("outage_history", "outage_history_user_id_fkey"),
    ("power_history", "power_history_user_id_fkey"),
    ("schedule_history", "schedule_history_user_id_fkey"),
]


def upgrade() -> None:
    for table, constraint in _TABLES:
        # Drop old FK (no ON DELETE CASCADE)
        op.drop_constraint(constraint, table, type_="foreignkey")
        # Recreate with ON DELETE CASCADE
        op.create_foreign_key(
            constraint,
            table,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table, constraint in reversed(_TABLES):
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            "users",
            ["user_id"],
            ["id"],
        )
