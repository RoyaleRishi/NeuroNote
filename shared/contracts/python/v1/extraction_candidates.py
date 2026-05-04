"""Shared contracts for POST /v1/extract-candidates."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractCandidatesRequest(BaseModel):
    """Request for server-side deterministic candidate extraction."""

    note_id: str = Field(min_length=1)
    title: str = Field(default="")
    content_text: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class ExtractCandidatesResponse(BaseModel):
    """Deterministic concept candidates for LLM filtering."""

    candidates: list[str] = Field(default_factory=list)
    content_hash: str
