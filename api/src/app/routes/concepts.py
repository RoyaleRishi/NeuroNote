from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.tenant_session import get_tenant_session
from app.services.concept_insight_service import ConceptInsightService
from shared.contracts.python.v1.graph import ConceptInsightResponse

router = APIRouter()


@router.get("/concepts/insight", response_model=ConceptInsightResponse)
async def get_concept_insight(
    label: str = Query(..., min_length=1, max_length=200),
    limit_notes: int = Query(default=10, ge=1, le=20),
    session: Session = Depends(get_tenant_session),
) -> ConceptInsightResponse:
    """Generate an AI insight for a concept, grounded in the user's notes."""
    svc = ConceptInsightService(session)
    return await svc.get_insight(label, limit_notes=limit_notes)
