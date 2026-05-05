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

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.nlp.spotting import _STOPWORDS as _CONCEPT_STOPWORDS  # noqa: PLC2701


def register_concepts(session: Session, items: list[tuple[str, str]]) -> None:
    """Register (concept_text, concept_entity_id) pairs.

    Already-known concepts are not overwritten so the first extracted form
    of a concept wins (later extractions reuse it via the SLM prompt).
    """
    normalised = [
        (t.strip().lower(), entity_id)
        for t, entity_id in items
        if t.strip() and t.strip().lower() not in _CONCEPT_STOPWORDS
    ]
    if not normalised:
        return

    import logging
    _log = logging.getLogger(__name__)
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
    except Exception as exc:
        _log.warning("register_concepts failed: %s", exc, exc_info=True)
        # Registry is best-effort; never fail NLP processing


def get_known_concepts(session: Session) -> list[str]:
    """Return all registered concept texts, sorted for deterministic prompts."""
    try:
        rows = session.execute(
            text("SELECT concept_text FROM concept_registry ORDER BY concept_text")
        ).all()
        return [str(row[0]) for row in rows]
    except Exception:
        return []


def registry_size(session: Session) -> int:
    """Return the number of registered concepts."""
    try:
        row = session.execute(
            text("SELECT COUNT(*) FROM concept_registry")
        ).scalar()
        return int(row) if row else 0
    except Exception:
        return 0


__all__ = ["register_concepts", "get_known_concepts", "registry_size"]
