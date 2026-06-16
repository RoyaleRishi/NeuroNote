"""Concept registry with Postgres persistence (tenant-aware).

Concept registrations are stored in the ``concept_registry`` table
which lives in the caller's tenant schema (resolved via session
``search_path``).  No in-memory cache — each call queries the DB
directly so tenant isolation is always respected.

The first-write-wins invariant is preserved: once "machine learning" is
registered, later registrations of the same normalised key are ignored
(ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)


def register_concepts(session: Session, items: list[tuple[str, str]]) -> None:
    """Register (concept_text, concept_entity_id) pairs.

    Already-known concepts are not overwritten so the first extracted form
    of a concept wins (later extractions reuse it via the SLM prompt).
    """
    normalised = [
        (t.strip().lower(), entity_id)
        for t, entity_id in items
        if t.strip()
    ]
    if not normalised:
        return

    try:
        for concept_text, entity_id in normalised:
            session.execute(
                text(
                    """
                    INSERT INTO concept_registry (concept_text, entity_id)
                    VALUES (:concept_text, :entity_id)
                    ON CONFLICT (concept_text) DO NOTHING
                    """
                ),
                {"concept_text": concept_text, "entity_id": entity_id},
            )
    except SQLAlchemyError as exc:
        # Registry is best-effort; never fail NLP processing on DB hiccups.
        _log.warning("register_concepts failed: %s", exc, exc_info=True)


def register_concepts_with_embeddings(
    session: Session, items: list[tuple[str, str, list[float]]]
) -> None:
    """Upsert (concept_text, entity_id, embedding) pairs into concept_registry.

    Rows that already exist are updated so the entity_id and embedding always
    reflect the most recent canonical form (first-write-wins only for text
    identity; new embeddings improve NN search quality).
    """
    if not items:
        return
    normalised = [
        (t.strip().lower(), entity_id, embedding)
        for t, entity_id, embedding in items
        if t.strip()
    ]
    if not normalised:
        return

    try:
        for concept_text, entity_id, embedding in normalised:
            vector_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            session.execute(
                text(
                    """
                    INSERT INTO concept_registry (concept_text, entity_id, embedding)
                    VALUES (:concept_text, :entity_id, CAST(:embedding AS vector(384)))
                    ON CONFLICT (concept_text) DO UPDATE
                      SET entity_id = EXCLUDED.entity_id,
                          embedding = EXCLUDED.embedding
                    """
                ),
                {
                    "concept_text": concept_text,
                    "entity_id": entity_id,
                    "embedding": vector_literal,
                },
            )
    except SQLAlchemyError as exc:
        # Registry is best-effort; never fail NLP processing on DB hiccups.
        _log.warning("register_concepts_with_embeddings failed: %s", exc, exc_info=True)


def get_known_concepts(session: Session) -> list[str]:
    """Return all registered concept texts, sorted for deterministic prompts."""
    rows = session.execute(
        text("SELECT concept_text FROM concept_registry ORDER BY concept_text")
    ).all()
    return [str(row[0]) for row in rows]


def registry_size(session: Session) -> int:
    """Return the number of registered concepts."""
    row = session.execute(
        text("SELECT COUNT(*) FROM concept_registry")
    ).scalar()
    return int(row) if row else 0


def prune_registry_rows(session: Session, entity_ids: list[str]) -> int:
    """Delete concept_registry rows for the given entity ids (full forget).

    **Not** best-effort. Unlike ``register_*`` (which must never fail NLP
    processing on a DB hiccup), pruning participates in the atomic
    delete/sweep/reconcile transaction: if the DELETE fails after the AGE node was
    already removed in the same transaction, the error must propagate so the whole
    transaction rolls back and parity is never left half-applied. Returns the
    number of rows deleted (0 on empty input).
    """
    ids = [i for i in entity_ids if i]
    if not ids:
        return 0
    result = session.execute(
        text("DELETE FROM concept_registry WHERE entity_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    )
    return int(result.rowcount or 0)


def prune_orphan_registry_rows(session: Session, live_entity_ids: set[str]) -> int:
    """Delete concept_registry rows whose entity_id is not in the live set.

    Catch-all used by the reconcile backstop to clean drift where the graph node
    was already removed. Like ``prune_registry_rows`` this is **not** best-effort —
    errors propagate so the per-tenant reconcile transaction rolls back atomically.
    """
    rows = session.execute(text("SELECT entity_id FROM concept_registry")).all()
    stale = [str(r[0]) for r in rows if str(r[0]) not in live_entity_ids]
    return prune_registry_rows(session, stale)


__all__ = [
    "register_concepts",
    "register_concepts_with_embeddings",
    "get_known_concepts",
    "registry_size",
    "prune_registry_rows",
    "prune_orphan_registry_rows",
]
