from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.repositories.note_repository import NoteRepository
from app.db.tenant_session import get_tenant_session
from shared.contracts.python.v1.backlink import BacklinkItem, BacklinksResponse

router = APIRouter()


@router.get("/notes/{note_id}/backlinks", response_model=BacklinksResponse)
def list_backlinks_for_note(
    note_id: str,
    session: Session = Depends(get_tenant_session),
) -> BacklinksResponse:
    repository = NoteRepository(session)
    if repository.get_note(note_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note {note_id} was not found",
        )
    items = repository.list_backlinks_for_note(note_id)
    return BacklinksResponse(
        note_id=note_id,
        items=[
            BacklinkItem(
                source_note_id=item.source_note_id,
                source_note_title=item.source_note_title,
                matched_title=item.matched_title,
                snippet=item.snippet,
                updated_at=item.updated_at,
            )
            for item in items
        ],
    )
