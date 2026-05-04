from __future__ import annotations

from dataclasses import dataclass
import re
from typing import cast

from app.nlp.extractors import EntityCandidateExtractor, EntityExtractionMetrics
from app.nlp.types import BlockTextInput, ExtractedEntity, ExtractedEntityMention

_TITLE_CASE_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b")
_ACRONYM_PATTERN = re.compile(r"\b[A-Z]{2,10}\b")
_LOWERCASE_TOKEN_PATTERN = re.compile(r"\b[a-z][a-z0-9]+")

_DICTIONARY_CONFIDENCE = 0.93
_SPACY_CONFIDENCE = 0.9
_TITLE_CASE_CONFIDENCE = 0.85
_ACRONYM_CONFIDENCE = 0.75
_LOWERCASE_DOMAIN_CONFIDENCE = 0.68
_LOWERCASE_SINGLE_TOKEN_CONFIDENCE = 0.64

_STOPWORDS = {
    "about",
    "across",
    "after",
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "before",
    "between",
    "be",
    "by",
    "during",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "over",
    "per",
    "that",
    "the",
    "these",
    "this",
    "those",
    "through",
    "than",
    "then",
    "note",
    "notes",
    "to",
    "under",
    "until",
    "via",
    "with",
    "within",
    "without",
}

_LOWERCASE_NOISE_TOKENS = {
    "hello",
    "thanks",
    "thank",
    "hi",
}

_LOWERCASE_VERB_TOKENS = {
    "analyzes",
    "builds",
    "connects",
    "explore",
    "explores",
    "drives",
    "enables",
    "helps",
    "discusses",
    "describes",
    "improves",
    "links",
    "predicts",
    "sees",
    "supports",
    "use",
    "uses",
    "using",
    "works",
    "working",
}

_CODE_KEYWORDS = frozenset({
    "var", "let", "const", "return", "import", "export",
    "function", "async", "await", "null", "true", "false",
    "undefined", "enum",
})

_CAMEL_CASE_RE = re.compile(r"^[a-z]+[A-Z]")
_CODE_TOKEN_RE = re.compile(r"[_$]")
_DIGIT_ONLY_RE = re.compile(r"^\d+$")


def _passes_quality_gate(text: str) -> bool:
    """Return True if the candidate is a valid concept (not a code token or noise)."""
    n = len(text)
    if n < 2:
        return False
    if n > 80:
        return False
    if n == 2 and not text.isupper():
        return False
    if _DIGIT_ONLY_RE.match(text):
        return False
    if _CAMEL_CASE_RE.match(text):
        return False
    if _CODE_TOKEN_RE.search(text):
        return False
    if text.lower() in _CODE_KEYWORDS:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _SpanCandidate:
    text: str
    label: str
    source_layer: str
    source_priority: int
    confidence: float
    start_offset: int
    end_offset: int


def _slugify(raw_text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", raw_text.lower()).strip("-")
    return normalized or "entity"


def _normalize_term(term: str) -> str:
    return " ".join(term.strip().split())


def _normalize_terms(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for raw_term in group:
            term = _normalize_term(raw_term)
            if len(term) < 2:
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(term)
    return ordered


def _dictionary_candidates(block_text: str, dictionary_terms: list[str]) -> list[_SpanCandidate]:
    candidates: list[_SpanCandidate] = []
    for term in _normalize_terms(dictionary_terms):
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags=re.IGNORECASE)
        for match in pattern.finditer(block_text):
            candidates.append(
                _SpanCandidate(
                    text=match.group(0),
                    label="dictionary",
                    source_layer="dictionary",
                    source_priority=0,
                    confidence=_DICTIONARY_CONFIDENCE,
                    start_offset=match.start(),
                    end_offset=match.end(),
                )
            )
    return candidates


def _ensure_entity_ruler_patterns(
    *,
    model_handle: object,
    terms: list[str],
) -> None:
    if not hasattr(model_handle, "add_pipe") or not hasattr(model_handle, "get_pipe"):
        return

    pipe_names = list(getattr(model_handle, "pipe_names", []))
    if "entity_ruler" not in pipe_names:
        try:
            if "ner" in pipe_names:
                model_handle.add_pipe("entity_ruler", before="ner")
            else:
                model_handle.add_pipe("entity_ruler")
        except Exception:
            return

    try:
        ruler = model_handle.get_pipe("entity_ruler")
    except Exception:
        return
    if not hasattr(ruler, "add_patterns"):
        return

    applied_terms = set(getattr(model_handle, "_neuronote_ruler_terms", set()))
    pending_terms = [term for term in terms if term.lower() not in applied_terms]
    if not pending_terms:
        return

    patterns = [{"label": "DOMAIN_TERM", "pattern": term} for term in pending_terms]
    try:
        ruler.add_patterns(patterns)
    except Exception:
        return
    setattr(
        model_handle,
        "_neuronote_ruler_terms",
        applied_terms.union({term.lower() for term in pending_terms}),
    )


def _spacy_candidates(
    *,
    block_text: str,
    model_handle: object | None,
    dictionary_terms: list[str],
    seed_terms: list[str],
) -> list[_SpanCandidate]:
    if model_handle is None or not callable(model_handle):
        return []

    _ensure_entity_ruler_patterns(
        model_handle=model_handle,
        terms=_normalize_terms(dictionary_terms, seed_terms),
    )

    try:
        doc = model_handle(block_text)
    except Exception:
        return []

    raw_ents = list(getattr(doc, "ents", []))
    candidates: list[_SpanCandidate] = []
    for entity in raw_ents:
        text = _normalize_term(str(getattr(entity, "text", "")))
        if len(text) < 2:
            continue
        start_offset = int(getattr(entity, "start_char", -1))
        end_offset = int(getattr(entity, "end_char", -1))
        if start_offset < 0 or end_offset <= start_offset:
            continue
        label = str(getattr(entity, "label_", "spacy"))
        candidates.append(
            _SpanCandidate(
                text=text,
                label=label.lower(),
                source_layer="spacy",
                source_priority=1,
                confidence=_SPACY_CONFIDENCE,
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
    return candidates


def _is_lowercase_domain_phrase(phrase: str) -> bool:
    tokens = [token for token in phrase.split() if token]
    if len(tokens) < 2:
        return False
    if any(token in _STOPWORDS for token in tokens):
        return False
    if any(token in _LOWERCASE_NOISE_TOKENS for token in tokens):
        return False
    if any(token in _LOWERCASE_VERB_TOKENS for token in tokens):
        return False
    if not all(len(token) >= 3 for token in tokens):
        return False
    return True


def _lowercase_ngram_candidates(block_text: str) -> list[_SpanCandidate]:
    tokens = [
        (match.group(0).lower(), match.start(), match.end())
        for match in _LOWERCASE_TOKEN_PATTERN.finditer(block_text)
    ]
    if len(tokens) < 2:
        return []

    candidates: list[_SpanCandidate] = []
    seen_spans: set[tuple[int, int]] = set()
    for size in (2,):
        for start_index in range(0, len(tokens) - size + 1):
            window = tokens[start_index : start_index + size]
            contiguous = True
            for left, right in zip(window, window[1:]):
                separator = block_text[left[2] : right[1]]
                if separator.strip():
                    contiguous = False
                    break
            if not contiguous:
                continue

            phrase_tokens = [item[0] for item in window]
            phrase = " ".join(phrase_tokens)
            if not _is_lowercase_domain_phrase(phrase):
                continue

            span = (window[0][1], window[-1][2])
            if span in seen_spans:
                continue
            seen_spans.add(span)
            candidates.append(
                _SpanCandidate(
                    text=block_text[span[0] : span[1]],
                    label="domain_phrase",
                    source_layer="regex",
                    source_priority=2,
                    confidence=_LOWERCASE_DOMAIN_CONFIDENCE,
                    start_offset=span[0],
                    end_offset=span[1],
                )
            )
    return candidates


def _fallback_candidates(block_text: str) -> list[_SpanCandidate]:
    candidates: list[_SpanCandidate] = []
    for match in _TITLE_CASE_PATTERN.finditer(block_text):
        if match.group(0).lower() in _STOPWORDS:
            continue
        candidates.append(
            _SpanCandidate(
                text=match.group(0),
                label="proper_noun",
                source_layer="regex",
                source_priority=2,
                confidence=_TITLE_CASE_CONFIDENCE,
                start_offset=match.start(),
                end_offset=match.end(),
            )
        )
    for match in _ACRONYM_PATTERN.finditer(block_text):
        candidates.append(
            _SpanCandidate(
                text=match.group(0),
                label="acronym",
                source_layer="regex",
                source_priority=2,
                confidence=_ACRONYM_CONFIDENCE,
                start_offset=match.start(),
                end_offset=match.end(),
            )
        )
    candidates.extend(_lowercase_ngram_candidates(block_text))
    return candidates


def _build_lowercase_token_counts(blocks: list[BlockTextInput]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        for match in _LOWERCASE_TOKEN_PATTERN.finditer(block.content_text):
            token = match.group(0).lower()
            if len(token) < 4:
                continue
            if token in _STOPWORDS or token in _LOWERCASE_VERB_TOKENS or token in _LOWERCASE_NOISE_TOKENS:
                continue
            counts[token] = counts.get(token, 0) + 1
    return counts


def _lowercase_single_token_candidates(
    block_text: str,
    *,
    token_counts: dict[str, int],
) -> list[_SpanCandidate]:
    if not token_counts:
        return []
    candidates: list[_SpanCandidate] = []
    for match in _LOWERCASE_TOKEN_PATTERN.finditer(block_text):
        token = match.group(0).lower()
        if token_counts.get(token, 0) < 2:
            continue
        candidates.append(
            _SpanCandidate(
                text=match.group(0),
                label="domain_token",
                source_layer="regex",
                source_priority=2,
                confidence=_LOWERCASE_SINGLE_TOKEN_CONFIDENCE,
                start_offset=match.start(),
                end_offset=match.end(),
            )
        )
    return candidates


class _DictionaryExtractor:
    layer_name = "dictionary"

    def extract(
        self,
        *,
        block_text: str,
        dictionary_terms: list[str],
        seed_terms: list[str],
        model_handle: object | None,
    ) -> list[_SpanCandidate]:
        del model_handle
        return _dictionary_candidates(
            block_text,
            _normalize_terms(dictionary_terms, seed_terms),
        )


class _SpacyExtractor:
    layer_name = "spacy"

    def extract(
        self,
        *,
        block_text: str,
        dictionary_terms: list[str],
        seed_terms: list[str],
        model_handle: object | None,
    ) -> list[_SpanCandidate]:
        return _spacy_candidates(
            block_text=block_text,
            model_handle=model_handle,
            dictionary_terms=dictionary_terms,
            seed_terms=seed_terms,
        )


class _RegexFallbackExtractor:
    layer_name = "regex"

    def extract(
        self,
        *,
        block_text: str,
        dictionary_terms: list[str],
        seed_terms: list[str],
        model_handle: object | None,
    ) -> list[_SpanCandidate]:
        del dictionary_terms, seed_terms, model_handle
        return _fallback_candidates(block_text)


def extract_entities_with_mentions_and_metrics(
    *,
    blocks: list[BlockTextInput],
    dictionary_terms: list[str] | None = None,
    extraction_profile: str = "rule-only",
    model_handle: object | None = None,
    seed_terms: list[str] | None = None,
    enable_regex_fallback: bool = True,
) -> tuple[list[ExtractedEntity], list[ExtractedEntityMention], EntityExtractionMetrics]:
    return _extract_entities_with_mentions(
        blocks=blocks,
        dictionary_terms=dictionary_terms,
        extraction_profile=extraction_profile,
        model_handle=model_handle,
        seed_terms=seed_terms,
        enable_regex_fallback=enable_regex_fallback,
    )


def extract_entities_with_mentions(
    *,
    blocks: list[BlockTextInput],
    dictionary_terms: list[str] | None = None,
    extraction_profile: str = "rule-only",
    model_handle: object | None = None,
    seed_terms: list[str] | None = None,
    enable_regex_fallback: bool = True,
) -> tuple[list[ExtractedEntity], list[ExtractedEntityMention]]:
    entities, mentions, _metrics = _extract_entities_with_mentions(
        blocks=blocks,
        dictionary_terms=dictionary_terms,
        extraction_profile=extraction_profile,
        model_handle=model_handle,
        seed_terms=seed_terms,
        enable_regex_fallback=enable_regex_fallback,
    )
    return entities, mentions


def _extract_entities_with_mentions(
    *,
    blocks: list[BlockTextInput],
    dictionary_terms: list[str] | None,
    extraction_profile: str,
    model_handle: object | None,
    seed_terms: list[str] | None,
    enable_regex_fallback: bool,
) -> tuple[list[ExtractedEntity], list[ExtractedEntityMention], EntityExtractionMetrics]:
    entity_index: dict[str, ExtractedEntity] = {}
    mentions: list[ExtractedEntityMention] = []
    seen_mentions: set[tuple[str, int, int, int]] = set()
    dictionary_terms = list(dictionary_terms or [])
    seed_terms = list(seed_terms or [])
    lowercase_token_counts = _build_lowercase_token_counts(blocks)
    dictionary_hits = 0
    spacy_hits = 0
    regex_hits = 0
    extractors: list[EntityCandidateExtractor] = [_DictionaryExtractor()]
    if extraction_profile in {"hybrid-spacy", "llm-enhanced"}:
        extractors.append(_SpacyExtractor())
    if enable_regex_fallback:
        extractors.append(_RegexFallbackExtractor())

    for block in sorted(blocks, key=lambda item: item.block_index):
        block_text = block.content_text
        if not block_text.strip():
            continue

        candidates: list[_SpanCandidate] = []
        for extractor in extractors:
            raw_candidates = extractor.extract(
                block_text=block_text,
                dictionary_terms=dictionary_terms,
                seed_terms=seed_terms,
                model_handle=model_handle,
            )
            span_candidates = cast(list[_SpanCandidate], raw_candidates)
            if extractor.layer_name == "dictionary":
                dictionary_hits += len(span_candidates)
            elif extractor.layer_name == "spacy":
                spacy_hits += len(span_candidates)
            elif extractor.layer_name == "regex":
                regex_hits += len(span_candidates)
            candidates.extend(span_candidates)
        if enable_regex_fallback:
            token_candidates = _lowercase_single_token_candidates(
                block_text,
                token_counts=lowercase_token_counts,
            )
            regex_hits += len(token_candidates)
            candidates.extend(token_candidates)

        candidates.sort(
            key=lambda item: (
                item.start_offset,
                -(item.end_offset - item.start_offset),
                -item.confidence,
                item.source_priority,
                item.text.lower(),
            )
        )
        seen_spans: set[tuple[int, int]] = set()
        accepted_spans: list[tuple[int, int]] = []

        for candidate in candidates:
            span_key = (candidate.start_offset, candidate.end_offset)
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)
            if any(
                accepted_start <= candidate.start_offset
                and accepted_end >= candidate.end_offset
                for accepted_start, accepted_end in accepted_spans
            ):
                continue
            normalized_text = _normalize_term(candidate.text)
            if not normalized_text:
                continue
            key = normalized_text.lower()
            if key in _STOPWORDS:
                continue
            if not _passes_quality_gate(normalized_text):
                continue
            entity_id = f"entity-{_slugify(normalized_text)}"
            existing_entity = entity_index.get(key)
            if existing_entity is None or candidate.confidence > existing_entity.confidence:
                entity_index[key] = ExtractedEntity(
                    entity_id=entity_id,
                    text=normalized_text,
                    label=candidate.label,
                    confidence=candidate.confidence,
                )

            mention_key = (
                entity_id,
                block.block_index,
                candidate.start_offset,
                candidate.end_offset,
            )
            if mention_key in seen_mentions:
                continue
            seen_mentions.add(mention_key)
            accepted_spans.append(span_key)
            mentions.append(
                ExtractedEntityMention(
                    entity_id=entity_id,
                    block_index=block.block_index,
                    mention_text=normalized_text,
                    start_offset=candidate.start_offset,
                    end_offset=candidate.end_offset,
                    confidence=candidate.confidence,
                )
            )

    entities = sorted(entity_index.values(), key=lambda item: item.entity_id)
    mentions.sort(
        key=lambda item: (
            item.block_index,
            item.start_offset,
            item.end_offset,
            item.entity_id,
        )
    )
    return (
        entities,
        mentions,
        EntityExtractionMetrics(
            dictionary_hits=dictionary_hits,
            spacy_hits=spacy_hits,
            regex_hits=regex_hits,
            merged_mentions=len(mentions),
        ),
    )
