import logging

from dataclasses import replace as _dataclass_replace

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import text as sa_text
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
from app.nlp.config import NlpSettings, get_nlp_settings
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
    """Load user's LLM preferences from the tenant schema.

    Returns an overridden NlpSettings for cloud mode with an API key,
    or None for edge mode / missing key (fall back to server defaults).
    """
    from app.db.engine import get_session_factory, set_tenant_schema
    from app.db.tenant import validate_schema_name

    validate_schema_name(schema_name)
    factory = get_session_factory()
    set_tenant_schema(schema_name)
    try:
        with factory() as session:
            rows = session.execute(
                sa_text("SELECT key, value FROM user_preferences")
            ).all()
    finally:
        set_tenant_schema(None)

    prefs = {str(r[0]): str(r[1]) for r in rows}
    if prefs.get("llm_mode") != "cloud" or not prefs.get("llm_api_key"):
        return None

    base = get_nlp_settings()
    return _dataclass_replace(
        base,
        extraction_profile="llm-enhanced",
        llm_api_key=prefs["llm_api_key"],
        llm_base_url=prefs.get("llm_base_url", base.llm_base_url),
        llm_model=prefs.get("llm_model", base.llm_model),
    )


def _run_processing_job(
    *, job_id: str, payload: ProcessNoteRequest, schema_name: str, graph_name: str
) -> None:
    # Pin the tenant schema for the entire background task so every session
    # opened by job_store, _load_user_llm_config, and NoteProcessingService
    # picks up the right search_path on connection checkout.
    from app.db.engine import set_tenant_schema

    set_tenant_schema(schema_name)
    try:
        mark_job_running(job_id)
        try:
            user_settings = _load_user_llm_config(schema_name)
            pipeline = NoteNlpPipeline(settings=user_settings) if user_settings else None
            summary = NoteProcessingService(
                schema_name=schema_name,
                graph_name=graph_name,
                pipeline=pipeline,
            ).process_note(payload)
        except NoteNotFoundError as exc:
            mark_job_failed(job_id, error=str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            _LOG.exception("Processing job %s failed: %s", job_id, exc)
            mark_job_failed(job_id, error=str(exc))
            return

        mark_job_completed(
            job_id,
            extraction_summary=summary.model_dump() if summary else None,
        )
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
