"""Integration tests for AGE-aware startup backfill pre-filter.

Requires PostgreSQL + AGE. Run via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_startup_backfill_age.py -v
"""
from __future__ import annotations

import pytest


def test_filter_stale_notes_includes_unsynced_note(db_session) -> None:
    """A note with no Block nodes in AGE must be included in the stale set."""
    from sqlalchemy import inspect as sa_inspect

    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.note_repository import NoteRepository
    from app.services.startup_backfill_service import StartupBackfillService

    # Create a note in the relational DB only (no AGE sync).
    NoteRepository(db_session).upsert_note(
        note_id="backfill-unsynced",
        note_title="Unsynced Note",
        content_json={"type": "doc", "content": []},
        content_text="some content",
        updated_at="2026-05-03T10:00:00Z",
    )
    db_session.commit()

    service = StartupBackfillService()
    stale = service._filter_stale_notes(db_session, ["backfill-unsynced"])
    assert "backfill-unsynced" in stale


def test_filter_stale_notes_excludes_fully_synced_note(db_session) -> None:
    """A note whose blocks are all in AGE with matching hashes must be skipped."""
    from sqlalchemy import inspect as sa_inspect

    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.models.block import Block
    from app.db.repositories.graph_repository import GraphRepository
    from app.db.repositories.note_repository import NoteRepository
    from app.services.startup_backfill_service import StartupBackfillService

    # Create note in relational DB.
    NoteRepository(db_session).upsert_note(
        note_id="backfill-synced",
        note_title="Synced Note",
        content_json={"type": "doc", "content": []},
        content_text="content",
        updated_at="2026-05-03T10:00:00Z",
    )
    db_session.flush()

    # Insert a matching Block in the relational DB.
    block_hash = "synced-content-hash-abc"
    db_session.add(
        Block(
            note_id="backfill-synced",
            block_uid="synced-b1",
            block_index=0,
            content_text="content",
            content_hash=block_hash,
            rich_content={"type": "paragraph"},
            sibling_order=0,
        )
    )
    db_session.flush()

    # Upsert matching Block node into AGE using the test tenant's graph.
    repo = GraphRepository(db_session)
    repo.upsert_node(
        label="Block",
        node_id="backfill-synced:block:synced-b1",
        properties={
            "block_uid": "synced-b1",
            "source_note_id": "backfill-synced",
            "content_hash": block_hash,
            "text": "content",
            "block_index": 0,
            "created_at": "2026-05-03T10:00:00Z",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name="nn_user_test0001",
    )
    db_session.commit()

    service = StartupBackfillService()
    stale = service._filter_stale_notes(
        db_session, ["backfill-synced"], graph_name="nn_user_test0001"
    )
    assert "backfill-synced" not in stale
