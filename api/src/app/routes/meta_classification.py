"""POST /v1/meta-classification-results — receive browser-computed meta edges.

In edge mode the browser identifies synonym and subtopic relationships between
concepts. Results are posted here so the server can write the durable AGE edges
and mark concepts as classified.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.repositories.graph_repository import GraphRepository
from app.db.tenant_session import get_tenant_session
from shared.contracts.python.v1.extraction import (
    SubmitMetaClassificationRequest,
    SubmitMetaClassificationResponse,
)

router = APIRouter()
_LOGGER = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    """Convert text to a lowercase slug for entity IDs."""
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "unknown"


@router.post(
    "/meta-classification-results",
    response_model=SubmitMetaClassificationResponse,
)
async def submit_meta_classification(
    body: SubmitMetaClassificationRequest,
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> SubmitMetaClassificationResponse:
    """Accept synonym/subtopic pairs from the browser and write to graph."""
    graph_name = f"nn_{user.schema_name}"
    now_iso = datetime.now(timezone.utc).isoformat()

    synonym_count = 0
    subtopic_count = 0

    # Check if the DB is PostgreSQL before attempting graph writes
    bind = session.get_bind()
    is_postgres = bind is not None and bind.dialect.name == "postgresql"

    if is_postgres and (body.synonym_pairs or body.subtopic_pairs):
        repo = GraphRepository(session=session)
        # Write SYNONYM_OF edges
        for pair in body.synonym_pairs:
            repo.upsert_typed_edge(
                source_label="Entity",
                source_id=f"concept-{_slugify(pair.a)}",
                target_label="Entity",
                target_id=f"concept-{_slugify(pair.b)}",
                relation_type="SYNONYM_OF",
                properties={"confidence": 0.9, "created_at": now_iso},
                graph_name=graph_name,
            )
            synonym_count += 1

        # Write SUBTOPIC_OF edges
        for pair in body.subtopic_pairs:
            repo.upsert_typed_edge(
                source_label="Entity",
                source_id=f"concept-{_slugify(pair.specific)}",
                target_label="Entity",
                target_id=f"concept-{_slugify(pair.broader)}",
                relation_type="SUBTOPIC_OF",
                properties={"confidence": 0.85, "created_at": now_iso},
                graph_name=graph_name,
            )
            subtopic_count += 1

        session.flush()
        # Restore tenant search_path after AGE operations.
        session.execute(
            sa_text(f"SET search_path TO {user.schema_name}, public")
        )

    # Mark concepts as classified in concept_registry
    if body.classified_concepts:
        try:
            now_dt = datetime.now(timezone.utc)
            normalised = [c.strip().lower() for c in body.classified_concepts if c.strip()]
            session.execute(
                sa_text(
                    "UPDATE concept_registry SET meta_classified_at = :now "
                    "WHERE concept_text = ANY(:texts)"
                ),
                {"now": now_dt, "texts": normalised},
            )
        except Exception:
            _LOGGER.debug("meta-classification: failed to mark classified", exc_info=True)

    session.commit()

    _LOGGER.info(
        "Edge meta-classification synced: synonyms=%d subtopics=%d classified=%d",
        synonym_count,
        subtopic_count,
        len(body.classified_concepts),
    )

    return SubmitMetaClassificationResponse(
        synonym_edges_written=synonym_count,
        subtopic_edges_written=subtopic_count,
    )
