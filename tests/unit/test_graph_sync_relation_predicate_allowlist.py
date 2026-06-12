"""Graph sync must persist structural predicates exactly, and skip unknowns with a warning."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from app.services.graph_sync_service import GraphSyncPayload, GraphSyncService
from app.nlp.types import ExtractedRelation


def _make_payload(predicate: str) -> GraphSyncPayload:
    return GraphSyncPayload(
        note_id="note-x",
        note_title="t",
        subject_id="subj-x",
        content_hash="hash-x",
        updated_at="2026-05-09T00:00:00Z",
        entities=[],
        relations=[
            ExtractedRelation(
                subject_id="concept-a",
                subject_text="a",
                predicate=predicate,
                object_id="concept-b",
                object_text="b",
                confidence=0.7,
            ),
        ],
        resolved_entities={},
        embedding=None,
    )


class _FakeGraphRepository:
    """Minimal fake that records upsert_typed_edge calls."""

    def __init__(self, session) -> None:
        self.upsert_typed_edge = MagicMock()
        self.upsert_node = MagicMock()
        self.upsert_nodes_batch = MagicMock()
        self.fetch_block_states = MagicMock(return_value={})
        self.delete_block_node = MagicMock()
        self.delete_note_mention_edges = MagicMock()
        self.delete_source_artifacts = MagicMock()

    def upsert_embedding(self, **_kwargs) -> None:
        return


def _make_service(fake_repo: _FakeGraphRepository) -> GraphSyncService:
    """Build a GraphSyncService wired to *fake_repo*, skipping real DB session."""
    svc = object.__new__(GraphSyncService)
    svc._session = None  # type: ignore[assignment]
    svc._repository = fake_repo
    svc._graph_name = "nn_test"
    return svc


@pytest.mark.parametrize("predicate", [
    "MENTIONED_TOGETHER", "SUBTOPIC_OF", "SIBLING_OF", "REFERENCES",
])
def test_structural_predicates_persist_with_their_own_label(predicate: str) -> None:
    repo = _FakeGraphRepository(session=None)
    svc = _make_service(repo)
    svc._upsert_relations(payload=_make_payload(predicate), now_iso="2026-05-09T00:00:00Z")
    concept_to_concept_calls = [
        c for c in repo.upsert_typed_edge.call_args_list
        if c.kwargs.get("source_label") == "Concept" and c.kwargs.get("target_label") == "Concept"
    ]
    edge_types = [c.kwargs.get("relation_type") for c in concept_to_concept_calls]
    assert predicate in edge_types, (
        f"expected an edge labeled {predicate!r} but got: {edge_types}"
    )


def test_unknown_predicate_is_skipped_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    repo = _FakeGraphRepository(session=None)
    svc = _make_service(repo)
    caplog.set_level(logging.WARNING, logger="app.services.graph_sync_service")
    svc._upsert_relations(payload=_make_payload("CAUSES"), now_iso="2026-05-09T00:00:00Z")

    # No Concept→Concept edge should have been created.
    concept_to_concept_calls = [
        c for c in repo.upsert_typed_edge.call_args_list
        if c.kwargs.get("source_label") == "Concept" and c.kwargs.get("target_label") == "Concept"
    ]
    assert not concept_to_concept_calls, (
        f"No Concept→Concept edge should be emitted for unknown predicate; got: {concept_to_concept_calls}"
    )

    # Must NOT silently fall back to RELATED_TO
    related_to_calls = [
        c for c in repo.upsert_typed_edge.call_args_list
        if c.kwargs.get("relation_type") == "RELATED_TO"
    ]
    assert not related_to_calls, "must NOT silently fall back to RELATED_TO"

    # Must emit a warning containing the predicate and note_id
    assert any(
        "CAUSES" in r.message and "note-x" in r.message
        for r in caplog.records
    ), f"Expected a warning about 'CAUSES' and 'note-x' but got: {[r.message for r in caplog.records]}"
