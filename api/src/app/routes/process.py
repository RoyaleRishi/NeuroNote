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
    from app.core.crypto import decrypt_api_key, InvalidToken
    from app.db.engine import bind_session_to_tenant, get_session_factory
    from app.db.tenant import validate_schema_name

    validate_schema_name(schema_name)
    factory = get_session_factory()
    with factory() as session:
        url = str(session.get_bind().url)
        if url.startswith("postgresql"):
            bind_session_to_tenant(session, schema_name)
        rows = session.execute(
            sa_text("SELECT key, value FROM user_preferences")
        ).all()

    prefs = {str(r[0]): str(r[1]) for r in rows}
    if prefs.get("llm_mode") != "cloud" or not prefs.get("llm_api_key"):
        return None

    # Decrypt the API key; if it's invalid (wrong key or plaintext), log and skip.
    api_key = prefs["llm_api_key"]
    try:
        api_key = decrypt_api_key(api_key)
    except InvalidToken:
        _LOG.warning("llm_api_key could not be decrypted (wrong key or plaintext); skipping cloud mode.")
        return None

    if not api_key:
        return None

    base = get_nlp_settings()
    return _dataclass_replace(
        base,
        llm_api_key=api_key,
        llm_base_url=prefs.get("llm_base_url", base.llm_base_url),
        llm_model=prefs.get("llm_model", base.llm_model),
    )


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
