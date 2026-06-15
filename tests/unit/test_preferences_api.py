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
    import socket

    # Store an API key first.
    client.put("/v1/preferences", json={"llm_api_key": "sk-test-key-1234"})

    # The default llm_base_url (api.openai.com) may not resolve in the
    # container — monkeypatch so URL validation passes without real DNS.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.18.7.192", 0))
        ],
    )

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
    import socket

    client.put("/v1/preferences", json={"llm_api_key": "sk-test-key-1234"})

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.18.7.192", 0))
        ],
    )

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


def test_load_user_llm_config_returns_settings_for_cloud(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cloud mode with API key returns overridden NlpSettings."""
    import socket
    from app.routes.process import _load_user_llm_config

    # Make the test hermetic: api.example.com resolves to a public IP in this env.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.18.7.192", 0))
        ],
    )

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
    client: TestClient, db_session: "Session", monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cloud mode with API key returns overridden NlpSettings."""
    import socket
    from app.nlp.config import resolve_user_llm_settings as _resolve_llm_settings

    # The default llm_base_url (api.openai.com) may not resolve inside the
    # container — monkeypatch so the test is hermetic and doesn't need DNS.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("104.18.7.192", 0))
        ],
    )

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


# ── crypto-failure surfacing ────────────────────────────────────────────────


def test_load_preferences_sets_invalid_flag_on_bad_ciphertext(
    client: TestClient, db_session: "Session", monkeypatch: pytest.MonkeyPatch
) -> None:
    """When PREF_ENCRYPTION_KEY is set and stored ciphertext is invalid,
    _load_preferences must set llm_api_key_invalid=True and NOT leak the raw value."""
    from cryptography.fernet import Fernet
    from sqlalchemy import text as sa_text
    from app.routes.preferences import _load_preferences

    # Write a ciphertext that is valid Fernet-looking bytes but was encrypted
    # under a *different* key — so decryption will raise InvalidToken.
    other_key = Fernet.generate_key()
    bad_ciphertext = Fernet(other_key).encrypt(b"sk-secret").decode()

    db_session.execute(
        sa_text(
            "INSERT INTO user_preferences (key, value, updated_at) "
            "VALUES ('llm_api_key', :v, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = CURRENT_TIMESTAMP"
        ),
        {"v": bad_ciphertext},
    )
    db_session.commit()

    result = _load_preferences(db_session)

    # Key must be blank — not the raw ciphertext or plaintext.
    assert result["llm_api_key"] == "", "raw/plaintext key must not be exposed"
    # The invalid flag must be set so callers can surface an actionable error.
    assert result.get("llm_api_key_invalid") is True, "llm_api_key_invalid must be True"


def test_get_preferences_exposes_invalid_flag_in_response(
    client: TestClient, db_session: "Session", monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /v1/preferences must include llm_api_key_invalid=True when decryption fails."""
    from cryptography.fernet import Fernet
    from sqlalchemy import text as sa_text

    other_key = Fernet.generate_key()
    bad_ciphertext = Fernet(other_key).encrypt(b"sk-secret").decode()

    db_session.execute(
        sa_text(
            "INSERT INTO user_preferences (key, value, updated_at) "
            "VALUES ('llm_api_key', :v, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = CURRENT_TIMESTAMP"
        ),
        {"v": bad_ciphertext},
    )
    db_session.commit()

    resp = client.get("/v1/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_api_key_invalid"] is True
    assert body["llm_api_key"] == ""


def test_test_connection_returns_failure_on_bad_ciphertext(
    client: TestClient, db_session: "Session"
) -> None:
    """test-connection must return success=False (not crash) when the stored
    API key can't be decrypted, with a message telling the user to re-enter it."""
    from cryptography.fernet import Fernet
    from sqlalchemy import text as sa_text

    other_key = Fernet.generate_key()
    bad_ciphertext = Fernet(other_key).encrypt(b"sk-secret").decode()

    db_session.execute(
        sa_text(
            "INSERT INTO user_preferences (key, value, updated_at) "
            "VALUES ('llm_api_key', :v, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = CURRENT_TIMESTAMP"
        ),
        {"v": bad_ciphertext},
    )
    db_session.commit()

    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    # Message must guide the user to re-enter their key.
    assert "re-enter" in body["message"].lower() or "re-save" in body["message"].lower()


# ── SSRF: url validation in test-connection ─────────────────────────────────


def test_test_connection_rejects_private_base_url(
    client: TestClient, db_session: "Session", monkeypatch: pytest.MonkeyPatch
) -> None:
    """test-connection must return success=False for a private/loopback base URL."""
    import socket

    # Store a valid-looking API key and a private base URL.
    client.put(
        "/v1/preferences",
        json={
            "llm_api_key": "sk-test-key-1234",
            "llm_base_url": "https://169.254.169.254/v1",
        },
    )

    # Make the metadata IP resolve to itself (it already is an IP literal, but
    # monkeypatch anyway so the test is hermetic).
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))
        ],
    )

    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    # Message must mention the URL is invalid / not allowed.
    assert any(
        kw in body["message"].lower()
        for kw in ("private", "loopback", "reserved", "non-public", "unsafe", "invalid")
    )


def test_test_connection_rejects_http_base_url(
    client: TestClient,
) -> None:
    """test-connection must reject http:// base URLs (require https)."""
    client.put(
        "/v1/preferences",
        json={
            "llm_api_key": "sk-test-key-1234",
            "llm_base_url": "http://api.openai.com/v1",
        },
    )
    resp = client.post("/v1/preferences/test-connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "https" in body["message"].lower() or "invalid" in body["message"].lower()


# ── SSRF: url validation in resolve_user_llm_settings ────────────────────────


def test_resolve_llm_settings_skips_cloud_mode_on_private_url(
    client: TestClient, db_session: "Session", monkeypatch: pytest.MonkeyPatch
) -> None:
    """resolve_user_llm_settings must return None (fall back to env default)
    when the stored llm_base_url is a private/unsafe address."""
    import socket
    from app.nlp.config import resolve_user_llm_settings

    client.put(
        "/v1/preferences",
        json={
            "llm_mode": "cloud",
            "llm_api_key": "sk-cloud-key",
            "llm_base_url": "https://10.0.0.1/v1",
        },
    )

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))
        ],
    )

    result = resolve_user_llm_settings(db_session)
    assert result is None, "private base URL must cause fallback to None"
