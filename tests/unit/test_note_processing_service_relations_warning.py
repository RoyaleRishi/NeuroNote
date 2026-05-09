"""Health-metric: warn when relations=0 despite enough concepts/blocks."""
from __future__ import annotations

import logging

import pytest

from app.nlp.types import (
    ExtractedEntity,
    ExtractedRelation,
    NoteExtractionResult,
)
from app.services.note_processing_service import _maybe_log_zero_relations_warning


def _make_result(*, entities: int, relations: int, blocks: int) -> NoteExtractionResult:
    return NoteExtractionResult(
        note_id="note-1",
        content_hash="h1",
        entities=[
            ExtractedEntity(entity_id=f"c-{i}", text=f"c{i}", label="concept", confidence=0.9)
            for i in range(entities)
        ],
        keyphrases=[],
        relations=[
            ExtractedRelation(
                subject_id="c-0", subject_text="c0",
                predicate="MENTIONED_TOGETHER",
                object_id="c-1", object_text="c1",
                confidence=0.7,
            )
            for _ in range(relations)
        ],
        embedding=None,
        distinct_blocks_with_concepts=blocks,
    )


def test_warning_fires_when_zero_relations_with_enough_signal(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.note_processing_service")
    result = _make_result(entities=4, relations=0, blocks=3)
    _maybe_log_zero_relations_warning(result)
    assert any(
        "relation_count=0" in rec.message and "note-1" in rec.message
        for rec in caplog.records
    )


def test_warning_does_not_fire_when_legitimately_sparse(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.note_processing_service")
    result = _make_result(entities=1, relations=0, blocks=1)
    _maybe_log_zero_relations_warning(result)
    assert not [r for r in caplog.records if "relation_count=0" in r.message]


def test_warning_does_not_fire_when_relations_present(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.note_processing_service")
    result = _make_result(entities=4, relations=2, blocks=3)
    _maybe_log_zero_relations_warning(result)
    assert not [r for r in caplog.records if "relation_count=0" in r.message]
