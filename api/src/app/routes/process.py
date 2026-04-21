import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.job_store import (
    create_or_get_job,
    get_job,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
)
from app.core.auth import UserContext, get_current_user
from app.db.repositories.note_repository import NoteRepository
from app.db.tenant_session import get_tenant_session
from app.core.rate_limiter import limiter
from app.services.note_processing_service import NoteNotFoundError, NoteProcessingService
from shared.contracts.python.v1.process import (
    ProcessNoteRequest,
    ProcessNoteResponse,
    ProcessStatusResponse,
)

router = APIRouter()
_LOG = logging.getLogger(__name__)


def _run_processing_job(
    *, job_id: str, payload: ProcessNoteRequest, schema_name: str, graph_name: str
) -> None:
    mark_job_running(job_id)
    try:
        summary = NoteProcessingService(
            schema_name=schema_name,
            graph_name=graph_name,
        ).process_note(payload)
    except NoteNotFoundError as exc:
        mark_job_failed(job_id, error=str(exc))
        return
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        _LOG.exception("Processing job %s failed: %s", job_id, exc)
        mark_job_failed(job_id, error=str(exc))
        return

    mark_job_completed(job_id, extraction_summary=summary.model_dump() if summary else None)


@router.post(
    "/process-note",
    response_model=ProcessNoteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("30/minute")
def process_note(
    request: Request,
    payload: ProcessNoteRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> ProcessNoteResponse:
    graph_name = f"nn_{user.schema_name}"

    note = NoteRepository(session).get_note(payload.note_id)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note {payload.note_id} was not found",
        )

    record, created = create_or_get_job(
        note_id=payload.note_id,
        content_hash=note.content_hash,
    )
    if created:
        background_tasks.add_task(
            _run_processing_job,
            job_id=record.job_id,
            payload=payload,
            schema_name=user.schema_name,
            graph_name=graph_name,
        )

    return ProcessNoteResponse(job_id=record.job_id, status="queued")


@router.get("/process-status/{job_id}", response_model=ProcessStatusResponse)
def process_status(job_id: str) -> ProcessStatusResponse:
    record = get_job(job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} was not found",
        )
    return record
