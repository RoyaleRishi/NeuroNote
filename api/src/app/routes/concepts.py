from __future__ import annotations

from dataclasses import replace as _dataclass_replace

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.tenant_session import get_tenant_session
from app.nlp.config import NlpSettings, get_nlp_settings
from app.services.concept_insight_service import ConceptInsightService
from shared.contracts.python.v1.graph import ConceptInsightResponse

router = APIRouter()


def _resolve_llm_settings(session: Session) -> NlpSettings | None:
    """Read tenant preferences; return overridden NlpSettings for cloud mode, else None."""
    rows = session.execute(
        sa_text("SELECT key, value FROM user_preferences")
    ).all()
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
    user_settings = _resolve_llm_settings(session)
    svc = ConceptInsightService(session, settings=user_settings, graph_name=graph_name)
    return await svc.get_insight(label, limit_notes=limit_notes)
