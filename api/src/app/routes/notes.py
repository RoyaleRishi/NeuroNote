from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.repositories.note_repository import NoteRepository, NoteTitleConflictError
from app.db.tenant_session import get_tenant_session
from app.services.note_asset_service import reconcile_note_assets_for_note
from shared.contracts.python.v1.note import (
    GetNoteResponse,
    ListNotesResponse,
    NoteSummary,
    SaveNoteRequest,
    SaveNoteResponse,
)

router = APIRouter()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.put("/notes/{note_id}", response_model=SaveNoteResponse)
def put_note(
    note_id: str,
    payload: SaveNoteRequest,
    session: Session = Depends(get_tenant_session),
) -> SaveNoteResponse:
    if note_id != payload.note_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path note_id must match payload note_id",
        )

    repository = NoteRepository(session)
    try:
        with session.begin():
            record = repository.upsert_note(
                note_id=payload.note_id,
                note_title=payload.note_title,
                subject_id=payload.subject_id,
                tags=payload.tags,
                is_pinned=payload.is_pinned,
                is_archived=payload.is_archived,
                content_json=payload.content_json,
                content_text=payload.content_text,
                updated_at=payload.updated_at,
            )
            reconcile_note_assets_for_note(
                note_id=payload.note_id,
                content_json=payload.content_json,
                session=session,
            )
    except NoteTitleConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "note_title_conflict",
                "message": str(exc),
                "title": exc.normalized_title,
            },
        ) from exc
    return SaveNoteResponse(
        note_id=record.note_id,
        saved_at=_utc_now_iso(),
        version=record.version,
    )


@router.get("/notes/{note_id}", response_model=GetNoteResponse)
def fetch_note(
    note_id: str,
    session: Session = Depends(get_tenant_session),
) -> GetNoteResponse:
    record = NoteRepository(session).get_note(note_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note {note_id} was not found",
        )
    return GetNoteResponse(
        note_id=record.note_id,
        note_title=record.note_title,
        subject_id=record.subject_id,
        tags=record.tags,
        is_pinned=record.is_pinned,
        is_archived=record.is_archived,
        content_json=record.content_json,
        content_text=record.content_text,
        updated_at=record.updated_at,
        version=record.version,
    )


@router.get("/notes", response_model=ListNotesResponse)
def list_notes(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    subject_id: str | None = Query(default=None, min_length=1),
    tag: str | None = Query(default=None, min_length=1),
    is_archived: bool | None = Query(default=False),
    is_pinned: bool | None = Query(default=None),
    session: Session = Depends(get_tenant_session),
) -> ListNotesResponse:
    items, total = NoteRepository(session).list_notes(
        limit=limit,
        offset=offset,
        search=search,
        subject_id=subject_id,
        tag=tag,
        is_archived=is_archived,
        is_pinned=is_pinned,
    )
    return ListNotesResponse(
        items=[
            NoteSummary(
                note_id=item.note_id,
                note_title=item.note_title,
                subject_id=item.subject_id,
                tags=item.tags,
                is_pinned=item.is_pinned,
                is_archived=item.is_archived,
                content_text=item.content_text,
                updated_at=item.updated_at,
                version=item.version,
            )
            for item in items
        ],
        total=total,
    )


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: str,
    session: Session = Depends(get_tenant_session),
) -> Response:
    with session.begin():
        deleted = NoteRepository(session).delete_note(note_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note {note_id} was not found",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
