"""Unit tests for lemma-keyed variant merge + compound IS_A subsumption."""
from __future__ import annotations

from app.nlp.extraction import ConceptSpan
from app.nlp.subsumption import IsAEdge, merge_and_subsume


def _span(text: str, conf: float = 0.9, lemma: str | None = None) -> ConceptSpan:
    # lemma defaults to the surface; tests pass an explicit spaCy-style lemma
    # where morphology matters (the real pipeline gets lemmas from extraction).
    return ConceptSpan(text=text, confidence=conf, source="noun_chunk",
                       lemma=lemma if lemma is not None else text.lower())


def test_variant_merge_collapses_plural_by_lemma():
    spans = [_span("neural networks", 0.9, lemma="neural network"),
             _span("neural network", 0.8, lemma="neural network")]
    result = merge_and_subsume(spans)
    assert len(result.concepts) == 1
    assert result.concepts[0].text == "neural networks"  # higher confidence wins


def test_variant_merge_handles_irregular_lemma():
    """Irregular plurals merge because spaCy gives them the same lemma."""
    spans = [_span("analyses", 0.9, lemma="analysis"),
             _span("analysis", 0.8, lemma="analysis")]
    result = merge_and_subsume(spans)
    assert len(result.concepts) == 1


def test_compound_subsumption_emits_is_a():
    spans = [_span("deep neural network", lemma="deep neural network"),
             _span("neural network", lemma="neural network"),
             _span("network", lemma="network")]
    edges = set(merge_and_subsume(spans).is_a_edges)
    assert IsAEdge(child="deep neural network", parent="neural network") in edges
    assert IsAEdge(child="neural network", parent="network") in edges


def test_subsumption_links_nearest_suffix_only():
    spans = [_span("deep neural network", lemma="deep neural network"),
             _span("neural network", lemma="neural network"),
             _span("network", lemma="network")]
    result = merge_and_subsume(spans)
    parents = {e.parent for e in result.is_a_edges if e.child == "deep neural network"}
    assert parents == {"neural network"}


def test_subsumption_matches_across_inflection_via_lemma():
    """A plural compound subsumes its singular head via lemma tokens."""
    spans = [_span("neural networks", lemma="neural network"),
             _span("network", lemma="network")]
    edges = merge_and_subsume(spans).is_a_edges
    assert any(e.parent == "network" for e in edges)


def test_no_edge_when_suffix_absent():
    spans = [_span("machine learning", lemma="machine learning"),
             _span("data pipeline", lemma="data pipeline")]
    assert merge_and_subsume(spans).is_a_edges == []


def test_empty_input():
    result = merge_and_subsume([])
    assert result.concepts == []
    assert result.is_a_edges == []
