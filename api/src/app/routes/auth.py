"""OAuth authentication routes — login, callback, me, logout, refresh."""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime

import httpx
from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    UserContext,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.core.oauth_config import OAuthSettings, get_oauth_settings
from app.db.models.user import User
from app.db.session import get_db_session
from app.db.tenant import create_user_schema
from shared.contracts.python.v1.auth import UserProfile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# Supported OAuth providers.
_SUPPORTED_PROVIDERS = {"google", "github"}

# Lazy-initialised authlib OAuth instance — built once on first request.
_oauth: OAuth | None = None
_oauth_lock = threading.Lock()


def _get_oauth() -> OAuth:
    """Return the singleton authlib OAuth instance, registering providers."""
    global _oauth  # noqa: PLW0603
    if _oauth is not None:
        return _oauth

    with _oauth_lock:
        if _oauth is not None:
            return _oauth

        settings = get_oauth_settings()
        oauth = OAuth()

        if settings.google_client_id:
            oauth.register(
                name="google",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )

        if settings.github_client_id:
            oauth.register(
                name="github",
                client_id=settings.github_client_id,
                client_secret=settings.github_client_secret,
                authorize_url="https://github.com/login/oauth/authorize",
                access_token_url="https://github.com/login/oauth/access_token",
                api_base_url="https://api.github.com/",
                client_kwargs={"scope": "read:user user:email"},
            )

        _oauth = oauth
        return _oauth


def _is_secure_env() -> bool:
    """True when OAUTH_REDIRECT_BASE_URL starts with https."""
    import os
    url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    return url.startswith("https")


def _set_auth_cookies(response: RedirectResponse | JSONResponse, access: str, refresh: str) -> None:
    """Set httpOnly auth cookies. ``secure`` flag is on in production (HTTPS) only."""
    secure = _is_secure_env()
    for name, value in ((ACCESS_COOKIE_NAME, access), (REFRESH_COOKIE_NAME, refresh)):
        response.set_cookie(
            key=name,
            value=value,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )


def _clear_auth_cookies(response: JSONResponse) -> None:
    """Delete auth cookies (flags must match _set_auth_cookies)."""
    secure = _is_secure_env()
    for name in (ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME):
        response.delete_cookie(
            key=name, path="/", httponly=True, secure=secure, samesite="lax"
        )


def _is_dev_mode() -> bool:
    """Dev mode: no OAuth providers configured."""
    settings = get_oauth_settings()
    return not settings.google_client_id and not settings.github_client_id


# ---------------------------------------------------------------------------
# Dev login (no OAuth providers configured)
# ---------------------------------------------------------------------------

@router.post("/auth/dev/login")
def dev_login(
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    """Auto-create a dev user and issue tokens. Only when no providers are configured."""
    if not _is_dev_mode():
        raise HTTPException(status_code=403, detail="Dev login disabled in production")

    user = session.query(User).filter(User.email == "dev@neuronote.local").first()
    if user is None:
        schema_name = f"user_{uuid.uuid4().hex[:12]}"
        user = User(
            email="dev@neuronote.local",
            display_name="Dev User",
            oauth_provider="dev",
            oauth_provider_id="dev-local",
            schema_name=schema_name,
        )
        session.add(user)
        session.flush()
        create_user_schema(session, schema_name)

        _url = str(session.get_bind().url)  # type: ignore[union-attr]
        if _url.startswith("postgresql"):
            session.execute(text(f"SET search_path TO {schema_name}, public"))
            session.execute(
                text(
                    "INSERT INTO subjects (id, name, created_at, updated_at) "
                    "VALUES (:id, :name, NOW(), NOW()) ON CONFLICT DO NOTHING"
                ),
                {"id": "inbox", "name": "Inbox"},
            )
            session.execute(text("SET search_path TO public"))
        session.commit()
        logger.info("Dev user created: %s", schema_name)
    else:
        user.last_login_at = datetime.now(UTC)
        session.commit()

    access = create_access_token(user.id, user.email, user.schema_name)
    refresh = create_refresh_token(user.id)
    response = JSONResponse(content={"detail": "Dev login successful", "email": user.email})
    _set_auth_cookies(response, access, refresh)
    return response


@router.get("/auth/dev/status")
def dev_status() -> dict:
    """Check if dev mode is active (no OAuth providers configured)."""
    return {"dev_mode": _is_dev_mode()}


# ---------------------------------------------------------------------------
# GET /auth/{provider}/login
# ---------------------------------------------------------------------------

@router.get("/auth/{provider}/login")
async def oauth_login(provider: str, request: Request) -> RedirectResponse:
    """Redirect the user to the OAuth provider's authorization page."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    settings = get_oauth_settings()
    _assert_provider_configured(provider, settings)

    oauth = _get_oauth()
    client = oauth.create_client(provider)
    callback_url = (
        f"{settings.oauth_redirect_base_url}/v1/auth/{provider}/callback"
    )
    return await client.authorize_redirect(request, callback_url)


def _assert_provider_configured(provider: str, settings: OAuthSettings) -> None:
    """Raise 400 if the provider's client_id is not set."""
    if provider == "google" and not settings.google_client_id:
        raise HTTPException(status_code=400, detail="Provider not configured")
    if provider == "github" and not settings.github_client_id:
        raise HTTPException(status_code=400, detail="Provider not configured")


# ---------------------------------------------------------------------------
# GET /auth/{provider}/callback
# ---------------------------------------------------------------------------

@router.get("/auth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    """Handle the OAuth callback — upsert user, set cookies, redirect to /."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    oauth = _get_oauth()
    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)

    # Extract user profile from provider.
    email, display_name, avatar_url, oauth_provider_id = await _extract_profile(
        provider, token
    )

    if not email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from provider")

    # Upsert user in public.users.
    user = _upsert_user(
        session,
        provider=provider,
        oauth_provider_id=str(oauth_provider_id),
        email=email,
        display_name=display_name,
        avatar_url=avatar_url,
    )

    # Generate JWT tokens.
    access = create_access_token(user.id, user.email, user.schema_name)
    refresh = create_refresh_token(user.id)

    frontend_url = get_oauth_settings().frontend_url
    response = RedirectResponse(url=frontend_url, status_code=302)
    _set_auth_cookies(response, access, refresh)
    return response


async def _extract_profile(
    provider: str, token: dict
) -> tuple[str | None, str | None, str | None, str]:
    """Return (email, display_name, avatar_url, oauth_provider_id) from token."""
    if provider == "google":
        userinfo = token.get("userinfo", {})
        return (
            userinfo.get("email"),
            userinfo.get("name"),
            userinfo.get("picture"),
            userinfo.get("sub", ""),
        )

    return await _fetch_github_profile(token)


async def _fetch_github_profile(
    token: dict,
) -> tuple[str | None, str | None, str | None, str]:
    """Fetch GitHub user profile and primary email via async API calls."""
    access_token = token.get("access_token", "")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.github.com/user", headers=headers)
            resp.raise_for_status()
            data = resp.json()

            email = data.get("email")
            display_name = data.get("name") or data.get("login")
            avatar_url = data.get("avatar_url")
            oauth_provider_id = str(data.get("id", ""))

            # If email is not public, fetch from /user/emails endpoint.
            if not email:
                emails_resp = await client.get(
                    "https://api.github.com/user/emails", headers=headers
                )
                emails_resp.raise_for_status()
                for entry in emails_resp.json():
                    if entry.get("primary"):
                        email = entry.get("email")
                        break
    except httpx.HTTPError as exc:
        logger.warning("GitHub API error: %s", exc)
        raise HTTPException(status_code=502, detail="GitHub API unavailable")

    return email, display_name, avatar_url, oauth_provider_id


def _upsert_user(
    session: Session,
    *,
    provider: str,
    oauth_provider_id: str,
    email: str,
    display_name: str | None,
    avatar_url: str | None,
) -> User:
    """Insert new user or update returning user. Returns the User row."""
    user = (
        session.query(User)
        .filter(
            User.oauth_provider == provider,
            User.oauth_provider_id == oauth_provider_id,
        )
        .first()
    )

    if user is not None:
        # Returning user — update mutable fields.
        user.last_login_at = datetime.now(UTC)
        user.email = email
        user.display_name = display_name
        user.avatar_url = avatar_url
        session.commit()
        logger.info("Returning user login: %s (%s)", email, provider)
        return user

    # New user — provision tenant schema.
    schema_name = f"user_{uuid.uuid4().hex[:12]}"
    user = User(
        email=email,
        display_name=display_name,
        avatar_url=avatar_url,
        oauth_provider=provider,
        oauth_provider_id=oauth_provider_id,
        schema_name=schema_name,
    )
    session.add(user)
    session.flush()  # Assign PK before schema provisioning.

    create_user_schema(session, schema_name)

    # Create default "Inbox" subject in the new user's schema.
    _url = str(session.get_bind().url)  # type: ignore[union-attr]
    if _url.startswith("postgresql"):
        session.execute(text(f"SET search_path TO {schema_name}, public"))
        session.execute(
            text(
                "INSERT INTO subjects (id, name, created_at, updated_at) "
                "VALUES (:id, :name, NOW(), NOW()) ON CONFLICT DO NOTHING"
            ),
            {"id": "inbox", "name": "Inbox"},
        )
        # Reset search_path back to public for the auth route context.
        session.execute(text("SET search_path TO public"))

    session.commit()
    logger.info("New user registered: %s (%s) -> %s", email, provider, schema_name)
    return user


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/auth/me")
def auth_me(
    user: UserContext = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserProfile:
    """Return the authenticated user's full profile from the database."""
    db_user = session.query(User).filter(User.id == user.user_id).first()
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found")

    return UserProfile(
        id=db_user.id,
        email=db_user.email,
        display_name=db_user.display_name,
        avatar_url=db_user.avatar_url,
        oauth_provider=db_user.oauth_provider,
        schema_name=db_user.schema_name,
    )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/auth/logout")
def auth_logout() -> JSONResponse:
    """Clear auth cookies and return 200."""
    response = JSONResponse(content={"detail": "Logged out"})
    _clear_auth_cookies(response)
    return response


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/auth/refresh")
def auth_refresh(
    request: Request,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    """Issue a new access token from a valid refresh token."""
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    claims = decode_token(refresh_token, expected_type="refresh")
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Look up current user state (email/schema_name may have changed).
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access = create_access_token(user.id, user.email, user.schema_name)
    response = JSONResponse(content={"detail": "Token refreshed"})
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access,
        httponly=True,
        secure=_is_secure_env(),
        samesite="lax",
        path="/",
    )
    return response
