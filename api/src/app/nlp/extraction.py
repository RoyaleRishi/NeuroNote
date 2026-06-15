"""Deterministic concept-candidate extraction via spaCy noun chunks.

Generates grammatically complete noun-phrase candidates from note text using
spaCy's dependency-based noun-chunker (``en_core_web_sm``). This replaces the
``kbir-inspec`` token-classification model, which over-fired and emitted
overlapping sub-spans — the root cause of graph "density".

**All morphology and word-class decisions are delegated to spaCy** rather than
hand-rolled: leading function words are trimmed by ``token.is_stop`` (covers
determiners, pronouns, and low-content quantifiers like "other"/"such" while
keeping content modifiers like "deep"), and each candidate carries its
``token.lemma_`` form so downstream stages (subsumption, Hearst matching) compare
on lemmas instead of brittle plural-stripping rules. ``_clean`` is left with only
*non-linguistic* content filters (length, digits, camelCase, code tokens).

Candidates emitted here are *unranked*: the salience stage (``salience.py``)
scores them and the subsumption stage (``subsumption.py``) merges variants. No
LLM is involved. YAKE is an **optional, off-by-default** recall fallback routed
through the same spaCy-token cleaning so there is a single cleaning path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.nlp.spacy_model import get_nlp

_MIN_TEXT_LEN = 10
_YAKE_INVERTED_THRESHOLD = 0.85  # YAKE returns lower-is-better; keep (1-s) >= 0.85

# Quantifier-style leading modifiers that spaCy's stop list happens to omit.
# A *minimal* supplement to is_stop — not a hand-rolled morphology list.
_EXTRA_LEADING_STOP = frozenset({"certain"})

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?\)\]\}'\"\s]+$")
_CODE_TOKEN_RE = re.compile(r"[_$]")
_CAMEL_CASE_RE = re.compile(r"^[a-z]+[A-Z]")
_DIGIT_ONLY_RE = re.compile(r"^\d+$")


def _clean(raw: str) -> str | None:
    """Non-linguistic content filter (length / digits / camelCase / code tokens).

    Word-class filtering (determiners, stopwords) is handled at the token level
    via ``is_stop`` before this is ever called, so this stays purely structural.
    """
    text = _TRAILING_PUNCT_RE.sub("", raw.strip()).strip()
    if not text:
        return None
    if len(text) < 2 or len(text) > 60:
        return None
    if _DIGIT_ONLY_RE.match(text):
        return None
    if _CAMEL_CASE_RE.match(text):
        return None
    if _CODE_TOKEN_RE.search(text):
        return None
    return text


@dataclass(frozen=True, slots=True)
class ConceptSpan:
    text: str
    confidence: float
    source: Literal["noun_chunk", "statistical", "both"]
    lemma: str = ""  # spaCy-lemmatised form, used as the normalisation key


def prewarm() -> None:
    """Load the spaCy model singleton. Call at app startup."""
    get_nlp()


_yake_instance: Any = None


def _yake_extractor() -> Any:
    """Lazy-load YAKE extractor on first call (only used when fallback enabled)."""
    global _yake_instance
    if _yake_instance is None:
        import yake  # type: ignore[import-untyped]  # lazy: only for the opt-in fallback

        _yake_instance = yake.KeywordExtractor(lan="en", n=3, dedupLim=0.7, top=20)
    return _yake_instance


def extract_concepts(
    text: str,
    *,
    enable_yake_fallback: bool = False,
    yake_min_candidates: int = 3,
    doc: Any = None,
) -> list[ConceptSpan]:
    """Return unranked noun-phrase concept candidates from *text*.

    ``doc`` lets the caller pass an already-parsed spaCy ``Doc`` for *text* so the
    note isn't parsed twice in one pipeline run; when omitted it is parsed here.
    ``enable_yake_fallback`` adds YAKE statistical keyphrases **only** when the
    noun-chunker yields fewer than ``yake_min_candidates`` candidates. Off by
    default so the common case stays clean and low-density.
    """
    if len(text.strip()) < _MIN_TEXT_LEN:
        return []

    spans = _noun_chunk_candidates(doc if doc is not None else get_nlp()(text))
    if enable_yake_fallback and len(spans) < yake_min_candidates:
        return _merge(spans, _run_yake(text))
    return spans


def _candidate_from_span(span: Any, *, confidence: float, source: str) -> ConceptSpan | None:
    """Trim leading function words by ``is_stop``, capture the lemma, and clean.

    Returns ``None`` if nothing contentful remains. The single ``is_stop`` check
    replaces every hand-rolled determiner/stopword/low-content word list.
    """
    start = 0
    for token in span:
        if token.is_stop or token.is_punct or token.lower_ in _EXTRA_LEADING_STOP:
            start += 1
        else:
            break
    span = span[start:]
    if len(span) == 0 or all(t.is_stop or t.is_punct for t in span):
        return None

    cleaned = _clean(span.text)
    if cleaned is None:
        return None
    lemma = " ".join(t.lemma_.lower() for t in span)
    return ConceptSpan(text=cleaned, confidence=confidence, source=source, lemma=lemma)  # type: ignore[arg-type]


def _noun_chunk_candidates(doc: Any) -> list[ConceptSpan]:
    out: list[ConceptSpan] = []
    seen: set[str] = set()
    for chunk in doc.noun_chunks:
        # Confidence is a placeholder; the salience stage overwrites it with the
        # candidate's cosine similarity to the document.
        cand = _candidate_from_span(chunk, confidence=1.0, source="noun_chunk")
        if cand is None:
            continue
        key = cand.text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def _run_yake(text: str) -> list[ConceptSpan]:
    nlp = get_nlp()
    out: list[ConceptSpan] = []
    for phrase, score in _yake_extractor().extract_keywords(text):
        inverted = 1.0 - float(score)
        if inverted < _YAKE_INVERTED_THRESHOLD:
            continue
        # Route the YAKE phrase through the same spaCy-token cleaning path.
        cand = _candidate_from_span(nlp(phrase.strip())[:], confidence=inverted, source="statistical")
        if cand is not None:
            out.append(cand)
    return out


def _merge(a: list[ConceptSpan], b: list[ConceptSpan]) -> list[ConceptSpan]:
    """Dedup two candidate lists by surface, keeping the higher-confidence span."""
    by_key: dict[str, ConceptSpan] = {}
    for s in (*a, *b):
        key = s.text.lower()
        existing = by_key.get(key)
        if existing is None or s.confidence > existing.confidence:
            by_key[key] = s
    return list(by_key.values())
