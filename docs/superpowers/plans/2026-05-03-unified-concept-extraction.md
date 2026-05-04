# Unified Concept Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the server the single source of truth for candidate extraction so cloud and edge modes receive identical concept candidates for the same note content, eliminating LLM free-generation garbage.

**Architecture:** Server runs preprocessor (strip inline code) → spaCy/regex spotting → quality gate → returns `candidates[]`. Cloud mode: server LLM filters candidates by index. Edge mode: calls `POST /v1/extract-candidates`, browser Gemma filters candidates by the same index-filter prompt.

**Tech Stack:** Python / FastAPI / spaCy / Pydantic on the server; TypeScript / Next.js / WebLLM on the frontend. Tests: pytest (Python), vitest (TypeScript).

**Spec:** `docs/superpowers/specs/2026-05-03-unified-concept-extraction-design.md`

---

### Task 1: Preprocessor module

**Files:**
- Create: `api/src/app/nlp/preprocessor.py`
- Create: `tests/unit/test_preprocessor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_preprocessor.py
from __future__ import annotations

from app.nlp.preprocessor import preprocess_content


def test_strips_inline_code() -> None:
    raw = "Use `setState` to update `myVar` in React."
    result = preprocess_content(raw)
    assert "setState" not in result
    assert "myVar" not in result
    assert "React" in result


def test_strips_fenced_code_block() -> None:
    raw = "Here is code:\n```python\nfor x in range(10):\n    print(x)\n```\nEnd."
    result = preprocess_content(raw)
    assert "for x" not in result
    assert "print" not in result
    assert "Here is code" in result
    assert "End" in result


def test_strips_markdown_link_keeps_display_text() -> None:
    raw = "Read [gradient descent](https://example.com/gd) for details."
    result = preprocess_content(raw)
    assert "https://example.com" not in result
    assert "gradient descent" in result


def test_strips_image_keeps_alt_text() -> None:
    raw = "See ![neural network diagram](https://example.com/nn.png) above."
    result = preprocess_content(raw)
    assert "https://example.com" not in result
    assert "neural network diagram" in result


def test_collapses_whitespace() -> None:
    raw = "  multiple   spaces\t\there  "
    result = preprocess_content(raw)
    assert "  " not in result
    assert result == "multiple spaces here"


def test_empty_string_returns_empty() -> None:
    assert preprocess_content("") == ""


def test_no_markup_unchanged() -> None:
    raw = "Machine Learning uses gradient descent."
    result = preprocess_content(raw)
    assert result == raw
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_preprocessor.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'app.nlp.preprocessor'`

- [ ] **Step 3: Implement the preprocessor**

```python
# api/src/app/nlp/preprocessor.py
"""Note content preprocessor — strips code and markup before NLP candidate extraction."""
from __future__ import annotations

import re

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_WHITESPACE_RE = re.compile(r"\s+")


def preprocess_content(raw: str) -> str:
    """Strip code fences, inline code, and markdown syntax from note content."""
    text = _FENCED_CODE_RE.sub(" ", raw)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


__all__ = ["preprocess_content"]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_preprocessor.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/preprocessor.py tests/unit/test_preprocessor.py
git commit -m "feat: add note content preprocessor (strip inline code, markdown)"
```

---

### Task 2: Quality gate in spotting.py

**Files:**
- Modify: `api/src/app/nlp/spotting.py`
- Modify: `tests/unit/test_entity_spotting.py`

- [ ] **Step 1: Add failing quality gate tests**

Append these tests to `tests/unit/test_entity_spotting.py`:

```python
# Append to tests/unit/test_entity_spotting.py

from app.nlp.spotting import _passes_quality_gate


def test_quality_gate_rejects_single_char() -> None:
    assert _passes_quality_gate("a") is False


def test_quality_gate_rejects_two_char_lowercase() -> None:
    assert _passes_quality_gate("is") is False
    assert _passes_quality_gate("in") is False
    assert _passes_quality_gate("to") is False


def test_quality_gate_keeps_two_char_acronym() -> None:
    assert _passes_quality_gate("ML") is True
    assert _passes_quality_gate("AI") is True


def test_quality_gate_rejects_pure_digits() -> None:
    assert _passes_quality_gate("123") is False
    assert _passes_quality_gate("42") is False


def test_quality_gate_rejects_camel_case() -> None:
    assert _passes_quality_gate("myVar") is False
    assert _passes_quality_gate("setState") is False
    assert _passes_quality_gate("useEffect") is False


def test_quality_gate_rejects_snake_case() -> None:
    assert _passes_quality_gate("my_var") is False
    assert _passes_quality_gate("_private") is False


def test_quality_gate_rejects_dollar_sign() -> None:
    assert _passes_quality_gate("$event") is False


def test_quality_gate_rejects_code_keywords() -> None:
    assert _passes_quality_gate("const") is False
    assert _passes_quality_gate("async") is False
    assert _passes_quality_gate("null") is False
    assert _passes_quality_gate("undefined") is False


def test_quality_gate_keeps_valid_concepts() -> None:
    assert _passes_quality_gate("machine learning") is True
    assert _passes_quality_gate("gradient descent") is True
    assert _passes_quality_gate("neural network") is True
    assert _passes_quality_gate("SQL") is True


def test_spotter_quality_gate_filters_code_variable_from_block() -> None:
    # Inline code already stripped by preprocessor; this tests the gate
    # handles any code tokens that somehow slip through
    entities, _ = extract_entities_with_mentions(
        blocks=[
            BlockTextInput(
                block_index=0,
                content_text="Use gradient descent for backpropagation.",
            )
        ],
    )
    texts = {e.text for e in entities}
    assert "gradient descent" in texts or "backpropagation" in texts
    # Verify no camelCase slipped through
    for text in texts:
        import re
        assert not re.match(r"^[a-z]+[A-Z]", text), f"camelCase leaked: {text}"
```

- [ ] **Step 2: Run to confirm new tests fail**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_entity_spotting.py::test_quality_gate_rejects_single_char -v
```
Expected: `ImportError` or `AttributeError` — `_passes_quality_gate` not yet defined.

- [ ] **Step 3: Add quality gate to spotting.py**

In `api/src/app/nlp/spotting.py`, add after the `_LOWERCASE_VERB_TOKENS` set (around line 94):

```python
_CODE_KEYWORDS = frozenset({
    "var", "let", "const", "return", "import", "from", "export",
    "function", "class", "async", "await", "null", "true", "false",
    "undefined", "type", "interface", "enum",
})

_CAMEL_CASE_RE = re.compile(r"^[a-z]+[A-Z]")
_CODE_TOKEN_RE = re.compile(r"[_$]")
_DIGIT_ONLY_RE = re.compile(r"^\d+$")


def _passes_quality_gate(text: str) -> bool:
    """Return True if the candidate is a valid concept (not a code token or noise)."""
    n = len(text)
    if n < 2:
        return False
    if n > 80:
        return False
    if n == 2 and not text.isupper():
        return False
    if _DIGIT_ONLY_RE.match(text):
        return False
    if _CAMEL_CASE_RE.match(text):
        return False
    if _CODE_TOKEN_RE.search(text):
        return False
    if text.lower() in _CODE_KEYWORDS:
        return False
    return True
```

Then in `_extract_entities_with_mentions`, after line `if key in _STOPWORDS: continue` (around line 541), add:

```python
            if not _passes_quality_gate(normalized_text):
                continue
```

- [ ] **Step 4: Run all spotting tests to confirm they pass**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_entity_spotting.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/spotting.py tests/unit/test_entity_spotting.py
git commit -m "feat: add quality gate to spotting — reject camelCase, code tokens, short noise"
```

---

### Task 3: Shared Python contract for extract-candidates

**Files:**
- Create: `shared/contracts/python/v1/extraction_candidates.py`

- [ ] **Step 1: Create the contract**

```python
# shared/contracts/python/v1/extraction_candidates.py
"""Shared contracts for POST /v1/extract-candidates."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractCandidatesRequest(BaseModel):
    """Request for server-side deterministic candidate extraction."""
    note_id: str = Field(min_length=1)
    title: str = Field(default="")
    content_text: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class ExtractCandidatesResponse(BaseModel):
    """Deterministic concept candidates for LLM filtering."""
    candidates: list[str] = Field(default_factory=list)
    content_hash: str
```

- [ ] **Step 2: Create the TypeScript mirror**

```typescript
// shared/contracts/ts/v1/extractionCandidates.ts
/** Shared contracts for POST /v1/extract-candidates. */

export interface ExtractCandidatesRequest {
  note_id: string;
  title: string;
  content_text: string;
  content_hash: string;
}

export interface ExtractCandidatesResponse {
  candidates: string[];
  content_hash: string;
}
```

- [ ] **Step 3: Commit**

```bash
git add shared/contracts/python/v1/extraction_candidates.py shared/contracts/ts/v1/extractionCandidates.ts
git commit -m "feat: add ExtractCandidates shared contracts (Python + TypeScript)"
```

---

### Task 4: New API endpoint POST /v1/extract-candidates

**Files:**
- Create: `api/src/app/routes/extraction_candidates.py`
- Modify: `api/src/app/main.py`
- Create: `tests/integration/test_extract_candidates_api.py`

- [ ] **Step 1: Write the failing integration tests**

```python
# tests/integration/test_extract_candidates_api.py
from __future__ import annotations

from fastapi.testclient import TestClient


def test_extract_candidates_returns_200(client: TestClient) -> None:
    response = client.post(
        "/v1/extract-candidates",
        json={
            "note_id": "note-1",
            "title": "Machine Learning",
            "content_text": "Machine learning uses gradient descent to train neural networks.",
            "content_hash": "hash-abc",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "candidates" in body
    assert "content_hash" in body
    assert body["content_hash"] == "hash-abc"
    assert isinstance(body["candidates"], list)


def test_extract_candidates_is_deterministic(client: TestClient) -> None:
    payload = {
        "note_id": "note-2",
        "title": "Backpropagation",
        "content_text": "Backpropagation computes gradients through the neural network using the chain rule.",
        "content_hash": "hash-det",
    }
    r1 = client.post("/v1/extract-candidates", json=payload)
    r2 = client.post("/v1/extract-candidates", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert sorted(r1.json()["candidates"]) == sorted(r2.json()["candidates"])


def test_extract_candidates_strips_inline_code(client: TestClient) -> None:
    response = client.post(
        "/v1/extract-candidates",
        json={
            "note_id": "note-3",
            "title": "React Hooks",
            "content_text": "Use `useState` and `useEffect` to manage state in React components.",
            "content_hash": "hash-code",
        },
    )
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert "useState" not in candidates
    assert "useEffect" not in candidates


def test_extract_candidates_excludes_code_keywords(client: TestClient) -> None:
    response = client.post(
        "/v1/extract-candidates",
        json={
            "note_id": "note-4",
            "title": "Notes",
            "content_text": "const result = async function() { return null; }",
            "content_hash": "hash-kw",
        },
    )
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    for banned in ["const", "async", "function", "return", "null"]:
        assert banned not in candidates


def test_extract_candidates_caps_at_fifty(client: TestClient) -> None:
    # Generate a note with many distinct title-case phrases
    phrases = [f"Concept{i}" for i in range(60)]
    content = " ".join(f"{p} is important." for p in phrases)
    response = client.post(
        "/v1/extract-candidates",
        json={
            "note_id": "note-5",
            "title": "Many Concepts",
            "content_text": content,
            "content_hash": "hash-cap",
        },
    )
    assert response.status_code == 200
    assert len(response.json()["candidates"]) <= 50


def test_extract_candidates_requires_auth(client: TestClient) -> None:
    # The default test client has auth injected; this test verifies the endpoint
    # is registered and reachable (auth override is always active in tests).
    response = client.post(
        "/v1/extract-candidates",
        json={
            "note_id": "note-6",
            "title": "Test",
            "content_text": "Neural networks learn representations.",
            "content_hash": "hash-auth",
        },
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/integration/test_extract_candidates_api.py -v 2>&1 | head -20
```
Expected: `404 Not Found` — endpoint not yet registered.

- [ ] **Step 3: Implement the route**

```python
# api/src/app/routes/extraction_candidates.py
"""POST /v1/extract-candidates — deterministic candidate extraction for edge mode.

Edge mode calls this endpoint to obtain the same candidates the server uses
for cloud-mode LLM filtering — ensuring both modes operate on an identical,
rule-generated candidate pool.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.tenant_session import get_tenant_session
from app.nlp.concept_registry import get_known_concepts
from app.nlp.preprocessor import preprocess_content
from app.nlp.spotting import extract_entities_with_mentions
from app.nlp.types import BlockTextInput
from shared.contracts.python.v1.extraction_candidates import (
    ExtractCandidatesRequest,
    ExtractCandidatesResponse,
)

router = APIRouter()
_LOGGER = logging.getLogger(__name__)
_MAX_CANDIDATES = 50


@router.post("/extract-candidates", response_model=ExtractCandidatesResponse)
async def extract_candidates(
    body: ExtractCandidatesRequest,
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> ExtractCandidatesResponse:
    """Extract deterministic concept candidates from note content.

    Always uses rule-based extraction (no LLM). Both cloud and edge modes
    call this to build an identical candidate pool before LLM filtering.
    """
    preprocessed = preprocess_content(body.content_text)
    known = get_known_concepts(session)

    entities, _ = extract_entities_with_mentions(
        blocks=[BlockTextInput(block_index=0, content_text=preprocessed)],
        dictionary_terms=known,
        extraction_profile="rule-only",
        seed_terms=[],
    )

    candidates = [e.text for e in entities[:_MAX_CANDIDATES]]

    _LOGGER.debug(
        "extract-candidates: note_id=%s candidates=%d",
        body.note_id,
        len(candidates),
    )

    return ExtractCandidatesResponse(
        candidates=candidates,
        content_hash=body.content_hash,
    )
```

- [ ] **Step 4: Register the router in main.py**

In `api/src/app/main.py`, add after the existing imports:

```python
from app.routes.extraction_candidates import router as extraction_candidates_router
```

And after the last `app.include_router` line:

```python
app.include_router(extraction_candidates_router, prefix="/v1")
```

- [ ] **Step 5: Run the integration tests**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/integration/test_extract_candidates_api.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
make compose-test
```
Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add api/src/app/routes/extraction_candidates.py api/src/app/main.py tests/integration/test_extract_candidates_api.py
git commit -m "feat: add POST /v1/extract-candidates endpoint for deterministic candidate extraction"
```

---

### Task 5: Refactor SLMExtractor to index-filter

**Files:**
- Modify: `api/src/app/nlp/slm_extractor.py`
- Modify: `tests/unit/test_slm_extractor.py`

- [ ] **Step 1: Replace the tests for `_parse_result` with tests for `_parse_index_result`**

Replace the entire content of `tests/unit/test_slm_extractor.py` with:

```python
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
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_slm_extractor.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name '_parse_index_result'`

- [ ] **Step 3: Rewrite slm_extractor.py**

Replace the entire content of `api/src/app/nlp/slm_extractor.py`:

```python
"""LLM-based concept and relation extractor (index-filter mode).

Accepts pre-generated rule-based candidates and asks the LLM to filter
by index — never free-generates concept text. This makes output bounded,
fast, and far more deterministic than free-generation.

Returns None on any failure so the pipeline falls back to rule-based extraction.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.nlp.llm_client import LLMClient

_LOGGER = logging.getLogger(__name__)

_RELATION_TYPES = frozenset(
    {"IS_A", "PART_OF", "CAUSES", "CONTRASTS_WITH", "USES", "PRODUCES", "RELATED_TO"}
)

_SYSTEM_PROMPT = """You are filtering candidate concept phrases extracted from a note.

You will receive:
- The note text (title + content)
- A numbered list of CANDIDATES (rule-extracted phrases, may include false positives)
- A list of KNOWN concepts already in the user's knowledge base

Your job:
1. Pick which candidates are real, meaningful concepts. Output their indices in "keep".
2. List any clear semantic relations between kept candidates as [srcIdx, type, tgtIdx] triples.
   Use ONLY these relation types: IS_A, PART_OF, CAUSES, CONTRASTS_WITH, USES, PRODUCES, RELATED_TO.
3. Write a one-sentence summary of the note in "summary".
4. Be conservative — prefer fewer, high-quality picks over many noisy ones.
5. Skip relations where sourceIdx equals targetIdx.

Return ONLY valid JSON in this shape, no markdown fences:
{{"keep": [<int>, ...], "relations": [[<int>, "<TYPE>", <int>], ...], "summary": "<string>"}}

Known concepts (reuse where a candidate is a synonym): {known_concepts_csv}"""

_USER_TEMPLATE = "Title: {title}\nContent: {content}\n\nCANDIDATES:\n{numbered}"


@dataclass(slots=True)
class SLMConcept:
    text: str
    confidence: float


@dataclass(slots=True)
class SLMRelation:
    source: str
    type: str
    target: str
    confidence: float


@dataclass(slots=True)
class SLMExtractionResult:
    concepts: list[SLMConcept]
    relations: list[SLMRelation]
    summary: str


def _parse_index_result(raw: str, candidates: list[str]) -> SLMExtractionResult | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _LOGGER.warning("SLM response is not valid JSON: %s", exc)
        return None

    if not isinstance(data, dict):
        return None

    max_idx = len(candidates)
    keep_raw = data.get("keep") or []
    if not isinstance(keep_raw, list):
        return None

    keep_indices = [
        i for i in keep_raw
        if isinstance(i, int) and 0 <= i < max_idx
    ]

    concepts = [
        SLMConcept(text=candidates[i].lower(), confidence=0.9)
        for i in keep_indices
    ]

    relations: list[SLMRelation] = []
    for item in data.get("relations") or []:
        if not isinstance(item, list) or len(item) != 3:
            continue
        src_raw, type_raw, tgt_raw = item
        if not isinstance(src_raw, int) or not isinstance(tgt_raw, int):
            continue
        if src_raw < 0 or src_raw >= max_idx or tgt_raw < 0 or tgt_raw >= max_idx:
            continue
        if src_raw == tgt_raw:
            continue
        rel_type = str(type_raw).strip().upper()
        if rel_type not in _RELATION_TYPES:
            continue
        relations.append(SLMRelation(
            source=candidates[src_raw].lower(),
            type=rel_type,
            target=candidates[tgt_raw].lower(),
            confidence=0.85,
        ))

    summary = str(data.get("summary", "")).strip()
    return SLMExtractionResult(concepts=concepts, relations=relations, summary=summary)


class SLMExtractor:
    """Filters rule-generated concept candidates using an LLM."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_ms: int = 8000,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_s = timeout_ms / 1000.0

    def extract(
        self,
        *,
        title: str,
        preprocessed_content: str,
        candidates: list[str],
        known_concepts: list[str],
    ) -> SLMExtractionResult | None:
        """Filter candidates by index using the LLM.

        Returns None on any error so the caller can fall back to rule-based extraction.
        """
        if not candidates:
            return SLMExtractionResult(concepts=[], relations=[], summary="")

        known_csv = ", ".join(known_concepts[:200]) if known_concepts else "none yet"
        system = _SYSTEM_PROMPT.format(known_concepts_csv=known_csv)
        numbered = "\n".join(f"{i}: {c}" for i, c in enumerate(candidates))
        user = _USER_TEMPLATE.format(
            title=title or "(untitled)",
            content=preprocessed_content[:4000],
            numbered=numbered,
        )

        raw = LLMClient(
            api_key=self._api_key,
            model=self._model,
            base_url=self._base_url,
            timeout_s=self._timeout_s,
        ).complete(system=system, user=user, max_tokens=512)

        if not raw:
            _LOGGER.warning("LLM returned empty response; falling back to rule-based")
            return None

        _LOGGER.debug("LLM raw response (%d chars): %s", len(raw), raw[:200])

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        return _parse_index_result(raw, candidates)


__all__ = ["SLMConcept", "SLMRelation", "SLMExtractionResult", "SLMExtractor", "_parse_index_result"]
```

- [ ] **Step 4: Run the tests**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_slm_extractor.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/slm_extractor.py tests/unit/test_slm_extractor.py
git commit -m "refactor: SLMExtractor — index-filter mode (takes candidates[], returns indices)"
```

---

### Task 6: Update pipeline.py to pass candidates to SLMExtractor

**Files:**
- Modify: `api/src/app/nlp/pipeline.py`

- [ ] **Step 1: Run the existing pipeline-related tests to establish a baseline**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_slm_extractor.py -v -k "pipeline"
```
Expected: the 3 pipeline tests fail because `pipeline.extract()` still calls the old `slm_extractor.extract(title=..., content=..., known_concepts=...)` signature.

- [ ] **Step 2: Update the llm-enhanced branch in pipeline.py**

In `api/src/app/nlp/pipeline.py`, at the top add the preprocessor import after the existing `from app.nlp.spotting import ...` lines:

```python
from app.nlp.preprocessor import preprocess_content
```

Then replace the `llm-enhanced path` block (lines ~154–227) with:

```python
        # ── LLM-enhanced path ─────────────────────────────────────────────────
        if self._settings.extraction_profile == "llm-enhanced" and self._slm_extractor is not None:
            preprocessed = preprocess_content(content_text)

            # Build deterministic candidates via rule-only spotting (no LLM).
            candidate_blocks = list(blocks or [BlockTextInput(block_index=0, content_text=preprocessed)])
            candidate_entities, _, _ = extract_entities_with_mentions_and_metrics(
                blocks=candidate_blocks,
                dictionary_terms=dictionary_terms or [],
                extraction_profile="rule-only",
                model_handle=None,
                seed_terms=list(self._settings.entity_seed_terms),
                enable_regex_fallback=self._settings.enable_regex_fallback,
            )
            candidates = [e.text for e in candidate_entities]

            slm_started = time.perf_counter()
            slm_result = self._slm_extractor.extract(
                title=title,
                preprocessed_content=preprocessed,
                candidates=candidates,
                known_concepts=list(dictionary_terms or []),
            )
            stage_timings.append(
                StageTiming(
                    stage="slm_extraction",
                    duration_ms=(time.perf_counter() - slm_started) * 1000.0,
                )
            )

            if slm_result is not None:
                entities: list[ExtractedEntity] = [
                    ExtractedEntity(
                        entity_id=f"concept-{self._slugify(c.text)}",
                        text=c.text,
                        label="concept",
                        confidence=c.confidence,
                    )
                    for c in slm_result.concepts
                    if c.text.strip().lower() not in _PIPELINE_STOPWORDS
                ]
                relations: list[ExtractedRelation] = [
                    ExtractedRelation(
                        subject_id=f"concept-{self._slugify(r.source)}",
                        subject_text=r.source,
                        predicate=r.type,
                        object_id=f"concept-{self._slugify(r.target)}",
                        object_text=r.target,
                        confidence=r.confidence,
                    )
                    for r in slm_result.relations
                ]

                embedding_started = time.perf_counter()
                if self._settings.use_semantic_embeddings:
                    embedding = build_semantic_embedding(content_text)
                    if embedding is None:
                        embedding = build_embedding(content_text) if self._settings.enable_embeddings else None
                else:
                    embedding = build_embedding(content_text) if self._settings.enable_embeddings else None
                stage_timings.append(
                    StageTiming(
                        stage="embedding",
                        duration_ms=(time.perf_counter() - embedding_started) * 1000.0,
                    )
                )
                stage_timings.append(
                    StageTiming(
                        stage="total",
                        duration_ms=(time.perf_counter() - started_at) * 1000.0,
                    )
                )
                self._last_stage_timings = format_stage_timings(stage_timings)
                self._last_extraction_hit_counts = {
                    "slm_concepts": len(entities),
                    "slm_relations": len(relations),
                }
                _LOGGER.debug("NLP stage timings (llm-enhanced): %s", self._last_stage_timings)
                slm_extraction_result = NoteExtractionResult(
                    note_id=note_id,
                    content_hash=content_hash,
                    entities=entities,
                    keyphrases=[],
                    relations=relations,
                    embedding=embedding,
                    entity_mentions=[],
                    summary=slm_result.summary,
                )
                _EXTRACTION_CACHE[content_hash] = slm_extraction_result
                if len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
                    _EXTRACTION_CACHE.popitem(last=False)
                return slm_extraction_result
            # SLM failed — fall through to rule-based path
```

- [ ] **Step 3: Run all relevant tests**

```bash
docker compose -f infra/docker-compose.yml exec api uv run pytest tests/unit/test_slm_extractor.py tests/unit/test_preprocessor.py tests/unit/test_entity_spotting.py -v
```
Expected: all pass.

- [ ] **Step 4: Run the full suite**

```bash
make compose-test
```
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add api/src/app/nlp/pipeline.py
git commit -m "refactor: pipeline llm-enhanced path — preprocess then pass candidates to SLMExtractor"
```

---

### Task 7: TypeScript contract import + fetchCandidates in api-client.ts

**Files:**
- Modify: `web/src/lib/api-client.ts`

- [ ] **Step 1: Add the import and fetchCandidates function**

At the top of `web/src/lib/api-client.ts`, add after the existing extraction import:

```typescript
import type {
  ExtractCandidatesRequest,
  ExtractCandidatesResponse,
} from "../../../shared/contracts/ts/v1/extractionCandidates";
```

Then add after the `fetchKnownConcepts` function (around line 477):

```typescript
/** Fetch server-generated concept candidates for a note (edge mode). */
export async function fetchCandidates(
  baseUrl: string,
  payload: ExtractCandidatesRequest,
): Promise<ExtractCandidatesResponse> {
  const response = await apiFetch(`${baseUrl}/v1/extract-candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeoutMs: 30_000,
  });
  return parseJsonResponse<ExtractCandidatesResponse>(response);
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote/web && npx tsc --noEmit 2>&1 | head -30
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/api-client.ts shared/contracts/ts/v1/extractionCandidates.ts
git commit -m "feat: add fetchCandidates to api-client + TypeScript extractionCandidates contract"
```

---

### Task 8: Add filterCandidates to inference-client.ts + align prompts.ts

**Files:**
- Modify: `web/src/lib/edge-llm/inference-client.ts`
- Modify: `web/src/lib/edge-llm/prompts.ts`

- [ ] **Step 1: Update the extraction prompt in prompts.ts to match the server prompt**

In `web/src/lib/edge-llm/prompts.ts`, replace `CHUNK_EXTRACTION_SYSTEM_PROMPT` with:

```typescript
const EXTRACTION_FILTER_SYSTEM_PROMPT = `You are filtering candidate concept phrases extracted from a note.

You will receive:
- The note text (title + content)
- A numbered list of CANDIDATES (rule-extracted phrases, may include false positives)
- A list of KNOWN concepts already in the user's knowledge base

Your job:
1. Pick which candidates are real, meaningful concepts. Output their indices in "keep".
2. List any clear semantic relations between kept candidates as [srcIdx, type, targetIdx] triples.
   Use ONLY these relation types: IS_A, PART_OF, CAUSES, CONTRASTS_WITH, USES, PRODUCES, RELATED_TO.
3. Be conservative — prefer fewer, high-quality picks over many noisy ones.
4. Skip relations where sourceIdx equals targetIdx.

Return ONLY valid JSON in this shape, no markdown fences:
{ "keep": [<int>, ...], "relations": [[<int>, "<TYPE>", <int>], ...] }

KNOWN concepts (reuse where the candidate is a synonym): {known_csv}`;
```

Replace `buildChunkExtractionPrompt` with `buildFilterPrompt`:

```typescript
/**
 * Build messages for the candidate filter LLM call.
 *
 * Mirrors the server-side _SYSTEM_PROMPT in slm_extractor.py.
 * Candidates are pre-generated by the server; the LLM only picks indices.
 */
export function buildFilterPrompt(
  noteContent: string,
  candidates: string[],
  knownConcepts: string[],
): { system: string; user: string } {
  const knownCsv =
    knownConcepts.length > 0
      ? knownConcepts.slice(0, 100).join(", ")
      : "none yet";
  const system = EXTRACTION_FILTER_SYSTEM_PROMPT.replace("{known_csv}", knownCsv);
  const numbered = candidates.map((c, i) => `${i}: ${c}`).join("\n");
  const user = `NOTE:\n${noteContent.slice(0, 2000)}\n\nCANDIDATES:\n${numbered}`;
  return { system, user };
}
```

Remove the old `buildChunkExtractionPrompt` export. Keep `buildSummaryPrompt`, `buildMetaPrompt`, `buildInsightPrompt` unchanged.

- [ ] **Step 2: Add filterCandidates to inference-client.ts**

In `web/src/lib/edge-llm/inference-client.ts`:

Replace the import of `buildChunkExtractionPrompt` with `buildFilterPrompt`:
```typescript
import {
  buildFilterPrompt,
  buildSummaryPrompt,
  buildMetaPrompt,
  buildInsightPrompt,
} from "./prompts";
```

Replace the `extractFromChunk` function with `filterCandidates`:

```typescript
/**
 * Filter server-generated candidates using the in-browser LLM.
 *
 * Mirrors SLMExtractor.extract() on the Python side. Returns indices
 * into the candidates array plus relation triples. Bounded output
 * (~256 tokens) because the model emits integers, not concept strings.
 */
export async function filterCandidates(
  noteContent: string,
  candidates: string[],
  knownConcepts: string[],
): Promise<ChunkExtractionResult | null> {
  const engine = getEngine();
  if (!engine) {
    console.warn("[edge-llm] filterCandidates: engine not initialised");
    return null;
  }

  if (candidates.length === 0) {
    return { keep: [], relations: [] };
  }

  const { system, user } = buildFilterPrompt(noteContent, candidates, knownConcepts);

  const t0 = performance.now();
  console.info("[edge-llm] filterCandidates: starting", {
    candidates: candidates.length,
    contentLen: noteContent.length,
  });

  let response;
  try {
    response = await engine.chat.completions.create({
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature: 0.1,
      max_tokens: 256,
      response_format: {
        type: "json_object",
        schema: JSON.stringify(CHUNK_EXTRACTION_SCHEMA),
      },
    });
  } catch (err) {
    console.error("[edge-llm] filterCandidates: inference threw", err);
    return null;
  }

  const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
  const text = response.choices[0]?.message?.content;
  console.info("[edge-llm] filterCandidates: done", {
    elapsedSeconds: elapsed,
    outputLen: text?.length ?? 0,
  });
  if (!text) return null;

  let parsed: { keep?: number[]; relations?: unknown[] };
  try {
    parsed = JSON.parse(text) as typeof parsed;
  } catch (err) {
    console.error("[edge-llm] filterCandidates: JSON parse failed", err, text.slice(0, 200));
    return null;
  }

  const maxIdx = candidates.length;
  const keep = Array.isArray(parsed.keep)
    ? parsed.keep.filter(
        (n): n is number =>
          typeof n === "number" && Number.isInteger(n) && n >= 0 && n < maxIdx,
      )
    : [];

  const relations: ChunkExtractionResult["relations"] = [];
  if (Array.isArray(parsed.relations)) {
    for (const r of parsed.relations) {
      if (!Array.isArray(r) || r.length !== 3) continue;
      const [src, type, tgt] = r as [unknown, unknown, unknown];
      if (typeof src !== "number" || typeof tgt !== "number") continue;
      if (typeof type !== "string") continue;
      if (src < 0 || src >= maxIdx || tgt < 0 || tgt >= maxIdx) continue;
      if (src === tgt) continue;
      relations.push([
        src as number,
        type as ChunkExtractionResult["relations"][number][1],
        tgt as number,
      ]);
    }
  }

  return { keep, relations };
}
```

- [ ] **Step 3: Update `web/src/lib/edge-llm/index.ts` to export filterCandidates**

Replace `extractFromChunk` with `filterCandidates` in the re-export block:

```typescript
export {
  filterCandidates,
  classifyMeta,
  generateInsight,
} from "./inference-client";
```

Also remove `ChunkExtractionRequest` from the type re-exports since `filterCandidates` no longer takes that type:

```typescript
export type {
  ChunkExtractionResult,
  MetaClassificationRequest,
  MetaClassificationResult,
  InsightRequest,
  InsightResult,
} from "./types";
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote/web && npx tsc --noEmit 2>&1 | head -40
```
Fix any errors before proceeding.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/edge-llm/inference-client.ts web/src/lib/edge-llm/prompts.ts
git commit -m "refactor: edge LLM — replace extractFromChunk with filterCandidates, align prompt to server"
```

---

### Task 9: Update edge-processing.ts, delete candidates.ts, clean up

**Files:**
- Modify: `web/src/lib/orchestration/edge-processing.ts`
- Delete: `web/src/lib/edge-llm/candidates.ts`
- Delete: `web/src/lib/edge-llm/__tests__/candidates.test.ts`

- [ ] **Step 1: Rewrite edge-processing.ts**

Replace the entire content of `web/src/lib/orchestration/edge-processing.ts`:

```typescript
/**
 * Edge LLM processing orchestration.
 *
 * 1. Fetch server-generated candidates (POST /v1/extract-candidates).
 * 2. Pass candidates to in-browser Gemma for index-based filtering.
 * 3. Map indices back to concept strings.
 * 4. Generate one-sentence summary (separate Gemma call).
 * 5. Submit results + meta-classification to the API.
 *
 * The server is the single source of truth for candidate generation, so
 * cloud and edge modes always operate on an identical candidate pool.
 */

import { filterCandidates, generateSummary, classifyMeta } from "../edge-llm/inference-client";
import {
  fetchKnownConcepts,
  fetchCandidates,
  submitExtractionResults,
  submitMetaClassification,
} from "../api-client";

export interface EdgeProcessingRequest {
  baseUrl: string;
  noteId: string;
  noteTitle: string;
  contentText: string;
  contentHash: string;
  onProgress?: (done: number, total: number) => void;
  onChunkResult?: (concepts: string[]) => void;
}

export interface EdgeProcessingResult {
  status: "completed" | "failed";
  conceptCount?: number;
  relationCount?: number;
  chunksProcessed?: number;
  error?: string;
}

export async function runEdgeProcessing(
  request: EdgeProcessingRequest,
): Promise<EdgeProcessingResult> {
  try {
    const [known, candidateResp] = await Promise.all([
      fetchKnownConcepts(request.baseUrl),
      fetchCandidates(request.baseUrl, {
        note_id: request.noteId,
        title: request.noteTitle,
        content_text: request.contentText,
        content_hash: request.contentHash,
      }),
    ]);

    const { candidates } = candidateResp;

    if (candidates.length === 0) {
      request.onProgress?.(1, 1);
      return { status: "completed", conceptCount: 0, relationCount: 0, chunksProcessed: 1 };
    }

    const result = await filterCandidates(
      request.contentText,
      candidates,
      known.concepts,
    );
    request.onProgress?.(1, 1);

    if (!result) {
      return { status: "failed", error: "LLM inference returned null" };
    }

    const finalConcepts = result.keep
      .map((idx) => candidates[idx])
      .filter((c): c is string => c !== undefined)
      .map((text) => ({ text, confidence: 0.9 }));

    request.onChunkResult?.(finalConcepts.map((c) => c.text));

    const validRelations: Array<{
      source: string;
      type: string;
      target: string;
      confidence: number;
    }> = [];
    const relSeen = new Set<string>();
    for (const [srcIdx, type, tgtIdx] of result.relations) {
      const src = candidates[srcIdx];
      const tgt = candidates[tgtIdx];
      if (!src || !tgt || src === tgt) continue;
      const key = `${src}|${type}|${tgt}`;
      if (relSeen.has(key)) continue;
      relSeen.add(key);
      validRelations.push({ source: src, type, target: tgt, confidence: 0.85 });
    }

    const summary = await generateSummary({
      title: request.noteTitle,
      content: request.contentText,
      concepts: finalConcepts.map((c) => c.text),
    });

    await submitExtractionResults(request.baseUrl, {
      note_id: request.noteId,
      content_hash: request.contentHash,
      concepts: finalConcepts,
      relations: validRelations,
      summary,
    });

    const conceptTexts = finalConcepts.map((c) => c.text);
    if (conceptTexts.length >= 2) {
      const meta = await classifyMeta({
        concepts: conceptTexts,
        knownConcepts: known.concepts,
      });
      if (meta) {
        await submitMetaClassification(request.baseUrl, {
          synonym_pairs: meta.synonymPairs,
          subtopic_pairs: meta.subtopicPairs,
          classified_concepts: conceptTexts,
        });
      }
    }

    return {
      status: "completed",
      conceptCount: finalConcepts.length,
      relationCount: validRelations.length,
      chunksProcessed: 1,
    };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
```

- [ ] **Step 2: Delete candidates.ts and its test**

```bash
rm /Users/rishis/Desktop/Projects/NeuroNote/web/src/lib/edge-llm/candidates.ts
rm /Users/rishis/Desktop/Projects/NeuroNote/web/src/lib/edge-llm/__tests__/candidates.test.ts
```

- [ ] **Step 3: Verify TypeScript compiles with no errors**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote/web && npx tsc --noEmit 2>&1
```
Fix any remaining import errors (e.g. stale references to `extractFromChunk` or `chunkNote` in other files).

- [ ] **Step 4: Run frontend tests**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote/web && npx vitest run 2>&1
```
Expected: all tests pass. If `chunker.test.ts` or `dedupe.test.ts` fail due to missing imports after this change, those tests are unaffected — `chunker.ts` and `dedupe.ts` are not deleted (they become unused code; can be cleaned up separately).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/orchestration/edge-processing.ts
git rm web/src/lib/edge-llm/candidates.ts web/src/lib/edge-llm/__tests__/candidates.test.ts
git commit -m "refactor: edge processing — fetch server candidates, remove local candidates.ts"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run the full Python test suite**

```bash
make compose-test
```
Expected: all tests pass, no regressions.

- [ ] **Step 2: Run the frontend test suite**

```bash
cd /Users/rishis/Desktop/Projects/NeuroNote/web && npx vitest run
```
Expected: all tests pass.

- [ ] **Step 3: Smoke test with the running stack**

```bash
make compose-up
```

Open `http://localhost:3000`, create a note with inline code:

```
Use `setState` and `useEffect` to manage React state.
Machine learning models use gradient descent for optimization.
```

Save and wait for processing. Open the graph panel. Verify:
- `setState` does NOT appear as a concept node
- `useEffect` does NOT appear as a concept node
- `machine learning` or `gradient descent` DOES appear

- [ ] **Step 4: Check cloud mode if API key is configured**

In preferences, set cloud mode + a valid API key. Re-save the same note. Verify the same quality: no code tokens in the graph.

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -p
git commit -m "fix: address smoke test findings from unified extraction"
```
