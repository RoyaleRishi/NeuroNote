"""Shared contracts for edge-mode extraction endpoints.

These models define the request/response shapes for browser-side LLM results
submitted to the server for graph storage and embedding generation.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ── POST /v1/extraction-results ─────────────────────────────────────────────

class EdgeConceptItem(BaseModel):
    """A concept extracted by the browser's in-browser LLM."""
    text: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0, default=0.9)


class EdgeRelationItem(BaseModel):
    """A relation extracted by the browser's in-browser LLM."""
    source: str = Field(min_length=1, max_length=500)
    type: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class SubmitExtractionResultsRequest(BaseModel):
    """Browser submits pre-computed extraction results for graph sync."""
    note_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    concepts: list[EdgeConceptItem] = Field(default_factory=list)
    relations: list[EdgeRelationItem] = Field(default_factory=list)
    summary: str = Field(default="", max_length=5000)


class SubmitExtractionResultsResponse(BaseModel):
    """Confirmation of successful graph sync from browser extraction."""
    note_id: str
    entity_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    synced: bool = True


# ── POST /v1/meta-classification-results ────────────────────────────────────

class SynonymPair(BaseModel):
    a: str = Field(min_length=1)
    b: str = Field(min_length=1)


class SubtopicPair(BaseModel):
    specific: str = Field(min_length=1)
    broader: str = Field(min_length=1)


class SubmitMetaClassificationRequest(BaseModel):
    """Browser submits synonym/subtopic pairs from in-browser classification."""
    synonym_pairs: list[SynonymPair] = Field(default_factory=list)
    subtopic_pairs: list[SubtopicPair] = Field(default_factory=list)
    classified_concepts: list[str] = Field(default_factory=list)


class SubmitMetaClassificationResponse(BaseModel):
    """Confirmation of meta-classification edge writes."""
    synonym_edges_written: int = Field(ge=0)
    subtopic_edges_written: int = Field(ge=0)


# ── GET /v1/concepts/insight-context ────────────────────────────────────────

class InsightContextNote(BaseModel):
    """A note excerpt returned for browser-side insight generation."""
    note_id: str
    title: str
    excerpt: str


class InsightContextResponse(BaseModel):
    """Note context for the browser to generate insights locally."""
    concept_label: str
    notes: list[InsightContextNote] = Field(default_factory=list)
    total_notes: int = Field(ge=0)


# ── GET /v1/concepts/known ──────────────────────────────────────────────────

class KnownConceptsResponse(BaseModel):
    """List of concepts registered in the user's knowledge base."""
    concepts: list[str] = Field(default_factory=list)
