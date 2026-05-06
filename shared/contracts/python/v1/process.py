from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "completed", "failed"]


class ProcessNoteRequest(BaseModel):
    note_id: str = Field(min_length=1)
    content_text: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class ProcessNoteResponse(BaseModel):
    job_id: str
    status: Literal["queued"]


class ExtractionSummary(BaseModel):
    """Counts of entities, relations, and keyphrases extracted from a note."""
    entity_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    keyphrase_count: int = Field(ge=0)
    top_entities: list[str] = Field(default_factory=list)


class ProcessStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    error: str | None = None
    extraction_summary: ExtractionSummary | None = None
