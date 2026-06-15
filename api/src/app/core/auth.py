"""Core auth module — JWT creation, validation, and FastAPI dependency."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, Request

# Token lifetimes
ACCESS_TOKEN_EXPIRY = timedelta(minutes=15)
REFRESH_TOKEN_EXPIRY = timedelta(days=7)

JWT_ALGORITHM = "HS256"
# Audience claim — prevents token reuse across services sharing the same secret.
JWT_AUDIENCE = "neuronote"

# Cookie names — shared constants to prevent mismatches.
ACCESS_COOKIE_NAME = "neuronote_access"
REFRESH_COOKIE_NAME = "neuronote_refresh"


@dataclass(frozen=True, slots=True)
class UserContext:
    """Authenticated user identity extracted from a valid access token."""

    user_id: str
    email: str
    schema_name: str


def _get_jwt_secret() -> str:
    """Return the JWT signing secret (delegated to OAuthSettings for single source of truth)."""
    from app.core.oauth_config import get_oauth_settings

    return get_oauth_settings().jwt_secret


def create_access_token(user_id: str, email: str, schema_name: str) -> str:
    """Create a short-lived access JWT with user identity claims."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "schema_name": schema_name,
        "type": "access",
        "aud": JWT_AUDIENCE,
        "exp": now + ACCESS_TOKEN_EXPIRY,
        "iat": now,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh JWT (no identity claims beyond subject)."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "aud": JWT_AUDIENCE,
        "exp": now + REFRESH_TOKEN_EXPIRY,
        "iat": now,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str, *, expected_type: str = "access") -> dict:
    """Decode and validate a JWT. Raises ``HTTPException(401)`` on failure.

    *expected_type* is checked against the ``type`` claim to prevent refresh
    tokens from being used where access tokens are expected (and vice versa).
    """
    try:
        # audience= enforces the aud claim; InvalidAudienceError (a subclass of
        # InvalidTokenError) is caught by the handler below → 401.
        claims = jwt.decode(
            token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if claims.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Invalid token type")

    return claims


def get_current_user(request: Request) -> UserContext:
    """FastAPI dependency — extract ``UserContext`` from the access token cookie.

    Usage::

        @router.get("/v1/protected")
        async def protected(user: UserContext = Depends(get_current_user)):
            ...
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    claims = decode_token(token, expected_type="access")
    try:
        return UserContext(
            user_id=claims["sub"],
            email=claims["email"],
            schema_name=claims["schema_name"],
        )
    except KeyError:
        raise HTTPException(status_code=401, detail="Malformed token")
