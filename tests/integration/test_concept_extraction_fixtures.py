"""Held-out regression fixtures for the deterministic concept extractor.

These fixtures exercise four distinct domains (CS prose, an academic
announcement, a bulleted goals list, and an opinion paragraph) so future
refactors get caught if they regress concept quality on real-world note
shapes. We deliberately avoid asserting any exact concept list — those
expectations would be brittle. The bar is "the extractor produces a
reasonable count of clean concepts on diverse inputs".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.nlp.extraction import _clean, extract_concepts

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "concept_extraction"
FIXTURE_FILES = (
    "variables.txt",
    "info_session.txt",
    "goals_2026.txt",
    "english_movies.txt",
)


@pytest.mark.integration
@pytest.mark.parametrize("fixture_name", FIXTURE_FILES)
def test_extract_concepts_quality_bar(fixture_name: str) -> None:
    text = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    spans = extract_concepts(text)

    assert len(spans) >= 5, (
        f"{fixture_name}: expected >=5 concept spans, got {len(spans)}"
    )

    for span in spans:
        # Every returned phrase must already pass the cleanup filter
        # (no leading determiners, no purely-stopword phrases, length 2-60).
        cleaned = _clean(span.text)
        assert cleaned is not None, (
            f"{fixture_name}: span {span.text!r} fails _clean"
        )
        assert cleaned == span.text, (
            f"{fixture_name}: span {span.text!r} not normalised "
            f"(would clean to {cleaned!r})"
        )
        assert 2 <= len(span.text) <= 60

    high_confidence = [s for s in spans if s.confidence >= 0.85]
    assert len(high_confidence) >= 2, (
        f"{fixture_name}: expected >=2 spans with confidence>=0.85, "
        f"got {len(high_confidence)}"
    )
