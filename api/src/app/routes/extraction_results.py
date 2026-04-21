"""POST /v1/extraction-results — receive browser-computed extraction results.

In edge mode the browser runs an in-browser LLM (Gemma 4 E4B) for concept
extraction. Results are posted here so the server can sync them to the AGE
graph, generate embeddings, and register concepts — without ever calling an
LLM itself.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.models.note import Note
from app.db.repositories.embedding_repository import EmbeddingRepository
from app.db.repositories.graph_repository import GraphRepository
from app.db.tenant_session import get_tenant_session
from app.nlp.concept_registry import register_concepts
from app.nlp.types import (
    ExtractedEntity,
    ExtractedKeyphrase,
    ExtractedRelation,
)
from app.services.graph_sync_service import GraphSyncPayload, GraphSyncService
from shared.contracts.python.v1.extraction import (
    SubmitExtractionResultsRequest,
    SubmitExtractionResultsResponse,
)

router = APIRouter()
_LOGGER = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    """Convert text to a lowercase slug for entity IDs."""
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "unknown"


@router.post(
    "/extraction-results",
    response_model=SubmitExtractionResultsResponse,
)
async def submit_extraction_results(
    body: SubmitExtractionResultsRequest,
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> SubmitExtractionResultsResponse:
    """Accept pre-computed extraction results from the browser and sync to graph."""
    graph_name = f"nn_{user.schema_name}"

    # 1. Validate note exists
    note = session.execute(
        select(Note).where(Note.note_id == body.note_id)
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    # 2. Reject stale results — content_hash must match current note
    if note.content_hash != body.content_hash:
        raise HTTPException(
            status_code=409,
            detail="Content hash mismatch — note has been updated since extraction",
        )

    # 3. Convert browser concepts to ExtractedEntity format
    entities: list[ExtractedEntity] = []
    for concept in body.concepts:
        entity_id = f"concept-{_slugify(concept.text)}"
        entities.append(ExtractedEntity(
            entity_id=entity_id,
            text=concept.text,
            label="concept",
            confidence=concept.confidence,
        ))

    # 4. Convert browser relations to ExtractedRelation format
    relations: list[ExtractedRelation] = []
    for rel in body.relations:
        relations.append(ExtractedRelation(
            subject_id=f"concept-{_slugify(rel.source)}",
            subject_text=rel.source,
            predicate=rel.type,
            object_id=f"concept-{_slugify(rel.target)}",
            object_text=rel.target,
            confidence=rel.confidence,
        ))

    # 5. Build GraphSyncPayload and sync
    payload = GraphSyncPayload(
        note_id=note.note_id,
        note_title=note.note_title,
        subject_id=note.subject_id,
        content_hash=note.content_hash,
        updated_at=note.updated_at,
        entities=entities,
        keyphrases=[],
        relations=relations,
        resolved_entities={},
        embedding=None,
        entity_mentions=[],
        note_summary=body.summary,
    )

    # Check if the DB is PostgreSQL before attempting graph sync
    bind = session.get_bind()
    is_postgres = bind is not None and bind.dialect.name == "postgresql"

    if is_postgres:
        GraphSyncService(
            session=session,
            graph_name=graph_name,
        ).sync_note_graph(payload)
        session.flush()

    # 6. Register concepts in concept_registry
    if entities:
        concept_items = [(e.text, e.entity_id) for e in entities]
        register_concepts(session, concept_items)
        session.flush()

    session.commit()

    _LOGGER.info(
        "Edge extraction synced: note_id=%s entities=%d relations=%d",
        body.note_id,
        len(entities),
        len(relations),
    )

    return SubmitExtractionResultsResponse(
        note_id=body.note_id,
        entity_count=len(entities),
        relation_count=len(relations),
        synced=True,
    )
