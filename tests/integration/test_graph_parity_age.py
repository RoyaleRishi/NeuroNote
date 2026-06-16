"""Integration tests for SQL↔AGE parity primitives + service.

Run against PostgreSQL+AGE via: make compose-test
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect as sa_inspect

_GRAPH = "nn_user_test0001"


def _require_pg(db_session) -> None:
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")


def _seed_mention(repo, *, note_id: str, entity_id: str, graph: str) -> None:
    """Create a Note node, an Entity node, and a Note→Entity MENTIONS edge."""
    repo.upsert_node(
        label="Note",
        node_id=note_id,
        properties={"id": note_id, "name": note_id, "source_note_id": note_id},
        graph_name=graph,
    )
    repo.upsert_node(
        label="Entity",
        node_id=entity_id,
        properties={"id": entity_id, "name": entity_id, "kind": "concept"},
        graph_name=graph,
    )
    repo.upsert_typed_edge(
        source_label="Note",
        source_id=note_id,
        target_label="Entity",
        target_id=entity_id,
        relation_type="MENTIONS",
        properties={"source_note_id": note_id, "confidence": 0.5},
        graph_name=graph,
    )


def test_fetch_live_mentioned_ids_returns_mentioned_entities(db_session):
    _require_pg(db_session)
    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    _seed_mention(repo, note_id="p-n1", entity_id="p-e1", graph=_GRAPH)
    db_session.commit()

    live = repo.fetch_live_mentioned_ids(graph_name=_GRAPH)
    assert "p-e1" in live


def test_delete_orphan_concept_nodes_removes_unmentioned_entity_and_concept(db_session):
    _require_pg(db_session)
    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    _seed_mention(repo, note_id="p-n2", entity_id="p-keep", graph=_GRAPH)
    repo.upsert_node(
        label="Entity",
        node_id="p-orphan",
        properties={"id": "p-orphan", "name": "orphan", "kind": "concept"},
        graph_name=_GRAPH,
    )
    repo.upsert_node(
        label="Concept",
        node_id="p-orphan",
        properties={"id": "p-orphan", "name": "orphan"},
        graph_name=_GRAPH,
    )
    repo.upsert_node(
        label="Concept",
        node_id="p-keep",
        properties={"id": "p-keep", "name": "keep"},
        graph_name=_GRAPH,
    )
    db_session.commit()

    deleted = repo.delete_orphan_concept_nodes(graph_name=_GRAPH)
    db_session.commit()

    assert "p-orphan" in deleted
    assert "p-keep" not in deleted
    live = repo.fetch_live_mentioned_ids(graph_name=_GRAPH)
    assert "p-keep" in live
