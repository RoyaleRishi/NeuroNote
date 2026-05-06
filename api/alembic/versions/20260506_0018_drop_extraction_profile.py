"""drop extraction_profile from nlp_extraction_cache

Revision ID: 20260506_0018
Revises: 20260505_0017
Create Date: 2026-05-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260506_0018"
down_revision = "20260505_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    schemas = [
        r[0] for r in bind.execute(
            sa.text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'user\\_%' ESCAPE '\\'"
            )
        ).all()
    ]
    for schema in schemas:
        op.execute(
            f'ALTER TABLE "{schema}".nlp_extraction_cache '
            f'DROP COLUMN IF EXISTS extraction_profile'
        )


def downgrade() -> None:
    bind = op.get_bind()
    schemas = [
        r[0] for r in bind.execute(
            sa.text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'user\\_%' ESCAPE '\\'"
            )
        ).all()
    ]
    for schema in schemas:
        op.execute(
            f'ALTER TABLE "{schema}".nlp_extraction_cache '
            f'ADD COLUMN IF NOT EXISTS extraction_profile VARCHAR(64)'
        )
