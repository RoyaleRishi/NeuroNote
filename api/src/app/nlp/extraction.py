"""Deterministic concept extraction using a transformer + statistical ensemble.

The transformer (kbir-inspec) is high-precision on dense prose; YAKE supplies
recall on informal/list content. Combined output is deduped and cleaned before
returning. No LLM call is made here — this is the deterministic core that
runs identically in cloud and edge modes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import yake  # type: ignore[import-untyped]
from transformers import pipeline as hf_pipeline

_INSPEC_MODEL = "ml6team/keyphrase-extraction-kbir-inspec"
_INSPEC_THRESHOLD = 0.85
_YAKE_INVERTED_THRESHOLD = 0.85  # YAKE returns lower-is-better; we keep (1-s) >= 0.85

_pipeline_instance: Any = None
_yake_instance: yake.KeywordExtractor | None = None


@dataclass(frozen=True, slots=True)
class ConceptSpan:
    text: str
    confidence: float
    source: Literal["transformer", "statistical", "both"]


def _inspec_pipeline(text: str) -> list[dict]:
    """Lazy-load the kbir-inspec HF pipeline on first call, then run inference."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = hf_pipeline(
            "token-classification",
            model=_INSPEC_MODEL,
            aggregation_strategy="simple",
        )
    return _pipeline_instance(text)


def _yake_extractor() -> yake.KeywordExtractor:
    """Lazy-load YAKE extractor on first call."""
    global _yake_instance
    if _yake_instance is None:
        _yake_instance = yake.KeywordExtractor(lan="en", n=3, dedupLim=0.7, top=20)
    return _yake_instance


def extract_concepts(text: str) -> list[ConceptSpan]:
    if len(text.strip()) < 10:
        return []
    inspec_spans = _run_inspec(text)
    yake_spans = _run_yake(text)
    return _merge(inspec_spans, yake_spans)


def _run_inspec(text: str) -> list[ConceptSpan]:
    raw = _inspec_pipeline(text)
    out: list[ConceptSpan] = []
    for s in raw:
        score = float(s["score"])
        if score < _INSPEC_THRESHOLD:
            continue
        out.append(ConceptSpan(text=s["word"].strip(), confidence=score, source="transformer"))
    return out


def _run_yake(text: str) -> list[ConceptSpan]:
    raw = _yake_extractor().extract_keywords(text)
    out: list[ConceptSpan] = []
    for phrase, score in raw:
        inverted = 1.0 - float(score)
        if inverted < _YAKE_INVERTED_THRESHOLD:
            continue
        out.append(ConceptSpan(text=phrase.strip(), confidence=inverted, source="statistical"))
    return out


def _merge(a: list[ConceptSpan], b: list[ConceptSpan]) -> list[ConceptSpan]:
    by_key: dict[str, ConceptSpan] = {}
    for s in (*a, *b):
        key = s.text.lower()
        if not key:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = s
        elif s.confidence > existing.confidence:
            by_key[key] = ConceptSpan(text=s.text, confidence=s.confidence, source="both")
        else:
            by_key[key] = ConceptSpan(text=existing.text, confidence=existing.confidence, source="both")
    return list(by_key.values())
