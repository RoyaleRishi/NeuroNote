"""POST /v1/extract-candidates — deterministic candidate extraction for edge mode.

Edge mode calls this endpoint to obtain the same candidates the server uses
for cloud-mode LLM filtering — ensuring both modes operate on an identical,
rule-generated candidate pool.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.tenant_session import get_tenant_session
from app.nlp.concept_registry import get_known_concepts
from app.nlp.preprocessor import preprocess_content
from app.nlp.spotting import extract_entities_with_mentions
from app.nlp.types import BlockTextInput
from shared.contracts.python.v1.extraction_candidates import (
    ExtractCandidatesRequest,
    ExtractCandidatesResponse,
)

router = APIRouter()
_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 50


@router.post("/extract-candidates", response_model=ExtractCandidatesResponse)
async def extract_candidates(
    body: ExtractCandidatesRequest,
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> ExtractCandidatesResponse:
    """Extract deterministic concept candidates from note content.

    Always uses rule-based extraction (no LLM). Both cloud and edge modes
    call this to build an identical candidate pool before LLM filtering.
    """
    preprocessed = preprocess_content(body.content_text)
    known = get_known_concepts(session)

    entities, _ = extract_entities_with_mentions(
        blocks=[BlockTextInput(block_index=0, content_text=preprocessed)],
        dictionary_terms=known,
        extraction_profile="rule-only",
        seed_terms=[],
    )

    candidates = [e.text for e in entities[:_MAX_CANDIDATES]]

    _LOGGER.debug(
        "extract-candidates: note_id=%s candidates=%d",
        body.note_id,
        len(candidates),
    )

    return ExtractCandidatesResponse(
        candidates=candidates,
        content_hash=body.content_hash,
    )
