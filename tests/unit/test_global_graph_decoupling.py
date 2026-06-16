"""Service-level tests for the decoupled graph thresholds.

The AGE fetch is mocked so these run on any DB: they verify the *service* logic —
salience normalization, the node-salience gate, the both-endpoints edge rule, and
that the relationship threshold is passed through to the repository (where the
real Cypher filter lives, covered by the AGE integration tests).
"""
from __future__ import annotations

import pytest

import app.services.global_graph_service as ggs
from app.db.engine import get_session_factory
from app.db.repositories.graph_repository import (
    EntityMention,
    GraphFetchResult,
    RelationEdge,
)
from app.db.repositories.note_repository import NoteRepository
from app.services.global_graph_service import GlobalGraphQuery, GlobalGraphService


def _save_note(note_id: str, title: str, updated_at: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id=note_id,
                note_title=title,
                content_json={"type": "doc", "content": []},
                content_text="body",
                updated_at=updated_at,
            )


def _fake_fetch(captured: dict):
    """A fetch_graph_for_notes stand-in: A is salient (raw 0.51 -> norm 0.85),
    B is weak (raw 0.18 -> norm 0.30); A IS_A B (0.9) and MENTIONED_TOGETHER (0.7)."""

    def _inner(self, *, note_ids, salience_floor=0.0, relation_min_confidence=0.0, graph_name="neuronote"):  # noqa: ANN001
        captured["salience_floor"] = salience_floor
        captured["relation_min_confidence"] = relation_min_confidence
        nid = note_ids[0]
        mentions = [
            EntityMention("concept-a", "Concept A", "concept", nid, 0.51),
            EntityMention("concept-b", "Concept B", "concept", nid, 0.18),
        ]
        relations = [
            RelationEdge("concept-a", "concept-b", "IS_A", 0.9, ""),
            RelationEdge("concept-a", "concept-b", "MENTIONED_TOGETHER", 0.7, nid),
        ]
        return GraphFetchResult(mentions=mentions, relations=relations)

    return _inner


def _query(node_threshold: float, rel_threshold: float) -> GlobalGraphQuery:
    return GlobalGraphQuery(
        limit_nodes=500,
        node_salience_threshold=node_threshold,
        relationship_confidence_threshold=rel_threshold,
        include_types=["note", "entity", "relation"],
    )


def test_node_salience_gate_uses_normalized_value(configured_db: None, monkeypatch) -> None:
    _save_note("decoupling-note", "Decoupling Note", "2026-06-15T10:00:00Z")
    captured: dict = {}
    monkeypatch.setattr(ggs.GraphRepository, "fetch_graph_for_notes", _fake_fetch(captured))

    factory = get_session_factory()
    with factory() as session:
        # Low node threshold: both concepts survive; emitted confidence is normalized.
        resp = GlobalGraphService(session).get_global_graph(_query(0.0, 0.0))

    by_id = {n.id: n for n in resp.nodes}
    assert "concept-a" in by_id and "concept-b" in by_id
    assert by_id["concept-a"].confidence == pytest.approx(0.85)  # 0.51 / 0.6
    assert by_id["concept-b"].confidence == pytest.approx(0.30)  # 0.18 / 0.6
    # MENTIONS fetched unfiltered; relationship threshold passed through to repo.
    assert captured["salience_floor"] == 0.0
    assert captured["relation_min_confidence"] == 0.0


def test_raising_node_threshold_drops_weak_concept_and_its_edges(
    configured_db: None, monkeypatch
) -> None:
    _save_note("decoupling-note2", "Decoupling Note 2", "2026-06-15T10:01:00Z")
    captured: dict = {}
    monkeypatch.setattr(ggs.GraphRepository, "fetch_graph_for_notes", _fake_fetch(captured))

    factory = get_session_factory()
    with factory() as session:
        # node threshold 0.5 keeps A (0.85) but drops B (0.30).
        resp = GlobalGraphService(session).get_global_graph(_query(0.5, 0.0))

    node_ids = {n.id for n in resp.nodes}
    assert "concept-a" in node_ids
    assert "concept-b" not in node_ids
    # Concept→Concept edges need both endpoints — A→B edges vanish with B gone.
    rel_types = {e.type for e in resp.edges if e.type in {"IS_A", "MENTIONED_TOGETHER"}}
    assert rel_types == set()
    # A's MENTIONS edge to its note remains (node still present).
    assert any(e.type == "MENTIONS" and e.target == "concept-a" for e in resp.edges)


def test_relationship_threshold_is_forwarded_to_repository(
    configured_db: None, monkeypatch
) -> None:
    _save_note("decoupling-note3", "Decoupling Note 3", "2026-06-15T10:02:00Z")
    captured: dict = {}
    monkeypatch.setattr(ggs.GraphRepository, "fetch_graph_for_notes", _fake_fetch(captured))

    factory = get_session_factory()
    with factory() as session:
        GlobalGraphService(session).get_global_graph(_query(0.0, 0.8))

    # Node salience is decided in-service (floor 0); relationship gating is the
    # repository's job (real Cypher filter) — assert the value reaches it intact.
    assert captured["salience_floor"] == 0.0
    assert captured["relation_min_confidence"] == 0.8
