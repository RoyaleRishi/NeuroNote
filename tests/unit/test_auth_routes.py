"""Unit tests for OAuth auth routes."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    create_access_token,
    create_refresh_token,
)
from app.db.models.user import User


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure JWT_SECRET is available for all tests in this module."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests")


@pytest.fixture(autouse=True)
def _reset_oauth_singleton() -> None:
    """Reset the lazy-initialised OAuth singleton between tests."""
    import app.routes.auth as auth_mod

    auth_mod._oauth = None
    yield
    auth_mod._oauth = None


# ---------------------------------------------------------------------------
# GET /v1/auth/me
# ---------------------------------------------------------------------------


@pytest.fixture()
def raw_client(configured_db: None) -> TestClient:
    """TestClient WITHOUT dependency overrides — auth routes need real JWT validation."""
    from app.main import app

    # Clear any overrides from the standard `client` fixture.
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    with TestClient(app) as tc:
        yield tc  # type: ignore[misc]
    app.dependency_overrides.update(saved)


def test_auth_me_with_valid_token(raw_client: TestClient, configured_db: None) -> None:
    """Authenticated request to /auth/me returns UserProfile from DB."""
    from app.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        user = User(
            id="u-123",
            email="test@example.com",
            display_name="Test User",
            avatar_url="https://example.com/avatar.png",
            oauth_provider="google",
            oauth_provider_id="g-123",
            schema_name="user_abc123def456",
        )
        session.add(user)
        session.commit()

    token = create_access_token(
        user_id="u-123", email="test@example.com", schema_name="user_abc123def456"
    )
    resp = raw_client.get("/v1/auth/me", cookies={ACCESS_COOKIE_NAME: token})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "u-123"
    assert body["email"] == "test@example.com"
    assert body["schema_name"] == "user_abc123def456"
    assert body["display_name"] == "Test User"
    assert body["oauth_provider"] == "google"


def test_auth_me_without_cookie(raw_client: TestClient) -> None:
    """Missing access cookie returns 401."""
    resp = raw_client.get("/v1/auth/me")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /v1/auth/logout
# ---------------------------------------------------------------------------


def test_auth_logout_clears_cookies(client: TestClient) -> None:
    """Logout endpoint returns 200 and clears auth cookies."""
    resp = client.post(
        "/v1/auth/logout",
        cookies={ACCESS_COOKIE_NAME: "old", REFRESH_COOKIE_NAME: "old"},
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Logged out"

    # Cookies should be cleared (set to empty / max-age=0).
    set_cookies = resp.headers.get_list("set-cookie")
    cookie_names = [c.split("=")[0] for c in set_cookies]
    assert ACCESS_COOKIE_NAME in cookie_names
    assert REFRESH_COOKIE_NAME in cookie_names


# ---------------------------------------------------------------------------
# POST /v1/auth/refresh
# ---------------------------------------------------------------------------


def test_auth_refresh_with_valid_token(client: TestClient, db_session: None) -> None:
    """Valid refresh token issues a new access token cookie."""
    from app.db.engine import get_session_factory

    # Seed a user in the DB.
    factory = get_session_factory()
    with factory() as session:
        user = User(
            id="u-refresh",
            email="refresh@example.com",
            oauth_provider="google",
            oauth_provider_id="g-refresh",
            schema_name="user_refresh12345",
        )
        session.add(user)
        session.commit()

    refresh = create_refresh_token(user_id="u-refresh")
    resp = client.post("/v1/auth/refresh", cookies={REFRESH_COOKIE_NAME: refresh})
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Token refreshed"

    # New access cookie should be set.
    set_cookies = resp.headers.get_list("set-cookie")
    access_cookies = [c for c in set_cookies if c.startswith(ACCESS_COOKIE_NAME)]
    assert len(access_cookies) == 1


def test_auth_refresh_without_cookie(client: TestClient) -> None:
    """Missing refresh cookie returns 401."""
    resp = client.post("/v1/auth/refresh")
    assert resp.status_code == 401


def test_auth_refresh_user_not_found(client: TestClient, db_session: None) -> None:
    """Refresh with a token for a non-existent user returns 401."""
    refresh = create_refresh_token(user_id="u-nonexistent")
    resp = client.post("/v1/auth/refresh", cookies={REFRESH_COOKIE_NAME: refresh})
    assert resp.status_code == 401
    assert "User not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Unsupported provider
# ---------------------------------------------------------------------------


def test_unsupported_provider_login(client: TestClient) -> None:
    """Login with an unsupported provider returns 400."""
    resp = client.get("/v1/auth/facebook/login")
    assert resp.status_code == 400
    assert "Unsupported provider" in resp.json()["detail"]


def test_unsupported_provider_callback(client: TestClient) -> None:
    """Callback with an unsupported provider returns 400."""
    resp = client.get("/v1/auth/facebook/callback")
    assert resp.status_code == 400
    assert "Unsupported provider" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Provider not configured
# ---------------------------------------------------------------------------


def test_provider_not_configured(client: TestClient) -> None:
    """Login with an unconfigured provider returns 400."""
    # By default in tests, GOOGLE_CLIENT_ID is not set -> empty string.
    resp = client.get("/v1/auth/google/login")
    assert resp.status_code == 400
    assert "Provider not configured" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Login redirect (mocked authlib)
# ---------------------------------------------------------------------------


def test_google_login_redirect(client: TestClient) -> None:
    """Configured Google provider triggers a redirect to Google's auth page."""
    mock_client = MagicMock()
    mock_client.authorize_redirect = AsyncMock(
        return_value=MagicMock(
            status_code=302,
            headers={"location": "https://accounts.google.com/o/oauth2/auth"},
        )
    )

    mock_oauth = MagicMock()
    mock_oauth.create_client.return_value = mock_client

    mock_settings = MagicMock()
    mock_settings.google_client_id = "test-google-id"
    mock_settings.oauth_redirect_base_url = "http://localhost:3000"

    with (
        patch("app.routes.auth._get_oauth", return_value=mock_oauth),
        patch("app.routes.auth.get_oauth_settings", return_value=mock_settings),
    ):
        client.get("/v1/auth/google/login", follow_redirects=False)

    mock_client.authorize_redirect.assert_called_once()


# ---------------------------------------------------------------------------
# H2 — Rate-limit markers on auth endpoints
# ---------------------------------------------------------------------------


def test_auth_endpoints_carry_rate_limit_marker() -> None:
    """dev_login, oauth_login, and oauth_callback must be registered in slowapi's route limits.

    Hammering for a 429 via TestClient is flaky because limiter state persists
    across tests and the in-memory store depends on the client IP key.  Instead
    we inspect ``limiter._route_limits`` — a dict keyed by ``module.funcname``
    that slowapi populates when ``@limiter.limit()`` is applied.  This is a
    stable structural assertion that the decorator was applied correctly.
    """
    from app.core.rate_limiter import limiter

    # Importing auth triggers registration of limits in the limiter.
    import app.routes.auth  # noqa: F401

    registered = limiter._route_limits
    for qualified_name in (
        "app.routes.auth.dev_login",
        "app.routes.auth.oauth_login",
        "app.routes.auth.oauth_callback",
    ):
        assert qualified_name in registered, (
            f"{qualified_name} must be registered in limiter._route_limits"
        )
        assert len(registered[qualified_name]) >= 1, (
            f"{qualified_name} has no rate-limit rules"
        )

    # Spot-check that dev_login carries a "10/minute" style limit string.
    dev_limit_strings = [str(rl.limit) for rl in registered["app.routes.auth.dev_login"]]
    assert any("10" in s for s in dev_limit_strings), (
        f"Expected '10/minute' limit on dev_login, got: {dev_limit_strings}"
    )
