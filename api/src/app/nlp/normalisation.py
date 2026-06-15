"""Cross-note concept normalisation via embedding nearest-neighbor.

For each extracted concept, search ``concept_registry`` for the nearest
existing concept by cosine similarity. Above threshold, merge to the
canonical form and emit a SYNONYM_OF edge. Below threshold, treat as new.

On Postgres, lookups use the pgvector ``<=>`` cosine-distance operator
backed by the HNSW index on ``concept_registry.embedding`` — one round-trip
per span, no full-table scan. On SQLite (test fallback) the code degrades
to an in-Python cosine loop because pgvector is unavailable.

Embedding is batched: all span texts are encoded in a single call before
the per-span lookup loop runs, eliminating the per-span transformer
round-trip that dominated this hot path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.nlp.extraction import ConceptSpan
from app.nlp.resolution.embedding import cosine_similarity

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


def _is_postgres_session(session: Session) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    # ``get_bind()`` may return a ``Connection`` (no ``.url``); resolve to engine first.
    engine = getattr(bind, "engine", bind)
    url = getattr(engine, "url", None)
    if url is None:
        return False
    return str(url).startswith("postgresql")


def _vector_literal(embedding: list[float]) -> str:
    """Format a float list as a pgvector literal (e.g. ``[0.1,0.2,...]``)."""
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


def _decide(
    span: ConceptSpan,
    best_text: str | None,
    best_sim: float,
    cosine_threshold: float,
) -> tuple[NormalisedConcept, SynonymEdge | None]:
    """Common synonym-vs-new decision shared by the PG and SQLite paths."""
    if best_text is not None and best_sim >= cosine_threshold:
        if best_text.lower() != span.text.lower():
            return (
                NormalisedConcept(
                    canonical_text=best_text,
                    raw_text=span.text,
                    confidence=span.confidence,
                    is_new=False,
                ),
                SynonymEdge(from_text=span.text, to_text=best_text),
            )
        return (
            NormalisedConcept(
                canonical_text=best_text,
                raw_text=span.text,
                confidence=span.confidence,
                is_new=False,
            ),
            None,
        )
    return (
        NormalisedConcept(
            canonical_text=span.text,
            raw_text=span.text,
            confidence=span.confidence,
            is_new=True,
        ),
        None,
    )


def normalise_concepts(
    session: Session,
    spans: list[ConceptSpan],
    *,
    embed: Callable[[list[str]], list[list[float]]],
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
) -> NormalisationResult:
    """Normalise extracted spans against ``concept_registry``.

    ``embed`` is a batched embedder: it receives the full list of span texts
    and must return one vector per text in the same order. This eliminates
    the per-span transformer call that previously dominated this stage.
    """
    if not spans:
        return NormalisationResult(concepts=[], synonym_edges=[])

    embeddings = embed([span.text for span in spans])
    if len(embeddings) != len(spans):
        raise ValueError(
            "embed() returned %d vectors for %d spans"
            % (len(embeddings), len(spans))
        )

    if _is_postgres_session(session):
        return _normalise_pgvector(session, spans, embeddings, cosine_threshold)
    return _normalise_python(session, spans, embeddings, cosine_threshold)


def _normalise_pgvector(
    session: Session,
    spans: list[ConceptSpan],
    embeddings: list[list[float]],
    cosine_threshold: float,
) -> NormalisationResult:
    """One ANN query per span using the HNSW index on ``concept_registry``."""
    # pgvector cosine distance ``<=>`` returns ``1 - cosine_similarity``.
    max_distance = 1.0 - cosine_threshold

    stmt = sa_text(
        "SELECT concept_text, embedding <=> CAST(:q AS vector(384)) AS dist "
        "FROM concept_registry "
        "WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> CAST(:q AS vector(384)) "
        "LIMIT 1"
    )

    out_concepts: list[NormalisedConcept] = []
    out_edges: list[SynonymEdge] = []
    for span, emb in zip(spans, embeddings):
        row = session.execute(stmt, {"q": _vector_literal(emb)}).first()
        best_text: str | None = None
        best_sim = 0.0
        if row is not None:
            dist = float(row[1])
            if dist <= max_distance:
                best_text = str(row[0])
                best_sim = 1.0 - dist

        concept, edge = _decide(span, best_text, best_sim, cosine_threshold)
        out_concepts.append(concept)
        if edge is not None:
            out_edges.append(edge)

    return NormalisationResult(concepts=out_concepts, synonym_edges=out_edges)


def _normalise_python(
    session: Session,
    spans: list[ConceptSpan],
    embeddings: list[list[float]],
    cosine_threshold: float,
) -> NormalisationResult:
    """SQLite test-fallback: load registry, compare in Python."""
    rows = session.execute(
        sa_text(
            "SELECT concept_text, embedding FROM concept_registry "
            "WHERE embedding IS NOT NULL"
        )
    ).all()
    existing: list[tuple[str, list[float]]] = [
        (r[0], _to_vector(r[1])) for r in rows
    ]

    out_concepts: list[NormalisedConcept] = []
    out_edges: list[SynonymEdge] = []
    for span, emb in zip(spans, embeddings):
        best_text: str | None = None
        best_sim = 0.0
        for ex_text, ex_emb in existing:
            sim = cosine_similarity(emb, ex_emb)
            if sim > best_sim:
                best_sim = sim
                best_text = ex_text

        concept, edge = _decide(span, best_text, best_sim, cosine_threshold)
        out_concepts.append(concept)
        if edge is not None:
            out_edges.append(edge)

    return NormalisationResult(concepts=out_concepts, synonym_edges=out_edges)
