"""Salience ranking + redundancy filtering for concept candidates.

The noun-chunker (``extraction.py``) is high-recall: it returns every noun phrase
in the note, including off-topic asides and near-duplicate phrasings. This stage
turns that raw candidate list into a clean concept set using the note's own
embedding — fully deterministic, no LLM.

Two operations, both grounded in ``all-MiniLM-L6-v2`` cosine similarity:

1. **Adaptive salience threshold** (KeyBERT-style). Each candidate is scored by
   cosine similarity to the *document* embedding. Candidates are kept relative to
   the most-salient one (``score >= max_score - delta``), not by a fixed top-K —
   so a dense note keeps many concepts and a sparse note keeps few. There is **no
   hard cap** on concept count.

2. **Redundancy filter** (MMR diversity term, applied as a filter). Walking
   candidates in descending salience, a candidate is dropped when it is within
   ``redundancy_threshold`` cosine of an already-kept, higher-salience candidate.
   This is Maximal Marginal Relevance's novelty criterion used to *remove*
   near-duplicates rather than to select a fixed-size set — the deterministic fix
   for "neural net" vs "neural network" style redundancy that embeddings see as
   the same point.
"""
from __future__ import annotations

from typing import Callable

from app.nlp.extraction import ConceptSpan
from app.nlp.resolution.embedding import cosine_similarity

DEFAULT_THRESHOLD_DELTA = 0.30
# Tiny absolute floor: only excludes near-orthogonal noise. The real selection is
# relative (max_score - delta), which guarantees the most-salient concept always
# survives, so a diffuse multi-topic note never collapses to zero concepts.
DEFAULT_FLOOR = 0.02
DEFAULT_REDUNDANCY_THRESHOLD = 0.86

# Batched embedder: receives a list of texts, returns one vector per text in order.
Embedder = Callable[[list[str]], list[list[float]]]


def rank_and_filter(
    text: str,
    spans: list[ConceptSpan],
    *,
    embed: Embedder,
    threshold_delta: float = DEFAULT_THRESHOLD_DELTA,
    floor: float = DEFAULT_FLOOR,
    redundancy_threshold: float = DEFAULT_REDUNDANCY_THRESHOLD,
) -> list[ConceptSpan]:
    """Rank *spans* by salience to *text* and drop off-topic + redundant ones.

    ``embed`` encodes the document and all candidate texts in a single batched
    call. Returned spans carry ``confidence`` = their document cosine similarity
    and are ordered most-salient first.
    """
    if not spans:
        return []

    # One batched encode: document first, then every candidate, preserving order.
    vectors = embed([text, *(s.text for s in spans)])
    if len(vectors) != len(spans) + 1:
        raise ValueError(
            "embed() returned %d vectors for %d inputs"
            % (len(vectors), len(spans) + 1)
        )
    doc_vec = vectors[0]
    phrase_vecs = vectors[1:]

    scored = [
        (span, cosine_similarity(vec, doc_vec), vec)
        for span, vec in zip(spans, phrase_vecs)
    ]
    max_score = max(score for _, score, _ in scored)
    keep_threshold = max(floor, max_score - threshold_delta)

    # Salient candidates, most-salient first. Ties broken by text for determinism.
    salient = sorted(
        (item for item in scored if item[1] >= keep_threshold),
        key=lambda item: (-item[1], item[0].text.lower()),
    )

    kept: list[ConceptSpan] = []
    kept_vecs: list[list[float]] = []
    for span, score, vec in salient:
        if any(cosine_similarity(vec, kv) >= redundancy_threshold for kv in kept_vecs):
            continue  # near-duplicate of an already-kept, higher-salience concept
        kept.append(ConceptSpan(text=span.text, confidence=round(score, 4),
                                source=span.source, lemma=span.lemma))
        kept_vecs.append(vec)
    return kept


__all__ = ["rank_and_filter", "Embedder"]
