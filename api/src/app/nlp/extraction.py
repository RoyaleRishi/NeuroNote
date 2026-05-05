"""Deterministic concept extraction using a transformer + statistical ensemble.

The transformer (kbir-inspec) is high-precision on dense prose; YAKE supplies
recall on informal/list content. Combined output is deduped and cleaned before
returning. No LLM call is made here — this is the deterministic core that
runs identically in cloud and edge modes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import yake  # type: ignore[import-untyped]
from transformers import pipeline as hf_pipeline

_INSPEC_MODEL = "ml6team/keyphrase-extraction-kbir-inspec"
_INSPEC_THRESHOLD = 0.85
_YAKE_INVERTED_THRESHOLD = 0.85  # YAKE returns lower-is-better; we keep (1-s) >= 0.85

_pipeline_instance: Any = None
_yake_instance: yake.KeywordExtractor | None = None

_LEADING_DETERMINERS = ("the ", "a ", "an ", "this ", "that ", "these ", "those ")
_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?\)\]\}'\"\s]+$")
_CODE_TOKEN_RE = re.compile(r"[_$]")
_CAMEL_CASE_RE = re.compile(r"^[a-z]+[A-Z]")
_DIGIT_ONLY_RE = re.compile(r"^\d+$")
# Closed-class English words used to reject phrases that are entirely function words.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "him", "his", "i", "if", "in", "is", "it", "its", "may",
    "me", "might", "must", "my", "no", "not", "of", "on", "or", "our",
    "shall", "she", "should", "so", "such", "than", "that", "the", "their",
    "them", "they", "these", "this", "those", "to", "us", "was", "we",
    "were", "what", "when", "where", "which", "who", "whom", "why", "will",
    "with", "would", "you", "your", "etc",
})


def _clean(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    text = _TRAILING_PUNCT_RE.sub("", text).strip()
    if not text:
        return None
    # Strip leading determiners (case-insensitive on the determiner only).
    lower = text.lower()
    for det in _LEADING_DETERMINERS:
        if lower.startswith(det):
            text = text[len(det):]
            lower = text.lower()
            break
    if len(text) < 2 or len(text) > 60:
        return None
    if _DIGIT_ONLY_RE.match(text):
        return None
    if _CAMEL_CASE_RE.match(text):
        return None
    if _CODE_TOKEN_RE.search(text):
        return None
    tokens = lower.split()
    if not tokens or all(t in _STOPWORDS for t in tokens):
        return None
    return text


@dataclass(frozen=True, slots=True)
class ConceptSpan:
    text: str
    confidence: float
    source: Literal["transformer", "statistical", "both"]


def _load_inspec_pipeline() -> Any:
    """Load the kbir-inspec HF pipeline singleton without running inference."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = hf_pipeline(
            "token-classification",
            model=_INSPEC_MODEL,
            aggregation_strategy="simple",
        )
    return _pipeline_instance


def _inspec_pipeline(text: str) -> list[dict]:
    return _load_inspec_pipeline()(text)


def prewarm() -> None:
    """Load the transformer + YAKE singletons. Call at app startup."""
    _load_inspec_pipeline()
    _yake_extractor()


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
        cleaned = _clean(s.text)
        if cleaned is None:
            continue
        key = cleaned.lower()
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = ConceptSpan(text=cleaned, confidence=s.confidence, source=s.source)
        elif s.confidence > existing.confidence:
            by_key[key] = ConceptSpan(text=cleaned, confidence=s.confidence, source="both")
        else:
            by_key[key] = ConceptSpan(text=existing.text, confidence=existing.confidence, source="both")
    return list(by_key.values())
