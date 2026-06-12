"""Unit tests for preferences API endpoints."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


# ── test-connection endpoint ────────────────────────────────────────────────


def test_test_connection_no_api_key(client: TestClient) -> None:
    """Without an API key stored, test-connection returns failure."""
    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "No API key" in body["message"]


def test_test_connection_with_key_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the LLM client returns a response, test-connection succeeds."""
    # Store an API key first.
    client.put("/v1/preferences", json={"llm_api_key": "sk-test-key-1234"})

    # Patch AsyncLLMClient.complete to return a canned response.
    async def _fake_complete(self: object, **kwargs: object) -> str:
        return "Hello!"

    monkeypatch.setattr(
        "app.nlp.llm_client.AsyncLLMClient.complete", _fake_complete
    )
    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "successful" in body["message"].lower()


def test_test_connection_with_key_llm_returns_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the LLM returns None (e.g. bad model), test-connection returns failure."""
    client.put("/v1/preferences", json={"llm_api_key": "sk-test-key-1234"})

    async def _fake_complete_none(self: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "app.nlp.llm_client.AsyncLLMClient.complete", _fake_complete_none
    )
    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "no response" in body["message"].lower()


# ── _load_user_llm_config (process route helper) ───────────────────────────


def test_load_user_llm_config_returns_none_for_edge_mode(client: TestClient) -> None:
    """Edge mode (default) should return None — no override."""
    from app.routes.process import _load_user_llm_config

    # Default mode is 'edge', so config should be None.
    result = _load_user_llm_config("user_test0001")
    assert result is None


def test_load_user_llm_config_returns_settings_for_cloud(client: TestClient) -> None:
    """Cloud mode with API key returns overridden NlpSettings."""
    from app.routes.process import _load_user_llm_config

    client.put(
        "/v1/preferences",
        json={
            "llm_mode": "cloud",
            "llm_api_key": "sk-cloud-key-abc",
            "llm_base_url": "https://api.example.com/v1",
            "llm_model": "my-model",
        },
    )
    result = _load_user_llm_config("user_test0001")
    assert result is not None
    assert result.llm_api_key == "sk-cloud-key-abc"
    assert result.llm_base_url == "https://api.example.com/v1"
    assert result.llm_model == "my-model"


def test_load_user_llm_config_cloud_without_key_returns_none(
    client: TestClient,
) -> None:
    """Cloud mode without an API key falls back to None."""
    from app.routes.process import _load_user_llm_config

    client.put("/v1/preferences", json={"llm_mode": "cloud"})
    result = _load_user_llm_config("user_test0001")
    assert result is None


def test_load_user_llm_config_does_not_clobber_context_var(
    client: TestClient,
) -> None:
    """_load_user_llm_config must not alter the tenant-schema ContextVar.

    Before the fix, the function reset the ContextVar to None in its finally
    block. This broke mark_job_running/mark_job_completed calls in
    _run_processing_job that rely on the ContextVar after this helper returns.
    """
    from app.db.engine import get_tenant_schema, set_tenant_schema
    from app.routes.process import _load_user_llm_config

    set_tenant_schema("user_test0001")
    try:
        result = _load_user_llm_config("user_test0001")
        assert result is None  # edge mode (default) returns None
        assert get_tenant_schema() == "user_test0001", (
            "_load_user_llm_config must not reset the tenant-schema ContextVar"
        )
    finally:
        set_tenant_schema(None)  # always clean up so other tests are unaffected


# ── resolve_user_llm_settings (shared resolver in app/nlp/config) ───────────


def test_resolve_llm_settings_edge_mode(db_session: "Session") -> None:
    """Edge mode returns None."""
    from app.nlp.config import resolve_user_llm_settings as _resolve_llm_settings

    result = _resolve_llm_settings(db_session)
    assert result is None


def test_resolve_llm_settings_cloud_mode(
    client: TestClient, db_session: "Session"
) -> None:
    """Cloud mode with API key returns overridden NlpSettings."""
    from app.nlp.config import resolve_user_llm_settings as _resolve_llm_settings

    client.put(
        "/v1/preferences",
        json={
            "llm_mode": "cloud",
            "llm_api_key": "sk-insight-key",
            "llm_model": "insight-model",
        },
    )
    result = _resolve_llm_settings(db_session)
    assert result is not None
    assert result.llm_api_key == "sk-insight-key"
    assert result.llm_model == "insight-model"


# ── encryption at rest ──────────────────────────────────────────────────────


def test_put_preferences_api_key_is_encrypted_in_db(
    client: TestClient, db_session: "Session"
) -> None:
    """Raw DB value after PUT must differ from the plaintext key (i.e. encrypted)."""
    from sqlalchemy import text as sa_text

    client.put("/v1/preferences", json={"llm_api_key": "sk-real-key-abc123"})
    row = db_session.execute(
        sa_text("SELECT value FROM user_preferences WHERE key = 'llm_api_key'")
    ).first()
    assert row is not None
    assert row[0] != "sk-real-key-abc123"


def test_put_preferences_api_key_round_trips(
    client: TestClient, db_session: "Session"
) -> None:
    """PUT an API key; _load_preferences must return the decrypted plaintext."""
    from app.routes.preferences import _load_preferences

    client.put("/v1/preferences", json={"llm_api_key": "sk-real-key-abc123"})
    prefs = _load_preferences(db_session)
    assert prefs["llm_api_key"] == "sk-real-key-abc123"
