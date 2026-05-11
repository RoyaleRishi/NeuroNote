"""Clear plaintext llm_api_key values from all tenant schemas.

Existing stored API keys are plaintext and must be wiped before the
encryption layer is deployed. Users will need to re-enter their API key.

Revision ID: 20260503_0016
Revises: 20260421_0015
Create Date: 2026-05-03 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260503_0016"
down_revision = "20260421_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT schema_name FROM users")
    ).all()
    for (schema_name,) in rows:
        bind.execute(
            sa.text(
                f"UPDATE {schema_name}.user_preferences "
                "SET value = '' WHERE key = 'llm_api_key'"
            )
        )


def downgrade() -> None:
    pass  # clearing values is irreversible by design
