import pytest

from app.nlp.extraction import _clean, extract_concepts


def test_extract_concepts_returns_noun_phrases():
    """Noun-chunker yields complete noun phrases, not overlapping fragments."""
    text = (
        "Deep neural networks power modern machine translation. "
        "The transformer architecture relies on attention mechanisms."
    )
    spans = extract_concepts(text)
    texts = {s.text.lower() for s in spans}

    assert "deep neural networks" in texts
    assert "attention mechanisms" in texts
    assert all(s.source == "noun_chunk" for s in spans)
    # Leading determiner is stripped by is_stop ("the transformer architecture").
    assert "the transformer architecture" not in texts


def test_candidates_carry_spacy_lemma():
    """Each candidate carries its spaCy-lemmatised form as the normalisation key."""
    spans = extract_concepts("Deep neural networks are powerful models for vision.")
    by_text = {s.text.lower(): s.lemma for s in spans}
    assert by_text.get("deep neural networks") == "deep neural network"


def test_is_stop_strips_leading_modifier_keeps_content_modifier():
    """is_stop drops 'other' but keeps the content modifier 'deep'."""
    text = "Convolutional networks and other neural networks rival deep neural networks."
    texts = {s.text.lower() for s in extract_concepts(text)}
    assert not any(t.startswith("other ") for t in texts)
    # 'deep' is not a stopword, so the compound is kept intact.
    assert any("deep neural network" in t for t in texts)


def test_extract_concepts_dedupes_case_insensitively():
    text = "Machine learning is great. Machine Learning is everywhere in machine learning."
    spans = extract_concepts(text)
    keys = [s.text.lower() for s in spans]
    assert keys.count("machine learning") == 1


def test_extract_concepts_short_text_returns_empty():
    assert extract_concepts("hi") == []


def test_yake_fallback_off_by_default_no_statistical_source():
    text = "Deep neural networks power modern machine translation systems today."
    spans = extract_concepts(text)
    assert all(s.source != "statistical" for s in spans)


@pytest.mark.parametrize("raw, expected", [
    ("data types", "data types"),
    ("123", None),
    ("variable_name", None),       # underscore — code token
    ("camelCase", None),           # camelCase
    ("variables...", "variables"),  # trailing punctuation strip
    ("", None),
    ("x" * 70, None),              # too long
    ("a", None),                   # too short
])
def test_clean_is_non_linguistic_only(raw: str, expected: str | None) -> None:
    # _clean no longer does word-class filtering (determiners/stopwords) — that
    # is handled at the token level by is_stop. It only filters structurally.
    assert _clean(raw) == expected
