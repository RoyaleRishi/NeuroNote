"""Auth contracts — user identity and session responses."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """Public-facing user profile returned by ``GET /v1/auth/me``."""

    id: str = Field(min_length=1)
    email: str = Field(min_length=1)
    display_name: str | None = None
    avatar_url: str | None = None
    oauth_provider: str = Field(min_length=1)
    schema_name: str = Field(min_length=1)
