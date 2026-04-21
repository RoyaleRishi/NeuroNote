from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.tenant_session import get_tenant_session
from app.nlp.semantic_linker import SemanticLinkerService
from shared.contracts.python.v1.connections import NoteConnectionsResponse

router = APIRouter()


@router.get("/notes/{note_id}/connections", response_model=NoteConnectionsResponse)
def get_note_connections(
    note_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    min_strength: float = Query(default=0.1, ge=0.0, le=1.0),
    session: Session = Depends(get_tenant_session),
) -> NoteConnectionsResponse:
    """Return notes semantically connected to this one via embedding similarity."""
    try:
        return SemanticLinkerService(session).get_connections(
            note_id,
            limit=limit,
            min_strength=min_strength,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute connections",
        )
