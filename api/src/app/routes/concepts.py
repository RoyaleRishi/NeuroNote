from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.models.note import Note
from app.db.tenant_session import get_tenant_session
from app.nlp.concept_registry import get_known_concepts
from app.nlp.config import resolve_user_llm_settings
from app.services.concept_insight_service import ConceptInsightService
from shared.contracts.python.v1.graph import (
    ConceptInsightResponse,
    InsightContextNote,
    InsightContextResponse,
    KnownConceptsResponse,
)

router = APIRouter()
_LOG = logging.getLogger(__name__)


@router.get("/concepts/insight", response_model=ConceptInsightResponse)
async def get_concept_insight(
    request: Request,
    label: str = Query(..., min_length=1, max_length=200),
    limit_notes: int = Query(default=10, ge=1, le=20),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> ConceptInsightResponse:
    """Generate an AI insight for a concept, grounded in the user's notes."""
    graph_name = f"nn_{user.schema_name}"
    user_settings = resolve_user_llm_settings(session)
    svc = ConceptInsightService(session, settings=user_settings, graph_name=graph_name)
    return await svc.get_insight(label, limit_notes=limit_notes)


# ── Edge-mode endpoints ─────────────────────────────────────────────────────

_MAX_EXCERPT_CHARS = 600
_SNIPPET_BEFORE = 60
_SNIPPET_AFTER = 90


def _make_excerpt(note: Note, label: str) -> str:
    """Build a context excerpt from a note, centering on the concept mention."""
    raw_text: str = note.content_text or ""
    lower_text = raw_text.lower()
    pos = lower_text.find(label.lower())
    if pos >= 0:
        start = max(0, pos - _SNIPPET_BEFORE)
        end = min(len(raw_text), pos + len(label) + _SNIPPET_AFTER)
        return ("…" if start > 0 else "") + raw_text[start:end].strip() + "…"
    return raw_text[:_MAX_EXCERPT_CHARS].strip() + ("…" if len(raw_text) > _MAX_EXCERPT_CHARS else "")


@router.get("/concepts/insight-context", response_model=InsightContextResponse)
async def get_insight_context(
    label: str = Query(..., min_length=1, max_length=200),
    limit_notes: int = Query(default=10, ge=1, le=20),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> InsightContextResponse:
    """Return note context for browser-side insight generation.

    The server performs DB/graph queries to find relevant notes, returns
    excerpts, and the browser generates insight text locally with its LLM.
    """
    like = f"%{label.lower()}%"
    notes = (
        session.execute(
            select(Note)
            .where(
                or_(
                    func.lower(Note.note_title).like(like),
                    func.lower(Note.content_text).like(like),
                )
            )
            .order_by(Note.updated_at.desc())
            .limit(limit_notes)
        )
        .scalars()
        .all()
    )

    context_notes = [
        InsightContextNote(
            note_id=n.note_id,
            title=n.note_title,
            excerpt=_make_excerpt(n, label),
        )
        for n in notes
    ]

    return InsightContextResponse(
        concept_label=label,
        notes=context_notes,
        total_notes=len(context_notes),
    )


@router.get("/concepts/known", response_model=KnownConceptsResponse)
async def get_known_concepts_endpoint(
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> KnownConceptsResponse:
    """Return all registered concepts for the user's knowledge base.

    Used by edge-mode browsers to seed the extraction prompt with
    previously extracted concepts for normalisation consistency.
    """
    concepts = get_known_concepts(session)
    return KnownConceptsResponse(concepts=concepts)
