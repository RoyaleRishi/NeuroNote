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
from app.nlp.config import NlpSettings, resolve_user_llm_settings
from app.nlp.pipeline import NoteNlpPipeline
from app.services.note_processing_service import NoteNotFoundError, NoteProcessingService
from shared.contracts.python.v1.process import (
    ProcessNoteRequest,
    ProcessNoteResponse,
    ProcessStatusResponse,
)

router = APIRouter()
_LOG = logging.getLogger(__name__)


def _load_user_llm_config(schema_name: str) -> NlpSettings | None:
    """Background-thread wrapper around :func:`resolve_user_llm_settings`.

    Mints a tenant-bound session for ``schema_name`` (the HTTP layer's
    ``get_tenant_session`` dependency is unavailable here) and delegates the
    actual preference read / decrypt / settings build to the shared resolver.
    """
    from app.db.engine import bind_session_to_tenant, get_session_factory
    from app.db.tenant import validate_schema_name

    validate_schema_name(schema_name)
    factory = get_session_factory()
    with factory() as session:
        url = str(session.get_bind().url)  # type: ignore[union-attr]
        if url.startswith("postgresql"):
            bind_session_to_tenant(session, schema_name)
        return resolve_user_llm_settings(session)


def _run_processing_job(
    *, job_id: str, payload: ProcessNoteRequest, schema_name: str, graph_name: str
) -> None:
    # Two layers of tenant binding here:
    # 1. ContextVar (`set_tenant_schema`) — keeps `NoteProcessingService`
    #    working: it opens its own ad-hoc sessions and relies on the
    #    pool's before_cursor_execute fallback.
    # 2. Explicit per-session bind for every job_store call below — this
    #    is the authoritative path; it does not depend on thread-local
    #    state and is what guarantees `processing_jobs` writes land in
    #    the correct tenant schema.
    from app.db.engine import (
        bind_session_to_tenant,
        get_session_factory,
        set_tenant_schema,
    )

    set_tenant_schema(schema_name)
    try:
        factory = get_session_factory()
        with factory() as job_session:
            bind_session_to_tenant(job_session, schema_name)
            mark_job_running(job_session, job_id)

        try:
            user_settings = _load_user_llm_config(schema_name)
            pipeline = NoteNlpPipeline(settings=user_settings) if user_settings else None
            summary = NoteProcessingService(
                schema_name=schema_name,
                graph_name=graph_name,
                pipeline=pipeline,
            ).process_note(payload)
        except NoteNotFoundError as exc:
            with factory() as job_session:
                bind_session_to_tenant(job_session, schema_name)
                mark_job_failed(job_session, job_id, error=str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            _LOG.exception("Processing job %s failed: %s", job_id, exc)
            with factory() as job_session:
                bind_session_to_tenant(job_session, schema_name)
                mark_job_failed(job_session, job_id, error=str(exc))
            return

        summary_dict: dict[str, object] = summary.model_dump() if summary else {}
        with factory() as job_session:
            bind_session_to_tenant(job_session, schema_name)
            mark_job_completed(job_session, job_id, extraction_summary=summary_dict)
    finally:
        set_tenant_schema(None)


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
        session,
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
def process_status(
    job_id: str,
    session: Session = Depends(get_tenant_session),
) -> ProcessStatusResponse:
    record = get_job(session, job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} was not found",
        )
    return record
