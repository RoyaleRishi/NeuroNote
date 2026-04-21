from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.tenant_session import get_tenant_session
from app.services.concept_insight_service import ConceptInsightService
from shared.contracts.python.v1.graph import ConceptInsightResponse

router = APIRouter()


@router.get("/concepts/insight", response_model=ConceptInsightResponse)
async def get_concept_insight(
    request: Request,
    label: str = Query(..., min_length=1, max_length=200),
    limit_notes: int = Query(default=10, ge=1, le=20),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> ConceptInsightResponse:
    """Generate an AI insight for a concept, grounded in the user's notes."""
    graph_name = f"nn_{user.schema_name}"
    svc = ConceptInsightService(session, graph_name=graph_name)
    return await svc.get_insight(label, limit_notes=limit_notes)
