"""Add ON DELETE CASCADE to history table FKs

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-05

outage_history, power_history and schedule_history were created without
ON DELETE CASCADE on their user_id FK. The application worked around this
by explicitly deleting rows in delete_user_data(), but the DB schema had no
defence-in-depth: a direct DELETE on users (manual admin query, future code)
would raise a FK violation without this migration.

Strategy:
- DROP CONSTRAINT IF EXISTS — idempotent, safe in offline SQL scripts and on
  fresh databases where the constraint never existed.
- ADD CONSTRAINT ... NOT VALID — creates the constraint without scanning the
  full table, avoiding an ACCESS EXCLUSIVE lock that would block reads.
- VALIDATE CONSTRAINT — validates existing rows under SHARE UPDATE EXCLUSIVE,
  which does not block concurrent reads or writes.
- ALTER TABLE IF EXISTS — entire statement is a no-op when the table is absent,
  making the migration safe against fresh/empty databases in both online and
  offline (SQL script generation) modes.
"""

from __future__ import annotations

from alembic import op

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
        # Drop old FK (no ON DELETE CASCADE). IF EXISTS makes this a no-op on
        # fresh DBs and on tables that were created via create_all() without it.
        op.execute(
            f"ALTER TABLE IF EXISTS {table} "
            f"DROP CONSTRAINT IF EXISTS {constraint}"
        )
        # Recreate with ON DELETE CASCADE.  NOT VALID skips the full-table
        # scan so no ACCESS EXCLUSIVE lock is held while rows are re-checked.
        op.execute(
            f"ALTER TABLE IF EXISTS {table} "
            f"ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE NOT VALID"
        )
        # Validate existing rows under SHARE UPDATE EXCLUSIVE — does not block
        # concurrent reads or writes.
        op.execute(
            f"ALTER TABLE IF EXISTS {table} VALIDATE CONSTRAINT {constraint}"
        )


def downgrade() -> None:
    for table, constraint in reversed(_TABLES):
        op.execute(
            f"ALTER TABLE IF EXISTS {table} "
            f"DROP CONSTRAINT IF EXISTS {constraint}"
        )
        op.execute(
            f"ALTER TABLE IF EXISTS {table} "
            f"ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY (user_id) REFERENCES users(id)"
        )
