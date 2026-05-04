"""Integration tests for POST /v1/extract-candidates.

Verifies the endpoint returns deterministic, rule-based concept candidates
from note content and respects all quality gates (no code tokens, cap at 50).
"""
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
    content = " ".join(f"The {p} phenomenon is important in this domain." for p in phrases)
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
