"""File import endpoint — accepts markdown or plain text content and creates a note."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.repositories.note_repository import NoteRepository
from app.db.tenant_session import get_tenant_session
from app.import_.markdown_parser import (
    extract_title_from_markdown,
    parse_markdown_to_tiptap,
    parse_plaintext_to_tiptap,
)
from shared.contracts.python.v1.import_ import ImportNoteRequest, ImportNoteResponse
from shared.contracts.python.v1.process import ProcessNoteRequest

router = APIRouter()


def _make_note_id() -> str:
    import uuid
    return f"note-{uuid.uuid4().hex[:12]}"


def _extract_plain_text(content_json: dict) -> str:  # type: ignore[type-arg]
    """Extract plain text from TipTap JSON for search indexing."""
    parts: list[str] = []
    for node in content_json.get("content", []):
        for child in node.get("content", []):
            if child.get("type") == "text":
                parts.append(child.get("text", ""))
    return " ".join(parts).strip() or " "


@router.post(
    "/notes/import",
    response_model=ImportNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_note(
    payload: ImportNoteRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_tenant_session),
) -> ImportNoteResponse:
    filename = payload.filename.strip()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "md":
        content_json = parse_markdown_to_tiptap(payload.content)
        title = extract_title_from_markdown(payload.content)
    elif ext in ("txt", ""):
        content_json = parse_plaintext_to_tiptap(payload.content)
        first_line = payload.content.strip().split("\n")[0].strip()
        title = first_line[:120] if first_line else "Untitled"
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type: .{ext}. Only .md and .txt are supported.",
        )

    note_id = _make_note_id()
    now_iso = datetime.now(timezone.utc).isoformat()
    plain_text = _extract_plain_text(content_json)

    repo = NoteRepository(session)
    saved = repo.upsert_note(
        note_id=note_id,
        note_title=title,
        subject_id=payload.subject_id,
        tags=[],
        is_pinned=False,
        is_archived=False,
        content_json=content_json,
        content_text=plain_text,
        updated_at=now_iso,
    )

    # Queue NLP processing in background
    from app.core.job_store import create_or_get_job, mark_job_running
    from app.services.note_processing_service import NoteProcessingService

    record, created = create_or_get_job(
        note_id=note_id,
        content_hash=saved.content_hash,
    )
    if created:
        process_payload = ProcessNoteRequest(
            note_id=note_id,
            content_text=plain_text,
            content_hash=saved.content_hash,
            updated_at=now_iso,
        )

        def _run_processing(job_id: str, p: ProcessNoteRequest) -> None:
            from app.core.job_store import mark_job_completed, mark_job_failed
            mark_job_running(job_id)
            try:
                summary = NoteProcessingService().process_note(p)
                mark_job_completed(job_id, extraction_summary=summary.model_dump() if summary else None)
            except Exception as exc:
                mark_job_failed(job_id, error=str(exc))

        background_tasks.add_task(_run_processing, record.job_id, process_payload)

    return ImportNoteResponse(
        note_id=note_id,
        note_title=title,
        saved_at=now_iso,
    )
