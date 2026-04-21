"""Unit tests for preferences API endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_get_preferences_returns_defaults(client: TestClient) -> None:
    resp = client.get("/v1/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_mode"] == "edge"
    assert body["llm_api_key"] == ""
    assert body["llm_base_url"] == "https://api.openai.com/v1"
    assert body["llm_model"] == "gpt-4o-mini"


def test_put_preferences_updates_and_returns(client: TestClient) -> None:
    resp = client.put(
        "/v1/preferences",
        json={"llm_mode": "cloud", "llm_model": "gpt-4o"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_mode"] == "cloud"
    assert body["llm_model"] == "gpt-4o"
    # Unchanged defaults
    assert body["llm_base_url"] == "https://api.openai.com/v1"


def test_put_preferences_masks_api_key(client: TestClient) -> None:
    client.put(
        "/v1/preferences",
        json={"llm_api_key": "sk-test-1234567890abcdef"},
    )
    resp = client.get("/v1/preferences")
    body = resp.json()
    assert body["llm_api_key"] == "****cdef"


def test_put_preferences_partial_update(client: TestClient) -> None:
    # Set model first
    client.put("/v1/preferences", json={"llm_model": "claude-haiku"})
    # Then set mode only
    client.put("/v1/preferences", json={"llm_mode": "cloud"})
    resp = client.get("/v1/preferences")
    body = resp.json()
    assert body["llm_mode"] == "cloud"
    assert body["llm_model"] == "claude-haiku"


def test_put_preferences_rejects_invalid_mode(client: TestClient) -> None:
    resp = client.put("/v1/preferences", json={"llm_mode": "invalid"})
    assert resp.status_code == 422
