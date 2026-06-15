from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(slots=True)
class ExtractedEntity:
    entity_id: str
    text: str
    label: str
    confidence: float


@dataclass(slots=True)
class ExtractedRelation:
    subject_id: str
    subject_text: str
    predicate: str
    object_id: str
    object_text: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ConceptSurface:
    """A concept with both its in-document surface form and its canonical identity.

    The matcher uses ``surface`` against the document text (guaranteed
    to appear because the noun-chunker extracted it from there). Edges are
    emitted keyed by ``canonical`` so cross-note normalisation holds.
    """

    surface: str
    canonical: str


@dataclass(frozen=True, slots=True)
class StructureEdge:
    """A single structural edge between two concept slugs derived from block layout."""

    source: str
    target: str
    relation: str  # one of MENTIONED_TOGETHER | SUBTOPIC_OF | SIBLING_OF | REFERENCES | DEFINED_BY


@dataclass(frozen=True, slots=True)
class RelationDerivation:
    """Output of the structural relation derivation stage."""

    edges: list[StructureEdge]
    distinct_blocks_with_concepts: int


@dataclass(slots=True)
class BlockTextInput:
    block_index: int
    content_text: str


@dataclass(slots=True)
class NoteExtractionResult:
    note_id: str
    content_hash: str
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    embedding: list[float] | None
    distinct_blocks_with_concepts: int = 0  # populated by structure_relations stage; default keeps existing callers intact

    def with_note_id(self, note_id: str) -> "NoteExtractionResult":
        """Return a copy of this result with a different note_id (for cache hits)."""
        return dataclasses.replace(self, note_id=note_id)
