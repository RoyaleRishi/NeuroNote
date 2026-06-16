from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import get_session_factory
from app.db.tenant import validate_schema_name
from app.db.models.block import Block
from app.db.repositories.note_repository import NoteRepository
from app.nlp.pipeline import NoteNlpPipeline
from app.nlp.types import BlockTextInput, NoteExtractionResult
from app.services.graph_sync_service import (
    GraphSyncPayload,
    GraphSyncService,
)
from shared.contracts.python.v1.process import ExtractionSummary, ProcessNoteRequest

_DEFAULT_GRAPH_NAME = "neuronote"
_LOGGER = logging.getLogger(__name__)


def _maybe_log_zero_relations_warning(result: NoteExtractionResult) -> None:
    """Emit a warning when relation extraction looks suspiciously empty.

    Heuristic: warn when the note has ≥3 concepts spread across ≥3
    distinct structural blocks (so the algorithm had something to chew
    on) yet emitted zero concept→concept relations. Catches regressions
    of the same shape as the deterministic-refactor blockUid contract
    drift.
    """
    relation_count = len(result.relations)
    entity_count = len(result.entities)
    blocks = result.distinct_blocks_with_concepts
    if relation_count == 0 and entity_count >= 3 and blocks >= 3:
        _LOGGER.warning(
            "Suspicious extraction: note_id=%s relation_count=0 entity_count=%d "
            "distinct_blocks_with_concepts=%d",
            result.note_id, entity_count, blocks,
        )


class NoteNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessedNoteSnapshot:
    note_id: str
    subject_id: str
    note_title: str
    content_text: str
    content_hash: str
    updated_at: str
    document_json: dict
    blocks: list[BlockTextInput]


class NoteProcessingService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        pipeline: NoteNlpPipeline | None = None,
        graph_name: str = _DEFAULT_GRAPH_NAME,
        schema_name: str | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._pipeline = pipeline or NoteNlpPipeline()
        self._graph_name = graph_name
        self._schema_name = schema_name

    def _open_session(self) -> Session:
        """Open a session — search_path is set by the engine's pool checkout
        event based on the contextvar set in ``process_note``."""
        return self._session_factory()

    def _load_snapshot(self, note_id: str) -> ProcessedNoteSnapshot:
        with self._open_session() as session:
            note = NoteRepository(session).get_note(note_id)
            if note is None:
                raise NoteNotFoundError(f"Note {note_id} was not found")
            blocks = session.execute(
                select(Block).where(Block.note_id == note_id).order_by(Block.block_index.asc())
            ).scalars()
            block_inputs = [
                BlockTextInput(
                    block_index=block.block_index,
                    content_text=block.content_text,
                )
                for block in blocks
            ]
            return ProcessedNoteSnapshot(
                note_id=note.note_id,
                subject_id=note.subject_id,
                note_title=note.note_title,
                content_text=note.content_text,
                content_hash=note.content_hash,
                updated_at=note.updated_at,
                document_json=note.content_json or {},
                blocks=block_inputs,
            )

    def _is_postgres(self, session: Session) -> bool:
        if session.bind is None:
            return False
        return session.bind.dialect.name == "postgresql"

    def _persist_graph_and_vector(self, *, snapshot: ProcessedNoteSnapshot) -> ExtractionSummary:
        from app.nlp.embeddings import embed_batch_for_normalisation
        from app.nlp.concept_registry import register_concepts_with_embeddings

        with self._open_session() as session:
            if not self._is_postgres(session):
                return ExtractionSummary(
                    entity_count=0,
                    relation_count=0,
                    top_entities=[],
                )

            with session.begin():
                result = self._pipeline.extract(
                    session=session,
                    embedder=embed_batch_for_normalisation,
                    note_id=snapshot.note_id,
                    title=snapshot.note_title,
                    content_text=snapshot.content_text,
                    document_json=snapshot.document_json,
                    content_hash=snapshot.content_hash,
                )

                _maybe_log_zero_relations_warning(result)

                # Persist newly-canonical concepts (with embeddings) so future
                # notes find them via NN — closing the normalisation loop.
                # Batched encode mirrors the normalisation hot path: one
                # transformer forward pass for all entities instead of N.
                entity_texts = [e.text for e in result.entities]
                entity_embeddings = embed_batch_for_normalisation(entity_texts)
                new_pairs: list[tuple[str, str, list[float]]] = [
                    (e.text, e.entity_id, emb)
                    for e, emb in zip(result.entities, entity_embeddings)
                ]
                register_concepts_with_embeddings(session, new_pairs)

                GraphSyncService(session=session, graph_name=self._graph_name).sync_note_graph(
                    GraphSyncPayload(
                        note_id=snapshot.note_id,
                        note_title=snapshot.note_title,
                        subject_id=snapshot.subject_id,
                        content_hash=snapshot.content_hash,
                        updated_at=snapshot.updated_at,
                        entities=result.entities,
                        relations=result.relations,
                        resolved_entities={},
                        embedding=result.embedding,
                    )
                )

                # Parity: a save that dropped a concept can orphan its shared
                # Entity/Concept nodes — sweep them in the same transaction.
                from app.db.repositories.note_repository import NoteRepository
                from app.services.graph_reconciliation_service import (
                    GraphReconciliationService,
                )

                live_subject_ids = NoteRepository(session).list_live_subject_ids()
                GraphReconciliationService(
                    session=session, graph_name=self._graph_name
                )._sweep_orphans(live_subject_ids=live_subject_ids)

        return ExtractionSummary(
            entity_count=len(result.entities),
            relation_count=len(result.relations),
            top_entities=[e.text for e in result.entities[:5]],
        )

    def process_note(self, payload: ProcessNoteRequest) -> ExtractionSummary:
        # Set the tenant schema contextvar so connections checked out from the
        # pool by every internal session apply the right SET search_path.
        from app.db.engine import set_tenant_schema
        if self._schema_name:
            validate_schema_name(self._schema_name)
        set_tenant_schema(self._schema_name)
        try:
            snapshot = self._load_snapshot(payload.note_id)
            return self._persist_graph_and_vector(snapshot=snapshot)
        finally:
            set_tenant_schema(None)
