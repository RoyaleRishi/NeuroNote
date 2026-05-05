from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.backfill_store import get_backfill_status
from app.core.rate_limiter import limiter
from app.services.startup_backfill_service import StartupBackfillService
from shared.contracts.python.v1.backfill import BackfillStatusResponse

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
