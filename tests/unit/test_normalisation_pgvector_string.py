"""Regression: pgvector embeddings come back as strings without an adapter."""
from __future__ import annotations

from app.nlp.extraction import ConceptSpan
from app.nlp.normalisation import _to_vector, normalise_concepts


def test_to_vector_parses_pgvector_literal() -> None:
    parsed = _to_vector("[0.1,0.2,-0.3]")
    assert parsed == [0.1, 0.2, -0.3]


def test_to_vector_passes_through_list() -> None:
    assert _to_vector([1.0, 2.0]) == [1.0, 2.0]


class _FakeRow:
    def __init__(self, text: str, embedding: object) -> None:
        self._t = text
        self._e = embedding

    def __getitem__(self, i: int) -> object:
        return (self._t, self._e)[i]


class _FakeResult:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def all(self) -> list[_FakeRow]:
        return self._rows


class _FakeBind:
    url = "sqlite:///:memory:"


class _FakeSession:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def execute(self, _stmt: object, _params: dict | None = None) -> _FakeResult:
        return _FakeResult(self._rows)

    def get_bind(self) -> _FakeBind:
        return _FakeBind()


def test_normalise_concepts_handles_pgvector_string_embeddings() -> None:
    """Normalisation must not crash when pgvector returns embedding as a string.

    Exercises the SQLite/Python fallback path which still needs to parse the
    pgvector literal string format ``"[a,b,c]"`` returned from the registry.
    """
    rows = [_FakeRow("machine learning", "[1.0,0.0,0.0]")]
    session = _FakeSession(rows)

    result = normalise_concepts(
        session,  # type: ignore[arg-type]
        [ConceptSpan(text="ML", confidence=0.9, source="transformer")],
        embed=lambda texts: [[1.0, 0.0, 0.0] for _ in texts],
        cosine_threshold=0.5,
    )

    assert result.concepts[0].canonical_text == "machine learning"
    assert result.concepts[0].is_new is False
