from __future__ import annotations

import hashlib

import pytest

from app.db.engine import get_session_factory
from app.db.repositories.note_repository import NoteRepository
from app.nlp.types import ExtractedRelation
from app.nlp.types import NoteExtractionResult
from app.services import note_processing_service as note_processing_module
from app.services.note_processing_service import NoteNotFoundError, NoteProcessingService
from shared.contracts.python.v1.process import ProcessNoteRequest


class _FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, dict]] = []

    def extract(
        self,
        *,
        session,
        embedder,
        note_id: str,
        title: str,
        content_text: str,
        document_json: dict,
        content_hash: str,
    ) -> NoteExtractionResult:
        self.calls.append((note_id, title, content_text, content_hash, document_json))
        return NoteExtractionResult(
            note_id=note_id,
            content_hash=content_hash,
            entities=[],
            relations=[],
            embedding=[0.0] * 384,
        )


def test_process_note_raises_when_note_is_missing(configured_db: None) -> None:
    pipeline = _FakePipeline()
    service = NoteProcessingService(
        session_factory=get_session_factory(),
        pipeline=pipeline,
    )

    with pytest.raises(NoteNotFoundError):
        service.process_note(
            ProcessNoteRequest(
                note_id="missing-note",
                content_text="text",
                content_hash="hash",
                updated_at="2026-03-07T12:00:00Z",
            )
        )


def _stub_postgres_path(monkeypatch: pytest.MonkeyPatch, service: NoteProcessingService) -> None:
    """Force the postgres branch + stub graph/registry side-effects for sqlite tests."""

    class _FakeGraphSyncService:
        def __init__(self, *, session, graph_name: str) -> None:
            pass

        def sync_note_graph(self, _payload) -> None:
            return

    monkeypatch.setattr(note_processing_module, "GraphSyncService", _FakeGraphSyncService)
    monkeypatch.setattr(service, "_is_postgres", lambda _session: True)
    from app.nlp import concept_registry as _cr
    monkeypatch.setattr(_cr, "register_concepts_with_embeddings", lambda *_a, **_k: None)


def test_process_note_uses_latest_persisted_note_snapshot(
    configured_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_id = "note-process-1"
    note_title = "Persisted title"
    persisted_text = "Machine Learning supports Entity Resolution"
    combined_text = f"{note_title}\n\n{persisted_text}"
    persisted_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()

    session_factory = get_session_factory()
    with session_factory() as session:
        repository = NoteRepository(session)
        with session.begin():
                repository.upsert_note(
                    note_id=note_id,
                    note_title=note_title,
                    content_json={"type": "doc", "content": []},
                    content_text=persisted_text,
                    updated_at="2026-03-07T12:01:00Z",
                )

    pipeline = _FakePipeline()
    service = NoteProcessingService(session_factory=session_factory, pipeline=pipeline)
    _stub_postgres_path(monkeypatch, service)
    service.process_note(
        ProcessNoteRequest(
            note_id=note_id,
            content_text="stale payload",
            content_hash="stale-hash",
            updated_at="2026-03-07T12:02:00Z",
        )
    )

    assert pipeline.calls[0][0:4] == (note_id, note_title, persisted_text, persisted_hash)


def test_process_note_includes_note_title_in_pipeline_input(
    configured_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_id = "note-process-title-1"
    persisted_title = "Machine Learning"
    persisted_text = "Improves entity resolution across domains"
    combined_text = f"{persisted_title}\n\n{persisted_text}"
    persisted_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()

    session_factory = get_session_factory()
    with session_factory() as session:
        repository = NoteRepository(session)
        with session.begin():
            repository.upsert_note(
                note_id=note_id,
                note_title=persisted_title,
                content_json={"type": "doc", "content": []},
                content_text=persisted_text,
                updated_at="2026-03-11T12:01:00Z",
            )

    pipeline = _FakePipeline()
    service = NoteProcessingService(session_factory=session_factory, pipeline=pipeline)
    _stub_postgres_path(monkeypatch, service)
    service.process_note(
        ProcessNoteRequest(
            note_id=note_id,
            content_text="stale payload",
            content_hash="stale-hash",
            updated_at="2026-03-11T12:02:00Z",
        )
    )

    assert pipeline.calls[0][0:4] == (note_id, persisted_title, persisted_text, persisted_hash)


def test_process_note_does_not_raise_transaction_error_when_postgres_path_is_used(
    configured_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note_id = "note-process-transaction-path"
    persisted_text = "Knowledge Graphs connect machine learning concepts"

    session_factory = get_session_factory()
    with session_factory() as session:
        repository = NoteRepository(session)
        with session.begin():
            repository.upsert_note(
                note_id=note_id,
                note_title="Transaction title",
                content_json={"type": "doc", "content": []},
                content_text=persisted_text,
                updated_at="2026-03-10T12:01:00Z",
            )

    class _FakeGraphSyncService:
        def __init__(self, *, session, graph_name: str) -> None:
            self._session = session
            self._graph_name = graph_name

        def sync_note_graph(self, _payload) -> None:
            return

    pipeline = _FakePipeline()
    service = NoteProcessingService(session_factory=session_factory, pipeline=pipeline)

    monkeypatch.setattr(note_processing_module, "GraphSyncService", _FakeGraphSyncService)
    monkeypatch.setattr(service, "_is_postgres", lambda _session: True)

    service.process_note(
        ProcessNoteRequest(
            note_id=note_id,
            content_text="stale payload",
            content_hash="stale-hash",
            updated_at="2026-03-10T12:02:00Z",
        )
    )


def test_process_note_collapses_relation_type_to_related_to(
    configured_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note_id = "note-process-related-to"
    persisted_text = "ML supports graph reasoning."

    session_factory = get_session_factory()
    with session_factory() as session:
        repository = NoteRepository(session)
        with session.begin():
            repository.upsert_note(
                note_id=note_id,
                note_title="Graph title",
                content_json={"type": "doc", "content": []},
                content_text=persisted_text,
                updated_at="2026-03-11T12:03:00Z",
            )

    class _RelationPipeline:
        def extract(
            self,
            *,
            session,
            embedder,
            note_id: str,
            title: str,
            content_text: str,
            document_json: dict,
            content_hash: str,
        ) -> NoteExtractionResult:
            return NoteExtractionResult(
                note_id=note_id,
                content_hash=content_hash,
                entities=[],
                relations=[
                    ExtractedRelation(
                        subject_id="concept-a",
                        subject_text="Machine Learning",
                        predicate="improves",
                        object_id="concept-b",
                        object_text="Graph Reasoning",
                        confidence=0.88,
                    )
                ],
                embedding=None,
            )

    captured_predicates: list[str] = []

    class _FakeGraphSyncService:
        def __init__(self, *, session, graph_name: str) -> None:
            self._session = session
            self._graph_name = graph_name

        def sync_note_graph(self, payload) -> None:
            captured_predicates.extend([relation.predicate for relation in payload.relations])

    service = NoteProcessingService(
        session_factory=session_factory,
        pipeline=_RelationPipeline(),
    )
    monkeypatch.setattr(note_processing_module, "GraphSyncService", _FakeGraphSyncService)
    monkeypatch.setattr(service, "_is_postgres", lambda _session: True)

    service.process_note(
        ProcessNoteRequest(
            note_id=note_id,
            content_text="stale payload",
            content_hash="stale-hash",
            updated_at="2026-03-11T12:04:00Z",
        )
    )

    assert captured_predicates == ["improves"]
