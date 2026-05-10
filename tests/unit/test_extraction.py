import pytest
from unittest.mock import patch

from app.nlp.extraction import _clean, extract_concepts


@patch("app.nlp.extraction._inspec_pipeline")
def test_extract_concepts_uses_inspec(mock_pipeline):
    mock_pipeline.return_value = [
        {"word": " data types", "score": 0.95, "entity_group": "KEY"},
        {"word": " variables", "score": 0.88, "entity_group": "KEY"},
        {"word": " noise", "score": 0.40, "entity_group": "KEY"},
    ]
    with patch("app.nlp.extraction._yake_extractor") as mock_yake:
        mock_yake.extract_keywords.return_value = []
        spans = extract_concepts("dummy text long enough to pass length check")

    texts = {s.text for s in spans}
    assert "data types" in texts
    assert "variables" in texts
    assert "noise" not in texts  # below 0.85 threshold


@pytest.mark.parametrize("raw, expected", [
    ("data types", "data types"),
    ("the data types", "data types"),
    ("a variable", "variable"),
    ("THE Quick", "Quick"),
    ("etc.", None),
    ("of the", None),
    ("123", None),
    ("a", None),
    ("variable_name", None),       # underscore — code token
    ("camelCase", None),           # camelCase
    ("variables...", "variables"), # trailing punctuation strip
    ("", None),
    ("x" * 70, None),              # too long
])
def test_clean_filters(raw: str, expected: str | None) -> None:
    assert _clean(raw) == expected
