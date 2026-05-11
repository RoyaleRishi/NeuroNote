"""Cross-note concept normalisation via embedding nearest-neighbor.

For each extracted concept, search concept_registry for the nearest
existing concept by cosine similarity. Above threshold, merge to the
canonical form and emit a SYNONYM_OF edge. Below threshold, treat as new.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.nlp.extraction import ConceptSpan

DEFAULT_COSINE_THRESHOLD = 0.88


@dataclass(frozen=True, slots=True)
class NormalisedConcept:
    canonical_text: str
    raw_text: str
    confidence: float
    is_new: bool


@dataclass(frozen=True, slots=True)
class SynonymEdge:
    from_text: str
    to_text: str


@dataclass(frozen=True, slots=True)
class NormalisationResult:
    concepts: list[NormalisedConcept]
    synonym_edges: list[SynonymEdge]


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a)
    bb = list(b)
    dot = sum(x * y for x, y in zip(aa, bb))
    na = math.sqrt(sum(x * x for x in aa))
    nb = math.sqrt(sum(x * x for x in bb))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _to_vector(raw: object) -> list[float]:
    """Coerce a pgvector column value to a list[float].

    Without a pgvector psycopg3 adapter registered, the column is returned
    as the literal string ``"[0.1,0.2,...]"``. Parse that into floats.
    Lists/tuples (already-decoded) pass through.
    """
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        if not s:
            return []
        return [float(part) for part in s.split(",")]
    return [float(v) for v in raw]  # type: ignore[attr-defined]


def normalise_concepts(
    session: Session,
    spans: list[ConceptSpan],
    *,
    embed: Callable[[str], list[float]],
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
) -> NormalisationResult:
    if not spans:
        return NormalisationResult(concepts=[], synonym_edges=[])

    # Load (text, embedding) for every existing concept with an embedding.
    rows = session.execute(
        sa_text(
            "SELECT concept_text, embedding FROM concept_registry "
            "WHERE embedding IS NOT NULL"
        )
    ).all()
    existing: list[tuple[str, list[float]]] = [(r[0], _to_vector(r[1])) for r in rows]

    out_concepts: list[NormalisedConcept] = []
    out_edges: list[SynonymEdge] = []
    for span in spans:
        emb = embed(span.text)
        best_text: str | None = None
        best_sim = 0.0
        for ex_text, ex_emb in existing:
            sim = _cosine(emb, ex_emb)
            if sim > best_sim:
                best_sim = sim
                best_text = ex_text

        if best_text is not None and best_sim >= cosine_threshold:
            if best_text.lower() != span.text.lower():
                # Near-duplicate with different surface form — normalise and record edge.
                out_concepts.append(NormalisedConcept(
                    canonical_text=best_text,
                    raw_text=span.text,
                    confidence=span.confidence,
                    is_new=False,
                ))
                out_edges.append(SynonymEdge(from_text=span.text, to_text=best_text))
            else:
                # Same text (case-insensitive) — already canonical, no edge needed.
                out_concepts.append(NormalisedConcept(
                    canonical_text=best_text,
                    raw_text=span.text,
                    confidence=span.confidence,
                    is_new=False,
                ))
        else:
            out_concepts.append(NormalisedConcept(
                canonical_text=span.text,
                raw_text=span.text,
                confidence=span.confidence,
                is_new=True,
            ))

    return NormalisationResult(concepts=out_concepts, synonym_edges=out_edges)
