from __future__ import annotations

from app.db.engine import get_session_factory
from app.db.repositories.note_repository import NoteRepository
from app.nlp.types import ExtractedEntity
from app.nlp.types import ExtractedEntityMention
from app.nlp.types import ExtractedRelation
from app.services import graph_sync_service as graph_sync_module
from app.services.graph_sync_service import GraphSyncPayload, GraphSyncService


def test_graph_sync_collapses_relation_edges_to_related_to(
    configured_db: None,
    monkeypatch,
) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id="sync-note-1",
                note_title="Sync title",
                content_json={
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "A B"}]},
                    ],
                },
                content_text="A B",
                updated_at="2026-03-11T12:10:00Z",
            )

    captured_relation_types: list[str] = []

    class _FakeGraphRepository:
        def __init__(self, _session) -> None:
            return

        def fetch_block_states(self, **_kwargs) -> dict:
            return {}

        def delete_block_node(self, **_kwargs) -> None:
            return

        def delete_note_mention_edges(self, **_kwargs) -> None:
            return

        def delete_source_artifacts(self, **_kwargs) -> None:
            return

        def upsert_node(self, **_kwargs) -> None:
            return

        def upsert_nodes_batch(self, **_kwargs) -> None:
            return

        def upsert_typed_edge(self, **kwargs) -> None:
            if kwargs["source_label"] == "Concept" and kwargs["target_label"] == "Concept":
                captured_relation_types.append(str(kwargs["relation_type"]))

        def upsert_embedding(self, **_kwargs) -> None:
            return

    monkeypatch.setattr(graph_sync_module, "GraphRepository", _FakeGraphRepository)

    with session_factory() as session:
        with session.begin():
            GraphSyncService(session=session).sync_note_graph(
                GraphSyncPayload(
                    note_id="sync-note-1",
                    note_title="Sync title",
                    subject_id="inbox",
                    content_hash="hash-sync-1",
                    updated_at="2026-03-11T12:10:00Z",
                    entities=[],
                    keyphrases=[],
                    relations=[
                        ExtractedRelation(
                            subject_id="concept-a",
                            subject_text="A",
                            predicate="supports",
                            object_id="concept-b",
                            object_text="B",
                            confidence=0.9,
                        )
                    ],
                    resolved_entities={},
                    embedding=None,
                    entity_mentions=[],
                )
            )

    assert captured_relation_types == ["RELATED_TO"]


def test_graph_sync_uses_entity_mentions_evidence_for_block_edges(
    configured_db: None,
    monkeypatch,
) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id="sync-note-mentions-1",
                note_title="Sync title",
                content_json={
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "ML appears in block one"}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "No entity here"}]},
                    ],
                },
                content_text="ML appears in block one\nNo entity here",
                updated_at="2026-03-14T12:10:00Z",
            )

    captured_edges: list[tuple[str, str]] = []

    class _FakeGraphRepository:
        def __init__(self, _session) -> None:
            return

        def fetch_block_states(self, **_kwargs) -> dict:
            return {}

        def delete_block_node(self, **_kwargs) -> None:
            return

        def delete_note_mention_edges(self, **_kwargs) -> None:
            return

        def delete_source_artifacts(self, **_kwargs) -> None:
            return

        def upsert_node(self, **_kwargs) -> None:
            return

        def upsert_nodes_batch(self, **_kwargs) -> None:
            return

        def upsert_typed_edge(self, **kwargs) -> None:
            if kwargs["source_label"] == "Block" and kwargs["target_label"] == "Entity":
                captured_edges.append((str(kwargs["source_id"]), str(kwargs["target_id"])))

        def upsert_embedding(self, **_kwargs) -> None:
            return

    monkeypatch.setattr(graph_sync_module, "GraphRepository", _FakeGraphRepository)

    with session_factory() as session:
        with session.begin():
            GraphSyncService(session=session).sync_note_graph(
                GraphSyncPayload(
                    note_id="sync-note-mentions-1",
                    note_title="Sync title",
                    subject_id="inbox",
                    content_hash="hash-sync-mentions",
                    updated_at="2026-03-14T12:10:00Z",
                    entities=[
                        ExtractedEntity(
                            entity_id="entity-ml",
                            text="ML",
                            label="acronym",
                            confidence=0.75,
                        )
                    ],
                    keyphrases=[],
                    relations=[],
                    resolved_entities={},
                    embedding=None,
                    entity_mentions=[
                        ExtractedEntityMention(
                            entity_id="entity-ml",
                            block_index=0,
                            mention_text="ML",
                            start_offset=0,
                            end_offset=2,
                            confidence=0.93,
                        )
                    ],
                )
            )

    assert len(captured_edges) == 1
    source_id, target_id = captured_edges[0]
    assert source_id.startswith("sync-note-mentions-1:block:")
    assert target_id == "entity-ml"


def test_graph_sync_emits_refers_to_edges_from_block_tokens(
    configured_db: None,
    monkeypatch,
) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id="sync-note-ref-target",
                note_title="Target",
                content_json={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "attrs": {"blockUid": "target-block-uid"},
                            "content": [{"type": "text", "text": "Target block"}],
                        }
                    ],
                },
                content_text="Target block",
                updated_at="2026-03-14T13:59:00Z",
            )
            NoteRepository(session).upsert_note(
                note_id="sync-note-ref-source",
                note_title="Source",
                content_json={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Reference ((target-block-uid)) here"}],
                        }
                    ],
                },
                content_text="Reference ((target-block-uid)) here",
                updated_at="2026-03-14T14:00:00Z",
            )

    captured_ref_edges: list[tuple[str, str]] = []

    class _FakeGraphRepository:
        def __init__(self, _session) -> None:
            return

        def fetch_block_states(self, **_kwargs) -> dict:
            return {}

        def delete_block_node(self, **_kwargs) -> None:
            return

        def delete_note_mention_edges(self, **_kwargs) -> None:
            return

        def delete_source_artifacts(self, **_kwargs) -> None:
            return

        def upsert_node(self, **_kwargs) -> None:
            return

        def upsert_nodes_batch(self, **_kwargs) -> None:
            return

        def upsert_typed_edge(self, **kwargs) -> None:
            if kwargs["relation_type"] == "REFERS_TO":
                captured_ref_edges.append((str(kwargs["source_id"]), str(kwargs["target_id"])))

        def upsert_embedding(self, **_kwargs) -> None:
            return

    monkeypatch.setattr(graph_sync_module, "GraphRepository", _FakeGraphRepository)

    with session_factory() as session:
        with session.begin():
            GraphSyncService(session=session).sync_note_graph(
                GraphSyncPayload(
                    note_id="sync-note-ref-source",
                    note_title="Source",
                    subject_id="inbox",
                    content_hash="hash-ref-source",
                    updated_at="2026-03-14T14:00:00Z",
                    entities=[],
                    keyphrases=[],
                    relations=[],
                    resolved_entities={},
                    embedding=None,
                    entity_mentions=[],
                )
            )

    assert captured_ref_edges


def test_graph_sync_emits_refers_to_edges_from_reference_link_marks(
    configured_db: None,
    monkeypatch,
) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        with session.begin():
            NoteRepository(session).upsert_note(
                note_id="sync-note-ref-mark-target",
                note_title="Target",
                content_json={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "attrs": {"blockUid": "target-mark-block-uid"},
                            "content": [{"type": "text", "text": "Target block"}],
                        }
                    ],
                },
                content_text="Target block",
                updated_at="2026-03-14T14:05:00Z",
            )
            NoteRepository(session).upsert_note(
                note_id="sync-note-ref-mark-source",
                note_title="Source",
                content_json={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Readable linked block",
                                    "marks": [
                                        {
                                            "type": "referenceLink",
                                            "attrs": {
                                                "href": "/notes/sync-note-ref-mark-target#block=target-mark-block-uid",
                                                "dataRefType": "block",
                                                "dataBlockUid": "target-mark-block-uid",
                                                "dataNoteId": "sync-note-ref-mark-target",
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                content_text="Readable linked block",
                updated_at="2026-03-14T14:06:00Z",
            )

    captured_ref_edges: list[tuple[str, str]] = []

    class _FakeGraphRepository:
        def __init__(self, _session) -> None:
            return

        def fetch_block_states(self, **_kwargs) -> dict:
            return {}

        def delete_block_node(self, **_kwargs) -> None:
            return

        def delete_note_mention_edges(self, **_kwargs) -> None:
            return

        def delete_source_artifacts(self, **_kwargs) -> None:
            return

        def upsert_node(self, **_kwargs) -> None:
            return

        def upsert_nodes_batch(self, **_kwargs) -> None:
            return

        def upsert_typed_edge(self, **kwargs) -> None:
            if kwargs["relation_type"] == "REFERS_TO":
                captured_ref_edges.append((str(kwargs["source_id"]), str(kwargs["target_id"])))

        def upsert_embedding(self, **_kwargs) -> None:
            return

    monkeypatch.setattr(graph_sync_module, "GraphRepository", _FakeGraphRepository)

    with session_factory() as session:
        with session.begin():
            GraphSyncService(session=session).sync_note_graph(
                GraphSyncPayload(
                    note_id="sync-note-ref-mark-source",
                    note_title="Source",
                    subject_id="inbox",
                    content_hash="hash-ref-mark-source",
                    updated_at="2026-03-14T14:06:00Z",
                    entities=[],
                    keyphrases=[],
                    relations=[],
                    resolved_entities={},
                    embedding=None,
                    entity_mentions=[],
                )
            )

    assert captured_ref_edges
