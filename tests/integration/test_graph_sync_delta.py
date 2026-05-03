"""Integration tests for AGE graph delta sync read methods.

Run against PostgreSQL+AGE via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py -v
"""
from __future__ import annotations

import pytest

_GRAPH = "nn_user_test0001"


def test_fetch_block_states_returns_empty_for_unsynced_note(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    states = repo.fetch_block_states(note_id="nonexistent-note", graph_name=_GRAPH)
    assert states == {}


def test_fetch_block_states_returns_correct_hash_after_upsert(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    repo.upsert_node(
        label="Block",
        node_id="delta-note1:block:b1",
        properties={
            "id": "delta-note1:block:b1",
            "block_uid": "b1",
            "source_note_id": "delta-note1",
            "content_hash": "hash-abc",
            "text": "hello",
            "block_index": 0,
            "created_at": "2026-05-03T10:00:00Z",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    db_session.commit()

    states = repo.fetch_block_states(note_id="delta-note1", graph_name=_GRAPH)
    assert states == {"b1": "hash-abc"}


def test_fetch_graph_for_notes_returns_empty_when_no_data(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    result = repo.fetch_graph_for_notes(
        note_ids=["no-such-note"],
        min_confidence=0.0,
        graph_name=_GRAPH,
    )
    assert result.mentions == []
    assert result.relations == []


def test_fetch_graph_for_notes_returns_mentions_and_relations(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)

    # Seed: Note node, Entity node, Note→Entity MENTIONS edge
    repo.upsert_node(
        label="Note",
        node_id="fetch-note1",
        properties={
            "id": "fetch-note1",
            "source_note_id": "fetch-note1",
            "name": "Test Note",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_node(
        label="Entity",
        node_id="concept-python",
        properties={
            "id": "concept-python",
            "name": "Python",
            "kind": "concept",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_typed_edge(
        source_label="Note",
        source_id="fetch-note1",
        target_label="Entity",
        target_id="concept-python",
        relation_type="MENTIONS",
        properties={
            "source_note_id": "fetch-note1",
            "confidence": 0.9,
            "created_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )

    # Seed: Concept nodes + typed relation edge
    repo.upsert_node(
        label="Concept",
        node_id="concept-python",
        properties={
            "id": "concept-python",
            "name": "Python",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_node(
        label="Concept",
        node_id="concept-django",
        properties={
            "id": "concept-django",
            "name": "Django",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_typed_edge(
        source_label="Concept",
        source_id="concept-python",
        target_label="Concept",
        target_id="concept-django",
        relation_type="USES",
        properties={
            "source_note_id": "fetch-note1",
            "confidence": 0.85,
            "predicate": "USES",
            "created_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    db_session.commit()

    result = repo.fetch_graph_for_notes(
        note_ids=["fetch-note1"],
        min_confidence=0.0,
        graph_name=_GRAPH,
    )

    entity_ids = {m.entity_id for m in result.mentions}
    assert "concept-python" in entity_ids

    rel_keys = {(r.source_id, r.target_id, r.edge_type) for r in result.relations}
    assert ("concept-python", "concept-django", "USES") in rel_keys
