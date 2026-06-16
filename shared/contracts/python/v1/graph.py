from __future__ import annotations

from pydantic import BaseModel, Field


class LocalGraphFilters(BaseModel):
    max_hops: int = Field(ge=1, le=2)
    limit_nodes: int = Field(ge=1, le=150)
    # Decoupled thresholds: node_salience gates which concepts appear (against the
    # normalized 0–1 salience); relationship_confidence gates concept→concept edges.
    node_salience_threshold: float = Field(ge=0.0, le=1.0)
    relationship_confidence_threshold: float = Field(ge=0.0, le=1.0)
    include_types: list[str] = Field(default_factory=list)


class LocalGraphNode(BaseModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    label: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_note_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class LocalGraphEdge(BaseModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    type: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_note_id: str | None = None


class LocalGraphMeta(BaseModel):
    root_note_id: str = Field(min_length=1)
    applied_filters: LocalGraphFilters
    truncated: bool = False


class LocalGraphResponse(BaseModel):
    nodes: list[LocalGraphNode]
    edges: list[LocalGraphEdge]
    meta: LocalGraphMeta


class GlobalGraphFilters(BaseModel):
    limit_nodes: int = Field(ge=1, le=2000)
    # Decoupled thresholds: node_salience gates which concepts appear (against the
    # normalized 0–1 salience); relationship_confidence gates concept→concept edges.
    node_salience_threshold: float = Field(ge=0.0, le=1.0)
    relationship_confidence_threshold: float = Field(ge=0.0, le=1.0)
    include_types: list[str] = Field(default_factory=list)
    subject_id: str | None = None
    tag: str | None = None


class GlobalGraphMeta(BaseModel):
    total_notes: int
    applied_filters: GlobalGraphFilters
    truncated: bool = False


class GlobalGraphResponse(BaseModel):
    nodes: list[LocalGraphNode]
    edges: list[LocalGraphEdge]
    meta: GlobalGraphMeta


class ConceptNoteRef(BaseModel):
    note_id: str
    note_title: str
    snippet: str


class ConceptLearningLink(BaseModel):
    title: str
    url: str
    description: str


class ConceptInsightResponse(BaseModel):
    concept_label: str
    notes_found: int
    note_refs: list[ConceptNoteRef]
    insight: str | None = None
    # Short, human-readable reason the insight could not be generated, or
    # ``None`` when generation succeeded or was not attempted.  The frontend
    # surfaces this verbatim instead of guessing the cause.
    insight_error: str | None = None
    learning_links: list[ConceptLearningLink] = Field(default_factory=list)
    generated_at: str


# ── Concept context endpoints (used by /concepts/insight-context and /concepts/known) ──

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


class KnownConceptsResponse(BaseModel):
    """List of concepts registered in the user's knowledge base."""
    concepts: list[str] = Field(default_factory=list)
