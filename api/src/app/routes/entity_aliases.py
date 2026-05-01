from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.repositories.entity_alias_repository import EntityAliasRepository
from app.db.tenant_session import get_tenant_session
from app.nlp.resolution.resolver import CanonicalAlias, EntityResolver
from app.nlp.types import ExtractedEntity
from shared.contracts.python.v1.entity_alias import (
    ConfirmEntityAliasRequest,
    ConfirmEntityAliasResponse,
    EntityAliasCalibrationResponse,
    ResolveEntitiesRequest,
    ResolveEntitiesResponse,
    ResolvedEntityOutput,
    UnresolvedEntityOutput,
)

router = APIRouter()


@router.post("/entity-aliases/confirm", response_model=ConfirmEntityAliasResponse)
def confirm_entity_alias(
    payload: ConfirmEntityAliasRequest,
    session: Session = Depends(get_tenant_session),
) -> ConfirmEntityAliasResponse:
    with session.begin_nested():
        record = EntityAliasRepository(session).upsert_alias(
            alias_text=payload.alias_text,
            canonical_entity_id=payload.canonical_entity_id,
            canonical_name=payload.canonical_name,
            confidence=payload.confidence,
            source="user_confirmed",
        )
    session.commit()

    return ConfirmEntityAliasResponse(
        alias_text=record.alias_text,
        canonical_entity_id=record.canonical_entity_id,
        canonical_name=record.canonical_name,
        confidence=record.confidence,
        source=record.source,
    )


@router.get("/entity-aliases/calibration", response_model=EntityAliasCalibrationResponse)
def get_entity_alias_calibration(
    session: Session = Depends(get_tenant_session),
) -> EntityAliasCalibrationResponse:
    stats = EntityAliasRepository(session).get_calibration_stats()
    return EntityAliasCalibrationResponse(
        total_aliases=stats.total_aliases,
        avg_confidence=stats.avg_confidence,
    )


@router.post("/entity-aliases/resolve-preview", response_model=ResolveEntitiesResponse)
def resolve_entities_preview(
    payload: ResolveEntitiesRequest,
    session: Session = Depends(get_tenant_session),
) -> ResolveEntitiesResponse:
    alias_records = EntityAliasRepository(session).list_alias_index()
    alias_index = {
        alias_text: CanonicalAlias(
            canonical_entity_id=record.canonical_entity_id,
            canonical_name=record.canonical_name,
        )
        for alias_text, record in alias_records.items()
    }
    abbreviation_index = {
        alias_text.replace(" ", ""): record.canonical_name
        for alias_text, record in alias_records.items()
        if " " not in alias_text and 1 < len(alias_text) <= 10
    }
    resolver = EntityResolver(
        alias_index=alias_index,
        abbreviation_index=abbreviation_index,
    )
    batch = resolver.resolve(
        [
            ExtractedEntity(
                entity_id=item.entity_id,
                text=item.text,
                label=item.label,
                confidence=item.confidence,
            )
            for item in payload.entities
        ]
    )

    return ResolveEntitiesResponse(
        resolved=[
            ResolvedEntityOutput(
                source_entity_id=item.source_entity_id,
                source_text=item.source_text,
                canonical_entity_id=item.canonical_entity_id,
                canonical_name=item.canonical_name,
                confidence=item.confidence,
                matched_layer=item.matched_layer,
            )
            for item in batch.resolved
        ],
        unresolved=[
            UnresolvedEntityOutput(
                source_entity_id=item.source_entity_id,
                source_text=item.source_text,
            )
            for item in batch.unresolved
        ],
    )
