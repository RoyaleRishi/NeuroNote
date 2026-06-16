from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.tenant_session import get_tenant_session
from app.services.global_graph_service import GlobalGraphQuery, GlobalGraphService
from app.services.local_graph_service import LocalGraphNoteNotFoundError
from app.services.local_graph_service import LocalGraphQuery, LocalGraphService
from shared.contracts.python.v1.graph import GlobalGraphResponse
from shared.contracts.python.v1.graph import LocalGraphResponse

router = APIRouter()


@router.get("/graph/global", response_model=GlobalGraphResponse)
def get_global_graph(
    limit_nodes: int = Query(default=500, ge=1, le=2000),
    node_salience_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    relationship_confidence_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    include_types: str = Query(default="note,entity,relation"),
    subject_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> GlobalGraphResponse:
    include_type_values = [item.strip() for item in include_types.split(",") if item.strip()]
    graph_name = f"nn_{user.schema_name}"
    return GlobalGraphService(session, graph_name=graph_name).get_global_graph(
        GlobalGraphQuery(
            limit_nodes=limit_nodes,
            node_salience_threshold=node_salience_threshold,
            relationship_confidence_threshold=relationship_confidence_threshold,
            include_types=include_type_values,
            subject_id=subject_id,
            tag=tag,
        )
    )


@router.get("/graph/local/{note_id}", response_model=LocalGraphResponse)
def get_local_graph(
    note_id: str,
    max_hops: int = Query(default=1, ge=1, le=2),
    limit_nodes: int = Query(default=80, ge=1, le=150),
    node_salience_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    relationship_confidence_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    include_types: str = Query(default="note,entity,relation"),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> LocalGraphResponse:
    include_type_values = [item.strip() for item in include_types.split(",") if item.strip()]
    graph_name = f"nn_{user.schema_name}"
    try:
        return LocalGraphService(session, graph_name=graph_name).get_local_graph(
            LocalGraphQuery(
                note_id=note_id,
                max_hops=max_hops,
                limit_nodes=limit_nodes,
                node_salience_threshold=node_salience_threshold,
                relationship_confidence_threshold=relationship_confidence_threshold,
                include_types=include_type_values,
            )
        )
    except LocalGraphNoteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
