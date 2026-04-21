"""Create users table for multi-tenant OAuth authentication

Stores OAuth identity (Google/GitHub) and maps each user to their
isolated tenant schema.  Lives in the ``public`` schema.

Revision ID: 20260409_0014
Revises: 20260407_0013
Create Date: 2026-04-09 00:01:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0014"
down_revision = "20260407_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column("oauth_provider", sa.String(length=32), nullable=False),
        sa.Column("oauth_provider_id", sa.String(length=255), nullable=False),
        sa.Column("schema_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("schema_name"),
        sa.UniqueConstraint(
            "oauth_provider", "oauth_provider_id", name="uq_users_oauth"
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
