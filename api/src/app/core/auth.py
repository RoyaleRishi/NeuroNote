"""Core auth module — JWT creation, validation, and FastAPI dependency."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, Request

# Token lifetimes
ACCESS_TOKEN_EXPIRY = timedelta(minutes=15)
REFRESH_TOKEN_EXPIRY = timedelta(days=7)

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class UserContext:
    """Authenticated user identity extracted from a valid access token."""

    user_id: str
    email: str
    schema_name: str


def _get_jwt_secret() -> str:
    """Read JWT_SECRET from environment. Raises if missing."""
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is required")
    return secret


def create_access_token(user_id: str, email: str, schema_name: str) -> str:
    """Create a short-lived access JWT with user identity claims."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "schema_name": schema_name,
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
        "exp": now + REFRESH_TOKEN_EXPIRY,
        "iat": now,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises ``HTTPException(401)`` on failure."""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request) -> UserContext:
    """FastAPI dependency — extract ``UserContext`` from the ``neuronote_access`` cookie.

    Usage::

        @router.get("/v1/protected")
        async def protected(user: UserContext = Depends(get_current_user)):
            ...
    """
    token = request.cookies.get("neuronote_access")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    claims = decode_token(token)
    return UserContext(
        user_id=claims["sub"],
        email=claims["email"],
        schema_name=claims["schema_name"],
    )
