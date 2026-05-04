"""Unit tests for SLMExtractor (index-filter mode) and the llm-enhanced pipeline branch."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.nlp.slm_extractor import SLMExtractor, SLMExtractionResult, SLMConcept, _parse_index_result


_CANDIDATES = ["machine learning", "gradient descent", "backpropagation", "can"]


# ── _parse_index_result ──────────────────────────────────────────────────────

def test_parse_index_result_happy_path() -> None:
    raw = '{"keep": [0, 2], "relations": [[2, "USES", 0]], "summary": "ML uses backprop."}'
    result = _parse_index_result(raw, _CANDIDATES)
    assert result is not None
    assert len(result.concepts) == 2
    assert result.concepts[0].text == "machine learning"
    assert result.concepts[1].text == "backpropagation"
    assert len(result.relations) == 1
    assert result.relations[0].source == "backpropagation"
    assert result.relations[0].type == "USES"
    assert result.relations[0].target == "machine learning"
    assert result.summary == "ML uses backprop."


def test_parse_index_result_out_of_bounds_index_skipped() -> None:
    raw = '{"keep": [0, 99], "relations": [], "summary": ""}'
    result = _parse_index_result(raw, _CANDIDATES)
    assert result is not None
    assert len(result.concepts) == 1
    assert result.concepts[0].text == "machine learning"


def test_parse_index_result_invalid_relation_type_dropped() -> None:
    raw = '{"keep": [0, 1], "relations": [[0, "INVENTED_BY", 1]], "summary": ""}'
    result = _parse_index_result(raw, _CANDIDATES)
    assert result is not None
    assert result.relations == []


def test_parse_index_result_self_relation_dropped() -> None:
    raw = '{"keep": [0, 1], "relations": [[0, "IS_A", 0]], "summary": ""}'
    result = _parse_index_result(raw, _CANDIDATES)
    assert result is not None
    assert result.relations == []


def test_parse_index_result_invalid_json_returns_none() -> None:
    assert _parse_index_result("not json", _CANDIDATES) is None


def test_parse_index_result_non_dict_returns_none() -> None:
    assert _parse_index_result("[1, 2]", _CANDIDATES) is None


def test_parse_index_result_empty_candidates_returns_empty() -> None:
    raw = '{"keep": [], "relations": [], "summary": ""}'
    result = _parse_index_result(raw, [])
    assert result is not None
    assert result.concepts == []


# ── SLMExtractor ─────────────────────────────────────────────────────────────

_BASE_URL = "https://api.anthropic.com/v1/"


def test_slm_extractor_returns_result_on_success() -> None:
    good_json = '{"keep": [0, 2], "relations": [[2, "USES", 0]], "summary": "ML uses backprop."}'
    extractor = SLMExtractor(model="claude-haiku-4-5-20251001", api_key="test-key", base_url=_BASE_URL)

    with patch("app.nlp.slm_extractor.LLMClient") as mock_cls:
        mock_cls.return_value.complete.return_value = good_json
        result = extractor.extract(
            title="ML Training",
            preprocessed_content="Machine learning uses backpropagation.",
            candidates=_CANDIDATES,
            known_concepts=["neural network"],
        )

    assert result is not None
    assert len(result.concepts) == 2
    assert result.concepts[0].text == "machine learning"
    assert result.summary == "ML uses backprop."


def test_slm_extractor_returns_none_on_api_error() -> None:
    extractor = SLMExtractor(model="claude-haiku-4-5-20251001", api_key="test-key", base_url=_BASE_URL)

    with patch("app.nlp.slm_extractor.LLMClient") as mock_cls:
        mock_cls.return_value.complete.return_value = None
        result = extractor.extract(
            title="Any",
            preprocessed_content="Some content.",
            candidates=["machine learning"],
            known_concepts=[],
        )

    assert result is None


def test_slm_extractor_returns_empty_when_no_candidates() -> None:
    extractor = SLMExtractor(model="claude-haiku-4-5-20251001", api_key="test-key", base_url=_BASE_URL)
    result = extractor.extract(
        title="Any",
        preprocessed_content="Content.",
        candidates=[],
        known_concepts=[],
    )
    assert result is not None
    assert result.concepts == []
    assert result.relations == []


def test_slm_extractor_strips_markdown_fences() -> None:
    json_body = '{"keep": [0], "relations": [], "summary": "Attention is key."}'
    fenced = f"```json\n{json_body}\n```"
    extractor = SLMExtractor(model="claude-haiku-4-5-20251001", api_key="test-key", base_url=_BASE_URL)

    with patch("app.nlp.slm_extractor.LLMClient") as mock_cls:
        mock_cls.return_value.complete.return_value = fenced
        result = extractor.extract(
            title="Attention",
            preprocessed_content="Attention is key.",
            candidates=["attention mechanism"],
            known_concepts=[],
        )

    assert result is not None
    assert result.concepts[0].text == "attention mechanism"


# ── llm-enhanced pipeline branch ─────────────────────────────────────────────

def test_pipeline_llm_enhanced_uses_slm_result() -> None:
    from unittest.mock import ANY
    from app.nlp.config import NlpSettings
    from app.nlp.pipeline import NoteNlpPipeline

    slm_result = SLMExtractionResult(concepts=[], relations=[], summary="A test summary.")
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = slm_result

    settings = NlpSettings(
        model_name="rule-based-small",
        enable_embeddings=False,
        process_min_text_len=1,
        timeout_ms=5000,
        extraction_profile="llm-enhanced",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5-20251001",
        use_semantic_embeddings=False,
    )
    pipeline = NoteNlpPipeline(settings=settings)
    pipeline._slm_extractor = mock_extractor

    result = pipeline.extract(
        note_id="note-llm-1",
        title="Test Note",
        content_text="Some test content about neural networks.",
        content_hash="hash-llm-1",
    )

    mock_extractor.extract.assert_called_once_with(
        title="Test Note",
        preprocessed_content=ANY,
        candidates=ANY,
        known_concepts=[],
    )
    assert result.summary == "A test summary."
    assert result.note_id == "note-llm-1"


def test_pipeline_llm_enhanced_falls_back_to_rule_based_on_slm_none() -> None:
    from app.nlp.config import NlpSettings
    from app.nlp.pipeline import NoteNlpPipeline

    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = None

    settings = NlpSettings(
        model_name="rule-based-small",
        enable_embeddings=False,
        process_min_text_len=1,
        timeout_ms=5000,
        extraction_profile="llm-enhanced",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5-20251001",
        use_semantic_embeddings=False,
    )
    pipeline = NoteNlpPipeline(settings=settings)
    pipeline._slm_extractor = mock_extractor

    result = pipeline.extract(
        note_id="note-fallback-1",
        title="Fallback Note",
        content_text="Machine learning is a field of artificial intelligence.",
        content_hash="hash-fallback-1",
    )

    assert result.note_id == "note-fallback-1"
    assert result.summary == ""


def test_pipeline_llm_enhanced_concepts_are_lowercase() -> None:
    from app.nlp.config import NlpSettings
    from app.nlp.pipeline import NoteNlpPipeline

    slm_result = SLMExtractionResult(
        concepts=[
            SLMConcept(text="machine learning", confidence=0.9),
            SLMConcept(text="neural network", confidence=0.85),
        ],
        relations=[],
        summary="",
    )
    mock_extractor = MagicMock()
    mock_extractor.extract.return_value = slm_result

    settings = NlpSettings(
        model_name="rule-based-small",
        enable_embeddings=False,
        process_min_text_len=1,
        timeout_ms=5000,
        extraction_profile="llm-enhanced",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5-20251001",
        use_semantic_embeddings=False,
    )
    pipeline = NoteNlpPipeline(settings=settings)
    pipeline._slm_extractor = mock_extractor

    result = pipeline.extract(
        note_id="note-case-1",
        title="ML Note",
        content_text="Machine Learning and Neural Networks.",
        content_hash="hash-case-1",
    )

    entity_texts = [e.text for e in result.entities]
    assert all(t == t.lower() for t in entity_texts), f"Non-lowercase: {entity_texts}"
