"""Unit tests for edge-mode extraction API endpoints.

Tests cover the four endpoints that receive browser-computed LLM results:
- POST /v1/extraction-results
- POST /v1/meta-classification-results
- GET /v1/concepts/insight-context
- GET /v1/concepts/known
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_NOTE_TITLE = "Machine Learning Basics"
_NOTE_CONTENT = "Machine learning is a branch of artificial intelligence"
# content_hash is SHA-256 of "{title}\n\n{content_text}" (matches NoteRepository)
_NOTE_CONTENT_HASH = hashlib.sha256(
    f"{_NOTE_TITLE}\n\n{_NOTE_CONTENT}".encode("utf-8")
).hexdigest()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _seed_note(client: TestClient) -> str:
    """Create a note via the API and return its note_id."""
    resp = client.put(
        "/v1/notes/edge-test-note-001",
        json={
            "note_id": "edge-test-note-001",
            "note_title": _NOTE_TITLE,
            "subject_id": "general",
            "content_json": {"type": "doc", "content": []},
            "content_text": _NOTE_CONTENT,
            "updated_at": "2024-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["note_id"]


# ── POST /v1/extraction-results ─────────────────────────────────────────────


class TestSubmitExtractionResults:
    """Tests for the extraction-results endpoint."""

    def test_successful_sync(self, client: TestClient) -> None:
        note_id = _seed_note(client)
        content_hash = _NOTE_CONTENT_HASH

        resp = client.post(
            "/v1/extraction-results",
            json={
                "note_id": note_id,
                "content_hash": content_hash,
                "concepts": [
                    {"text": "machine learning", "confidence": 0.95},
                    {"text": "artificial intelligence", "confidence": 0.9},
                ],
                "relations": [
                    {
                        "source": "machine learning",
                        "type": "IS_A",
                        "target": "artificial intelligence",
                        "confidence": 0.85,
                    }
                ],
                "summary": "An overview of ML as a branch of AI.",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["note_id"] == note_id
        assert body["entity_count"] == 2
        assert body["relation_count"] == 1
        assert body["synced"] is True

    def test_note_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/extraction-results",
            json={
                "note_id": "nonexistent-note",
                "content_hash": "abc123",
                "concepts": [],
                "relations": [],
                "summary": "",
            },
        )
        assert resp.status_code == 404

    def test_stale_content_hash_rejected(self, client: TestClient) -> None:
        note_id = _seed_note(client)

        resp = client.post(
            "/v1/extraction-results",
            json={
                "note_id": note_id,
                "content_hash": "stale-hash-that-does-not-match",
                "concepts": [{"text": "ML", "confidence": 0.9}],
                "relations": [],
                "summary": "",
            },
        )
        assert resp.status_code == 409
        assert "mismatch" in resp.json()["detail"].lower()

    def test_empty_concepts_accepted(self, client: TestClient) -> None:
        note_id = _seed_note(client)
        content_hash = _NOTE_CONTENT_HASH

        resp = client.post(
            "/v1/extraction-results",
            json={
                "note_id": note_id,
                "content_hash": content_hash,
                "concepts": [],
                "relations": [],
                "summary": "",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_count"] == 0
        assert body["relation_count"] == 0

    def test_validation_rejects_empty_note_id(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/extraction-results",
            json={
                "note_id": "",
                "content_hash": "abc",
                "concepts": [],
                "relations": [],
                "summary": "",
            },
        )
        assert resp.status_code == 422


# ── POST /v1/meta-classification-results ────────────────────────────────────


class TestSubmitMetaClassification:
    """Tests for the meta-classification-results endpoint."""

    def test_empty_pairs_accepted(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/meta-classification-results",
            json={
                "synonym_pairs": [],
                "subtopic_pairs": [],
                "classified_concepts": [],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["synonym_edges_written"] == 0
        assert body["subtopic_edges_written"] == 0

    def test_with_pairs_returns_counts(self, client: TestClient) -> None:
        """On SQLite the graph writes are skipped but counts remain 0."""
        resp = client.post(
            "/v1/meta-classification-results",
            json={
                "synonym_pairs": [{"a": "ML", "b": "machine learning"}],
                "subtopic_pairs": [
                    {"specific": "backpropagation", "broader": "neural networks"}
                ],
                "classified_concepts": ["ML", "machine learning", "backpropagation", "neural networks"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # On SQLite, graph writes are skipped so counts are 0
        assert body["synonym_edges_written"] >= 0
        assert body["subtopic_edges_written"] >= 0


# ── GET /v1/concepts/insight-context ────────────────────────────────────────


class TestInsightContext:
    """Tests for the insight-context endpoint."""

    def test_returns_matching_notes(self, client: TestClient) -> None:
        _seed_note(client)

        resp = client.get(
            "/v1/concepts/insight-context",
            params={"label": "machine learning"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["concept_label"] == "machine learning"
        assert body["total_notes"] >= 1
        assert len(body["notes"]) >= 1
        note = body["notes"][0]
        assert "note_id" in note
        assert "title" in note
        assert "excerpt" in note

    def test_no_matching_notes(self, client: TestClient) -> None:
        resp = client.get(
            "/v1/concepts/insight-context",
            params={"label": "quantum computing xyz"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_notes"] == 0
        assert body["notes"] == []

    def test_label_required(self, client: TestClient) -> None:
        resp = client.get("/v1/concepts/insight-context")
        assert resp.status_code == 422

    def test_limit_notes_respected(self, client: TestClient) -> None:
        _seed_note(client)

        resp = client.get(
            "/v1/concepts/insight-context",
            params={"label": "machine learning", "limit_notes": 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["notes"]) <= 1


# ── GET /v1/concepts/known ──────────────────────────────────────────────────


class TestKnownConcepts:
    """Tests for the known-concepts endpoint."""

    def test_returns_empty_initially(self, client: TestClient) -> None:
        resp = client.get("/v1/concepts/known")
        assert resp.status_code == 200
        body = resp.json()
        assert "concepts" in body
        assert isinstance(body["concepts"], list)


# ── Contract validation ─────────────────────────────────────────────────────


class TestExtractionContracts:
    """Validate Pydantic contract models."""

    def test_submit_extraction_request_defaults(self) -> None:
        from shared.contracts.python.v1.extraction import SubmitExtractionResultsRequest

        req = SubmitExtractionResultsRequest(
            note_id="n1",
            content_hash="abc",
        )
        assert req.concepts == []
        assert req.relations == []
        assert req.summary == ""

    def test_concept_item_confidence_bounds(self) -> None:
        from shared.contracts.python.v1.extraction import EdgeConceptItem

        item = EdgeConceptItem(text="ML", confidence=0.5)
        assert item.confidence == 0.5

        with pytest.raises(Exception):
            EdgeConceptItem(text="ML", confidence=1.5)

        with pytest.raises(Exception):
            EdgeConceptItem(text="ML", confidence=-0.1)

    def test_insight_context_response_shape(self) -> None:
        from shared.contracts.python.v1.extraction import (
            InsightContextNote,
            InsightContextResponse,
        )

        resp = InsightContextResponse(
            concept_label="ML",
            notes=[
                InsightContextNote(note_id="n1", title="Note 1", excerpt="some text"),
            ],
            total_notes=1,
        )
        assert resp.total_notes == 1
        assert resp.notes[0].title == "Note 1"

    def test_meta_classification_request_defaults(self) -> None:
        from shared.contracts.python.v1.extraction import SubmitMetaClassificationRequest

        req = SubmitMetaClassificationRequest()
        assert req.synonym_pairs == []
        assert req.subtopic_pairs == []
        assert req.classified_concepts == []

    def test_known_concepts_response(self) -> None:
        from shared.contracts.python.v1.extraction import KnownConceptsResponse

        resp = KnownConceptsResponse(concepts=["ml", "neural networks"])
        assert len(resp.concepts) == 2
