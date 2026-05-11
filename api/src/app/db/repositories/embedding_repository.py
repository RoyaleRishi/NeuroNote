"""pgvector embedding storage and nearest-neighbor search.

Extracted from GraphRepository to separate graph (AGE/Cypher) concerns
from vector (pgvector) concerns — Interface Segregation Principle.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(slots=True)
class EmbeddingNeighbor:
    item_id: str
    distance: float


class EmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_embedding(
        self,
        *,
        item_id: str,
        item_type: str,
        embedding: list[float],
    ) -> None:
        if len(embedding) != 384:
            raise ValueError("embedding must contain exactly 384 dimensions")

        vector_literal = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"

        self._session.execute(
            text(
                """
                INSERT INTO note_embeddings (item_id, item_type, embedding)
                VALUES (:item_id, :item_type, CAST(:embedding AS vector(384)))
                ON CONFLICT (item_id, item_type)
                DO UPDATE SET embedding = EXCLUDED.embedding, created_at = NOW()
                """
            ),
            {
                "item_id": item_id,
                "item_type": item_type,
                "embedding": vector_literal,
            },
        )

    def nearest_neighbors(
        self,
        *,
        item_type: str,
        query_embedding: list[float],
        limit: int = 5,
    ) -> list[EmbeddingNeighbor]:
        if len(query_embedding) != 384:
            raise ValueError("query_embedding must contain exactly 384 dimensions")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        query_literal = "[" + ",".join(f"{value:.8f}" for value in query_embedding) + "]"

        rows = self._session.execute(
            text(
                """
                SELECT item_id, embedding <=> CAST(:query_embedding AS vector(384)) AS distance
                FROM note_embeddings
                WHERE item_type = :item_type
                ORDER BY embedding <=> CAST(:query_embedding AS vector(384))
                LIMIT :limit
                """
            ),
            {
                "query_embedding": query_literal,
                "item_type": item_type,
                "limit": limit,
            },
        ).all()

        return [
            EmbeddingNeighbor(item_id=str(row[0]), distance=float(row[1]))
            for row in rows
        ]
