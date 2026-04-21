"""Add user_preferences table to all tenant schemas

Key-value store for per-user settings (LLM mode, API keys, etc.).
New tenant schemas get it from the template; this migration adds it
to any existing tenants.

Revision ID: 20260421_0015
Revises: 20260409_0014
Create Date: 2026-04-21 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0015"
down_revision = "20260409_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Find all tenant schemas.
    rows = bind.execute(
        sa.text("SELECT schema_name FROM users")
    ).all()

    for (schema_name,) in rows:
        bind.execute(
            sa.text(
                f"CREATE TABLE IF NOT EXISTS {schema_name}.user_preferences ("
                "  key VARCHAR(64) NOT NULL,"
                "  value TEXT NOT NULL,"
                "  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),"
                "  PRIMARY KEY (key)"
                ")"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT schema_name FROM users")
    ).all()
    for (schema_name,) in rows:
        bind.execute(
            sa.text(f"DROP TABLE IF EXISTS {schema_name}.user_preferences")
        )
