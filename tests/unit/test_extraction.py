from unittest.mock import MagicMock, patch

from app.nlp.extraction import ConceptSpan, extract_concepts


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
