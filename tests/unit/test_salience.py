"""Unit tests for salience ranking + redundancy filtering.

A fake embedder returns hand-crafted vectors so behaviour is deterministic and
independent of the sentence-transformer model.
"""
from __future__ import annotations

from app.nlp.extraction import ConceptSpan
from app.nlp.salience import rank_and_filter


def _span(text: str, lemma: str | None = None) -> ConceptSpan:
    return ConceptSpan(text=text, confidence=1.0, source="noun_chunk",
                       lemma=lemma if lemma is not None else text.lower())


def _embedder(mapping: dict[str, list[float]]):
    def embed(texts: list[str]) -> list[list[float]]:
        return [mapping[t] for t in texts]

    return embed


def test_empty_returns_empty():
    assert rank_and_filter("doc", [], embed=_embedder({})) == []


def test_lemma_is_preserved_through_ranking():
    doc = "neural networks"
    spans = [_span("neural networks", lemma="neural network")]
    embed = _embedder({doc: [1.0, 0.0], "neural networks": [1.0, 0.0]})
    kept = rank_and_filter(doc, spans, embed=embed)
    assert kept[0].lemma == "neural network"


def test_off_topic_candidate_dropped_by_threshold():
    doc = "machine learning models"
    spans = [_span("neural networks"), _span("grocery list")]
    embed = _embedder({
        doc: [1.0, 0.0, 0.0],
        "neural networks": [0.95, 0.31, 0.0],   # high cosine to doc
        "grocery list": [0.0, 0.0, 1.0],         # orthogonal -> below threshold
    })
    kept = {s.text for s in rank_and_filter(doc, spans, embed=embed, threshold_delta=0.3)}
    assert "neural networks" in kept
    assert "grocery list" not in kept


def test_near_duplicate_dropped_keeps_higher_salience():
    doc = "neural networks"
    spans = [_span("neural network"), _span("neural networks")]
    embed = _embedder({
        doc: [1.0, 0.0],
        "neural networks": [1.0, 0.0],     # identical to doc -> top salience
        "neural network": [0.999, 0.044],  # near-identical -> redundant
    })
    kept = rank_and_filter(doc, spans, embed=embed, redundancy_threshold=0.86)
    assert [s.text for s in kept] == ["neural networks"]


def test_distinct_concepts_both_kept():
    doc = "databases and networking"
    spans = [_span("postgres"), _span("tcp")]
    embed = _embedder({
        doc: [0.7, 0.7],
        "postgres": [1.0, 0.0],
        "tcp": [0.0, 1.0],
    })
    kept = {s.text for s in rank_and_filter(doc, spans, embed=embed, threshold_delta=0.5)}
    assert kept == {"postgres", "tcp"}


def test_confidence_is_document_cosine_and_sorted():
    doc = "alpha beta"
    spans = [_span("low"), _span("high")]
    embed = _embedder({
        doc: [1.0, 0.0],
        "low": [0.8, 0.6],   # cosine 0.8
        "high": [1.0, 0.0],  # cosine 1.0
    })
    kept = rank_and_filter(doc, spans, embed=embed, threshold_delta=0.5)
    assert [s.text for s in kept] == ["high", "low"]  # sorted by salience desc
    assert kept[0].confidence == 1.0
    assert abs(kept[1].confidence - 0.8) < 1e-6
