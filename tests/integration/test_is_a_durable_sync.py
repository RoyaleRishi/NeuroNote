"""End-to-end: durable IS_A edges survive the note-scoped delete-and-replace.

Runs against PostgreSQL + AGE (skipped on SQLite). Exercises the real
``GraphSyncService._upsert_relations`` path + ``GraphRepository`` against a live
graph, then simulates a note re-sync's delete step and asserts the semantic
hierarchy edge persists while the structural edge is removed.

Run via: make compose-test
"""
from __future__ import annotations

import pytest

from app.nlp.types import ExtractedRelation
from app.services.graph_sync_service import GraphSyncPayload, GraphSyncService

_GRAPH = "nn_user_test0001"
_NOTE = "note-is-a-durable"


def _count_edges(repo, relation_type: str) -> int:
    rows = repo._exec_cypher(
        _GRAPH,
        f"MATCH (:Concept)-[r:{relation_type}]->(:Concept) RETURN r",
    )
    return len(rows)


def _service(db_session) -> GraphSyncService:
    from app.db.repositories.graph_repository import GraphRepository

    svc = object.__new__(GraphSyncService)
    svc._session = db_session  # type: ignore[attr-defined]
    svc._repository = GraphRepository(db_session)  # type: ignore[attr-defined]
    svc._graph_name = _GRAPH  # type: ignore[attr-defined]
    return svc


def _payload() -> GraphSyncPayload:
    return GraphSyncPayload(
        note_id=_NOTE,
        note_title="t",
        subject_id="subj",
        content_hash="h",
        updated_at="2026-06-14T00:00:00Z",
        entities=[],
        relations=[
            # Durable semantic hierarchy edge.
            ExtractedRelation(
                subject_id="concept-deep-neural-network",
                subject_text="deep neural network",
                predicate="IS_A",
                object_id="concept-neural-network",
                object_text="neural network",
                confidence=0.9,
            ),
            # Note-scoped structural edge.
            ExtractedRelation(
                subject_id="concept-deep-neural-network",
                subject_text="deep neural network",
                predicate="MENTIONED_TOGETHER",
                object_id="concept-neural-network",
                object_text="neural network",
                confidence=0.7,
            ),
        ],
        resolved_entities={},
        embedding=None,
    )


def test_is_a_edge_survives_note_delete_but_structural_does_not(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect

    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    svc = _service(db_session)
    repo = svc._repository  # type: ignore[attr-defined]

    # Clean slate for this graph's concept edges (idempotent test re-runs).
    repo.delete_concept_relation_edges(source_note_id=_NOTE, graph_name=_GRAPH)
    repo._exec_cypher(_GRAPH, "MATCH (:Concept)-[r:IS_A]->(:Concept) DELETE r RETURN 1")
    db_session.commit()

    # Initial sync writes both edges.
    svc._upsert_relations(payload=_payload(), now_iso="2026-06-14T00:00:00Z")
    db_session.commit()
    assert _count_edges(repo, "IS_A") == 1
    assert _count_edges(repo, "MENTIONED_TOGETHER") == 1

    # Re-sync deletes note-scoped concept edges (what sync_note_graph does first).
    repo.delete_concept_relation_edges(source_note_id=_NOTE, graph_name=_GRAPH)
    db_session.commit()

    # Durable IS_A survives; structural MENTIONED_TOGETHER is gone.
    assert _count_edges(repo, "IS_A") == 1, "IS_A must persist across the delete"
    assert _count_edges(repo, "MENTIONED_TOGETHER") == 0


def test_durable_is_a_is_returned_by_graph_read(db_session) -> None:
    """fetch_graph_for_notes must surface durable IS_A edges (no source_note_id)
    between concepts the notes mention — otherwise the hierarchy is invisible."""
    from sqlalchemy import inspect as sa_inspect

    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    note_id = "note-isa-read"
    child, parent = "concept-deep-neural-network", "concept-neural-network"

    # Clean slate.
    repo.delete_concept_relation_edges(source_note_id=note_id, graph_name=_GRAPH)
    repo._exec_cypher(_GRAPH, "MATCH (:Concept)-[r:IS_A]->(:Concept) DELETE r RETURN 1")
    repo.delete_note_mention_edges(note_id=note_id, graph_name=_GRAPH)
    db_session.commit()

    # Note + two Entities + MENTIONS edges (so both concepts are "mentioned").
    repo.upsert_node(label="Note", node_id=note_id,
                     properties={"id": note_id}, graph_name=_GRAPH)
    for cid, name in ((child, "deep neural network"), (parent, "neural network")):
        repo.upsert_node(label="Entity", node_id=cid,
                         properties={"id": cid, "name": name, "kind": "concept"},
                         graph_name=_GRAPH)
        repo.upsert_typed_edge(
            source_label="Note", source_id=note_id,
            target_label="Entity", target_id=cid, relation_type="MENTIONS",
            properties={"source_note_id": note_id, "confidence": 0.9},
            graph_name=_GRAPH,
        )
    # Durable IS_A between the two concepts.
    svc = _service(db_session)
    svc._upsert_relations(
        payload=GraphSyncPayload(
            note_id=note_id, note_title="t", subject_id="s", content_hash="h",
            updated_at="2026-06-14T00:00:00Z", entities=[],
            relations=[ExtractedRelation(
                subject_id=child, subject_text="deep neural network",
                predicate="IS_A", object_id=parent, object_text="neural network",
                confidence=0.9,
            )],
            resolved_entities={}, embedding=None,
        ),
        now_iso="2026-06-14T00:00:00Z",
    )
    db_session.commit()

    result = repo.fetch_graph_for_notes(note_ids=[note_id], graph_name=_GRAPH)
    is_a = [r for r in result.relations if r.edge_type == "IS_A"]
    assert any(r.source_id == child and r.target_id == parent for r in is_a), (
        f"durable IS_A not returned by graph read; got {result.relations}"
    )
