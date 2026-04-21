"""OAuth provider configuration — reads credentials from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OAuthSettings:
    """OAuth provider credentials and JWT signing secret.

    Only ``jwt_secret`` is mandatory. Provider fields may be empty strings,
    meaning that provider is disabled.
    """

    google_client_id: str
    google_client_secret: str
    github_client_id: str
    github_client_secret: str
    jwt_secret: str
    oauth_redirect_base_url: str
    frontend_url: str


def get_oauth_settings() -> OAuthSettings:
    """Build ``OAuthSettings`` from environment variables.

    Raises ``RuntimeError`` if ``JWT_SECRET`` is missing or blank.
    """
    jwt_secret = os.getenv("JWT_SECRET", "").strip()
    if not jwt_secret:
        raise RuntimeError(
            "JWT_SECRET environment variable is required. "
            "Generate one with: openssl rand -hex 32"
        )

    return OAuthSettings(
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        github_client_id=os.getenv("GITHUB_CLIENT_ID", ""),
        github_client_secret=os.getenv("GITHUB_CLIENT_SECRET", ""),
        jwt_secret=jwt_secret,
        oauth_redirect_base_url=os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000"),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:3000"),
    )
