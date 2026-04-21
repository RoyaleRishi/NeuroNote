"""User preferences contracts."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    """All user preferences as a flat dict."""

    llm_mode: str = Field(default="edge", pattern="^(edge|cloud)$")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4o-mini")


class UpdatePreferencesRequest(BaseModel):
    """Partial update — only provided fields are written."""

    llm_mode: str | None = Field(default=None, pattern="^(edge|cloud)$")
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
