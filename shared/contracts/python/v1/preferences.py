"""User preferences contracts."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    """All user preferences as a flat dict."""

    llm_mode: str = Field(default="edge", pattern="^(edge|cloud)$")
    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4o-mini")
    # Decoupled graph filters. node_salience gates which concepts appear (against
    # the normalized 0–1 salience); relationship_confidence gates concept→concept
    # edges (raw per-type edge confidence). Both are absolute, global 0–1 scales.
    node_salience_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    relationship_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # True when PREF_ENCRYPTION_KEY is set but the stored key can't be decrypted
    # (e.g. after key rotation).  UI should prompt the user to re-enter their key.
    llm_api_key_invalid: bool = Field(default=False)


class UpdatePreferencesRequest(BaseModel):
    """Partial update — only provided fields are written."""

    llm_mode: str | None = Field(default=None, pattern="^(edge|cloud)$")
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    node_salience_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    relationship_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class TestConnectionResponse(BaseModel):
    """Result of a test LLM connection attempt."""

    success: bool
    message: str
