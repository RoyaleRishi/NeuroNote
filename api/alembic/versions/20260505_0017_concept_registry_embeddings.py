"""concept_registry embedding column

Adds a vector(384) embedding column to concept_registry in every tenant schema,
plus an HNSW cosine index for fast nearest-neighbour lookups.

Revision ID: 20260505_0017
Revises: 20260503_0016
Create Date: 2026-05-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260505_0017"
down_revision = "20260503_0016"
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
        bind.execute(
            sa.text(
                f'ALTER TABLE "{schema}".concept_registry '
                "ADD COLUMN IF NOT EXISTS embedding vector(384)"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS "
                f"concept_registry_embedding_hnsw_idx "
                f'ON "{schema}".concept_registry USING hnsw (embedding vector_cosine_ops)'
            )
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
        bind.execute(
            sa.text(
                f'DROP INDEX IF EXISTS "{schema}".concept_registry_embedding_hnsw_idx'
            )
        )
        bind.execute(
            sa.text(
                f'ALTER TABLE "{schema}".concept_registry '
                "DROP COLUMN IF EXISTS embedding"
            )
        )
