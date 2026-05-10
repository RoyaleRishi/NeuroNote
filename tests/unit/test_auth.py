"""Unit tests for core auth module and OAuth config."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt
import pytest

from app.core.auth import (
    ACCESS_COOKIE_NAME,
    JWT_ALGORITHM,
    UserContext,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.core.oauth_config import get_oauth_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_SECRET = "test-jwt-secret-for-unit-tests"


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure JWT_SECRET is available for every test."""
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


def test_create_access_token_produces_valid_jwt() -> None:
    token = create_access_token("uid-1", "a@b.com", "user_abc")
    claims = jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])

    assert claims["sub"] == "uid-1"
    assert claims["email"] == "a@b.com"
    assert claims["schema_name"] == "user_abc"
    assert claims["type"] == "access"
    assert "exp" in claims
    assert "iat" in claims


def test_create_access_token_expiry_is_15_minutes() -> None:
    token = create_access_token("uid-1", "a@b.com", "user_abc")
    claims = jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])
    # exp - iat should be 900 seconds (15 minutes)
    assert claims["exp"] - claims["iat"] == 900


# ---------------------------------------------------------------------------
# create_refresh_token
# ---------------------------------------------------------------------------


def test_create_refresh_token_produces_valid_jwt() -> None:
    token = create_refresh_token("uid-1")
    claims = jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])

    assert claims["sub"] == "uid-1"
    assert claims["type"] == "refresh"
    assert "exp" in claims
    assert "iat" in claims


def test_create_refresh_token_expiry_is_7_days() -> None:
    token = create_refresh_token("uid-1")
    claims = jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


# ---------------------------------------------------------------------------
# decode_token
# ---------------------------------------------------------------------------


def test_decode_token_succeeds_on_valid_token() -> None:
    token = create_access_token("uid-2", "x@y.com", "user_xyz")
    claims = decode_token(token)

    assert claims["sub"] == "uid-2"
    assert claims["email"] == "x@y.com"
    assert claims["schema_name"] == "user_xyz"


def test_decode_token_raises_on_expired_token() -> None:
    # Manually craft a token that expired 10 seconds ago.
    payload = {
        "sub": "uid-3",
        "email": "old@example.com",
        "schema_name": "user_old",
        "exp": int(time.time()) - 10,
        "iat": int(time.time()) - 1000,
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=JWT_ALGORITHM)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_decode_token_raises_on_tampered_token() -> None:
    token = create_access_token("uid-4", "t@t.com", "user_t")
    tampered = token + "XXXXX"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        decode_token(tampered)
    assert exc_info.value.status_code == 401


def test_decode_token_rejects_refresh_token_as_access() -> None:
    """A refresh token must not be accepted where an access token is expected."""
    token = create_refresh_token("uid-6")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        decode_token(token, expected_type="access")
    assert exc_info.value.status_code == 401
    assert "token type" in exc_info.value.detail.lower()


def test_decode_token_accepts_refresh_when_expected() -> None:
    token = create_refresh_token("uid-7")
    claims = decode_token(token, expected_type="refresh")
    assert claims["sub"] == "uid-7"
    assert claims["type"] == "refresh"


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


def test_get_current_user_extracts_user_context() -> None:
    token = create_access_token("uid-5", "me@me.com", "user_me")
    request = MagicMock()
    request.cookies = {ACCESS_COOKIE_NAME: token}

    ctx = get_current_user(request)

    assert isinstance(ctx, UserContext)
    assert ctx.user_id == "uid-5"
    assert ctx.email == "me@me.com"
    assert ctx.schema_name == "user_me"


def test_get_current_user_raises_401_when_cookie_missing() -> None:
    request = MagicMock()
    request.cookies = {}

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request)
    assert exc_info.value.status_code == 401
    assert "authentication" in exc_info.value.detail.lower()


def test_get_current_user_rejects_refresh_token() -> None:
    """Presenting a refresh token to get_current_user must return 401."""
    token = create_refresh_token("uid-8")
    request = MagicMock()
    request.cookies = {ACCESS_COOKIE_NAME: token}

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request)
    assert exc_info.value.status_code == 401


def test_get_current_user_rejects_malformed_access_token() -> None:
    """An access token missing required claims must return 401."""
    payload = {
        "sub": "uid-9",
        "type": "access",
        "exp": int(time.time()) + 900,
        "iat": int(time.time()),
        # email and schema_name intentionally missing
    }
    token = jwt.encode(payload, TEST_SECRET, algorithm=JWT_ALGORITHM)
    request = MagicMock()
    request.cookies = {ACCESS_COOKIE_NAME: token}

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request)
    assert exc_info.value.status_code == 401
    assert "malformed" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# OAuthSettings / get_oauth_settings
# ---------------------------------------------------------------------------


def test_oauth_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "g-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "g-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "gh-secret")
    monkeypatch.setenv("OAUTH_REDIRECT_BASE_URL", "https://example.com")

    settings = get_oauth_settings()

    assert settings.google_client_id == "g-id"
    assert settings.google_client_secret == "g-secret"
    assert settings.github_client_id == "gh-id"
    assert settings.github_client_secret == "gh-secret"
    assert settings.jwt_secret == TEST_SECRET
    assert settings.oauth_redirect_base_url == "https://example.com"


def test_oauth_settings_raises_when_jwt_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        get_oauth_settings()
