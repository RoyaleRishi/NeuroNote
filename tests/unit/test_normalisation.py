# tests/unit/test_normalisation.py
from unittest.mock import MagicMock

from app.nlp.extraction import ConceptSpan
from app.nlp.normalisation import SynonymEdge, normalise_concepts


def test_new_concept_inserted_to_registry() -> None:
    session = MagicMock()
    # SQLite-style bind so normalise_concepts takes the Python fallback path
    # against the MagicMock session.
    session.get_bind.return_value.url = "sqlite:///:memory:"
    session.execute.return_value.all.return_value = []  # empty registry

    spans = [ConceptSpan("data types", 0.99, "transformer")]
    result = normalise_concepts(session, spans, embed=lambda texts: [[0.1] * 384 for _ in texts])

    assert len(result.concepts) == 1
    assert result.concepts[0].canonical_text == "data types"
    assert result.concepts[0].is_new is True
    assert result.synonym_edges == []


def test_existing_concept_matched_above_threshold() -> None:
    session = MagicMock()
    session.get_bind.return_value.url = "sqlite:///:memory:"
    session.execute.return_value.all.return_value = [
        ("data type", [0.1] * 384),  # near-identical embedding
    ]

    spans = [ConceptSpan("data types", 0.99, "transformer")]
    result = normalise_concepts(
        session, spans,
        embed=lambda texts: [[0.1] * 384 for _ in texts],
        cosine_threshold=0.88,
    )

    assert len(result.concepts) == 1
    assert result.concepts[0].canonical_text == "data type"
    assert result.concepts[0].is_new is False
    assert result.synonym_edges == [
        SynonymEdge(from_text="data types", to_text="data type"),
    ]


def test_below_threshold_treated_as_new() -> None:
    session = MagicMock()
    session.get_bind.return_value.url = "sqlite:///:memory:"
    session.execute.return_value.all.return_value = [
        ("unrelated", [-1.0] + [0.0] * 383),
    ]
    spans = [ConceptSpan("data types", 0.99, "transformer")]
    result = normalise_concepts(
        session, spans,
        embed=lambda texts: [[1.0] + [0.0] * 383 for _ in texts],
        cosine_threshold=0.88,
    )
    assert result.concepts[0].canonical_text == "data types"
    assert result.concepts[0].is_new is True
    assert result.synonym_edges == []
