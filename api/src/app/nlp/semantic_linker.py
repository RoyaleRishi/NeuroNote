"""Spreading-activation-style semantic note linking.

Given a note_id, finds related notes by:
1. Looking up the note's embedding in note_embeddings
2. Running a pgvector KNN search to find the K nearest other note embeddings
3. Returning ranked connections with similarity strength

The "spreading activation" metaphor: a note's embedding is its semantic position
in concept space; notes that are close in that space activate each other.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.repositories.embedding_repository import EmbeddingRepository
from shared.contracts.python.v1.connections import NoteConnectionItem, NoteConnectionsResponse

_LOGGER = logging.getLogger(__name__)
_DEFAULT_K = 10


@dataclass(slots=True)
class _NoteTitle:
    note_id: str
    note_title: str


class SemanticLinkerService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = EmbeddingRepository(session)

    def _get_note_embedding(self, note_id: str) -> list[float] | None:
        row = self._session.execute(
            text(
                """
                SELECT embedding::text
                FROM note_embeddings
                WHERE item_id = :note_id AND item_type = 'note'
                LIMIT 1
                """
            ),
            {"note_id": note_id},
        ).first()
        if row is None:
            return None

        raw = str(row[0]).strip("[]")
        try:
            return [float(x) for x in raw.split(",")]
        except ValueError:
            return None

    def _get_note_titles(self, note_ids: list[str]) -> dict[str, str]:
        if not note_ids:
            return {}
        rows = self._session.execute(
            text(
                """
                SELECT note_id, note_title
                FROM notes
                WHERE note_id = ANY(:ids)
                """
            ),
            {"ids": note_ids},
        ).all()
        return {str(r[0]): str(r[1]) for r in rows}

    def get_connections(
        self,
        note_id: str,
        *,
        limit: int = _DEFAULT_K,
        min_strength: float = 0.1,
    ) -> NoteConnectionsResponse:
        embedding = self._get_note_embedding(note_id)
        if embedding is None:
            return NoteConnectionsResponse(note_id=note_id, connections=[])

        try:
            neighbors = self._repo.nearest_neighbors(
                item_type="note",
                query_embedding=embedding,
                limit=limit + 1,  # +1 because the note itself will appear
            )
        except Exception as exc:
            _LOGGER.warning("Semantic linking KNN failed for note %s: %s", note_id, exc)
            return NoteConnectionsResponse(note_id=note_id, connections=[])

        candidate_ids = [n.item_id for n in neighbors if n.item_id != note_id][:limit]
        titles = self._get_note_titles(candidate_ids)

        connections: list[NoteConnectionItem] = []
        for neighbor in neighbors:
            if neighbor.item_id == note_id:
                continue
            strength = round(max(0.0, 1.0 - neighbor.distance), 4)
            if strength < min_strength:
                continue
            title = titles.get(neighbor.item_id, "")
            if not title:
                continue
            connections.append(
                NoteConnectionItem(
                    related_note_id=neighbor.item_id,
                    related_note_title=title,
                    strength=strength,
                    via_concepts=[],
                )
            )

        connections.sort(key=lambda c: c.strength, reverse=True)
        return NoteConnectionsResponse(note_id=note_id, connections=connections)


__all__ = ["SemanticLinkerService"]
