from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedEntity:
    entity_id: str
    text: str
    label: str
    confidence: float


@dataclass(slots=True)
class ExtractedKeyphrase:
    phrase_id: str
    text: str
    score: float


@dataclass(slots=True)
class ExtractedRelation:
    subject_id: str
    subject_text: str
    predicate: str
    object_id: str
    object_text: str
    confidence: float


@dataclass(slots=True)
class ExtractedEntityMention:
    entity_id: str
    block_index: int
    mention_text: str
    start_offset: int
    end_offset: int
    confidence: float


@dataclass(slots=True)
class BlockTextInput:
    block_index: int
    content_text: str


@dataclass(slots=True)
class NoteExtractionResult:
    note_id: str
    content_hash: str
    entities: list[ExtractedEntity]
    keyphrases: list[ExtractedKeyphrase]
    relations: list[ExtractedRelation]
    embedding: list[float] | None
    entity_mentions: list[ExtractedEntityMention] = field(default_factory=list)
    summary: str = ""

    def with_note_id(self, note_id: str) -> "NoteExtractionResult":
        """Return a copy of this result with a different note_id (for cache hits)."""
        return dataclasses.replace(self, note_id=note_id)
