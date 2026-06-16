from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.core.backfill_store import get_backfill_status
from app.core.rate_limiter import limiter
from app.db.repositories.note_repository import NoteRepository
from app.db.tenant_session import get_tenant_session
from app.services.graph_reconciliation_service import GraphReconciliationService
from app.services.startup_backfill_service import StartupBackfillService
from shared.contracts.python.v1.backfill import BackfillStatusResponse
from shared.contracts.python.v1.parity import GraphParityReport

router = APIRouter()

_REPROCESS_EXECUTOR = ThreadPoolExecutor(max_workers=1)


@router.get("/backfill-status", response_model=BackfillStatusResponse)
def backfill_status() -> BackfillStatusResponse:
    snapshot = get_backfill_status()
    return BackfillStatusResponse(
        total_notes=snapshot.total_notes,
        processed_notes=snapshot.processed_notes,
        failed_notes=snapshot.failed_notes,
        in_progress=snapshot.in_progress,
    )


@router.post("/reprocess-all", response_model=BackfillStatusResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/hour")
def reprocess_all(
    request: Request,
    force: bool = Query(False, description="Skip stale check and clear extraction caches — re-extracts every note from scratch."),
) -> BackfillStatusResponse:
    """Trigger a full re-processing of every note with the current NLP settings.

    Returns 409 if a reprocess is already running.
    Poll GET /v1/backfill-status to track progress.
    """
    snapshot = get_backfill_status()
    if snapshot.in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A reprocess is already in progress.",
        )

    service = StartupBackfillService()
    _REPROCESS_EXECUTOR.submit(service.run_note_reprocessing_backfill, force=force)

    return BackfillStatusResponse(
        total_notes=0,
        processed_notes=0,
        failed_notes=0,
        in_progress=True,
    )


@router.post("/graph/reconcile", response_model=GraphParityReport)
@limiter.limit("6/hour")
def reconcile_graph(
    request: Request,
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> GraphParityReport:
    """Reverse-prune AGE state with no live SQL source for the caller's tenant.

    Operates only on the caller's own schema/graph. Idempotent.
    """
    graph_name = f"nn_{user.schema_name}"
    repo = NoteRepository(session)
    with session.begin_nested():
        report = GraphReconciliationService(session=session, graph_name=graph_name).reconcile(
            live_note_ids=repo.list_note_ids(),
            live_subject_ids=repo.list_live_subject_ids(),
        )
    session.commit()
    return report
