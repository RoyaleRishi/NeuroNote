from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace as _dataclass_replace
import logging
import re
from threading import Lock
import time

from app.nlp.config import NlpSettings, get_nlp_settings
from app.nlp.embeddings import build_embedding
from app.nlp.keyphrases import extract_keyphrases
from app.nlp.metrics import StageTiming, format_stage_timings
from app.nlp.preprocessor import preprocess_content
from app.nlp.relations import extract_relations
from app.nlp.semantic_embeddings import build_semantic_embedding
from app.nlp.slm_extractor import SLMExtractor
from app.nlp.spotting import extract_entities_with_mentions_and_metrics
from app.nlp.spotting import _STOPWORDS as _PIPELINE_STOPWORDS  # noqa: PLC2701
from app.nlp.types import BlockTextInput, ExtractedEntity, ExtractedRelation, NoteExtractionResult

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_LOGGER = logging.getLogger(__name__)

# Module-level LRU cache for NLP extraction results.
# Keyed by (note_id, content_hash) — a changed note produces a new hash, so stale
# entries become unreachable and are evicted naturally without explicit invalidation.
_EXTRACTION_CACHE: OrderedDict[str, NoteExtractionResult] = OrderedDict()
_EXTRACTION_CACHE_MAX = 512


def clear_extraction_cache() -> None:
    """Evict all in-memory NLP extraction results (call before force re-extraction)."""
    _EXTRACTION_CACHE.clear()


class NoteNlpPipeline:
    """Orchestrates NLP extraction for a single note.

    Profiles (``NLP_EXTRACTION_PROFILE``):
    - ``rule-only``    — dictionary + regex; no external deps.
    - ``hybrid-spacy`` — dictionary + spaCy NER + regex fallback.
    - ``llm-enhanced`` — LLM via :class:`SLMExtractor`; requires ``LLM_API_KEY``.

    spaCy model handles are cached at the class level so worker threads share one instance.
    Missing model falls back to rule-based silently.
    """

    _MODEL_HANDLE_CACHE: dict[str, object | None] = {}
    _MODEL_CACHE_LOCK = Lock()

    def __init__(self, settings: NlpSettings | None = None) -> None:
        self._settings = settings or get_nlp_settings()
        self._last_stage_timings: dict[str, float] = {}
        self._last_extraction_hit_counts: dict[str, int] = {}
        self._slm_extractor: SLMExtractor | None = None
        if self._settings.extraction_profile == "llm-enhanced" and self._settings.llm_api_key:
            self._slm_extractor = SLMExtractor(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url,
                timeout_ms=self._settings.llm_timeout_ms,
            )

    def _get_model_handle(self, model_name: str) -> object | None:
        with self._MODEL_CACHE_LOCK:
            if model_name in self._MODEL_HANDLE_CACHE:
                return self._MODEL_HANDLE_CACHE[model_name]

            if model_name.startswith("spacy:"):
                model_id = model_name.split(":", maxsplit=1)[1]
                handle: object | None
                try:
                    import spacy  # type: ignore[import-not-found]

                    handle = spacy.load(model_id)
                except Exception:
                    # Missing model should not fail processing; we fall back to rule-based extraction.
                    handle = None
            else:
                handle = object()

            self._MODEL_HANDLE_CACHE[model_name] = handle
            return handle

    def _is_timed_out(self, started_at: float) -> bool:
        return (time.perf_counter() - started_at) * 1000.0 > float(self._settings.timeout_ms)

    def _empty_result(self, *, note_id: str, content_hash: str) -> NoteExtractionResult:
        self._last_extraction_hit_counts = {}
        return NoteExtractionResult(
            note_id=note_id,
            content_hash=content_hash,
            entities=[],
            keyphrases=[],
            relations=[],
            embedding=None,
            entity_mentions=[],
        )

    @property
    def extraction_profile(self) -> str:
        return self._settings.extraction_profile

    @property
    def settings(self) -> NlpSettings:
        return self._settings

    def get_last_stage_timings(self) -> dict[str, float]:
        return dict(self._last_stage_timings)

    def get_last_extraction_hit_counts(self) -> dict[str, int]:
        return dict(self._last_extraction_hit_counts)

    @staticmethod
    def _slugify(text: str) -> str:
        return _SLUG_RE.sub("-", text.lower()).strip("-") or "unknown"

    def extract(
        self,
        *,
        note_id: str,
        title: str = "",
        content_text: str,
        content_hash: str,
        blocks: list[BlockTextInput] | None = None,
        dictionary_terms: list[str] | None = None,
    ) -> NoteExtractionResult:
        # ── Extraction cache ──────────────────────────────────────────────────
        # Key on content_hash only — two notes with identical text share one
        # extraction result, guaranteeing identical concepts regardless of note_id.
        cache_key = content_hash
        if cache_key in _EXTRACTION_CACHE:
            _EXTRACTION_CACHE.move_to_end(cache_key)
            cached = _EXTRACTION_CACHE[cache_key]
            # Re-stamp note_id so GraphSyncService targets the right note.
            if cached.note_id != note_id:
                return _dataclass_replace(cached, note_id=note_id)
            return cached

        stage_timings: list[StageTiming] = []
        started_at = time.perf_counter()

        if self._settings.timeout_ms <= 0:
            stage_timings.append(StageTiming(stage="timeout_guard", duration_ms=0.0))
            self._last_stage_timings = format_stage_timings(stage_timings)
            return self._empty_result(note_id=note_id, content_hash=content_hash)

        if len(content_text.strip().split()) < self._settings.process_min_text_len:
            stage_timings.append(StageTiming(stage="min_text_guard", duration_ms=0.0))
            self._last_stage_timings = format_stage_timings(stage_timings)
            return self._empty_result(note_id=note_id, content_hash=content_hash)

        # ── LLM-enhanced path ──────────────────────────────────────────────────
        if self._settings.extraction_profile == "llm-enhanced" and self._slm_extractor is not None:
            slm_started = time.perf_counter()
            # Preprocess note text and run rule-only spotting to generate candidates.
            # The LLM then filters by index — never free-generates concept text.
            preprocessed = preprocess_content(content_text)
            extraction_blocks_llm = list(blocks or [BlockTextInput(block_index=0, content_text=content_text)])
            rule_entities, _, _ = extract_entities_with_mentions_and_metrics(
                blocks=extraction_blocks_llm,
                dictionary_terms=dictionary_terms or [],
                extraction_profile="rule-only",
                model_handle=None,
                seed_terms=list(self._settings.entity_seed_terms),
                enable_regex_fallback=self._settings.enable_regex_fallback,
            )
            candidates = [e.text for e in rule_entities]
            slm_result = self._slm_extractor.extract(
                title=title,
                preprocessed_content=preprocessed,
                candidates=candidates,
                known_concepts=list(dictionary_terms or []),
            )
            stage_timings.append(
                StageTiming(
                    stage="slm_extraction",
                    duration_ms=(time.perf_counter() - slm_started) * 1000.0,
                )
            )

            if slm_result is not None:
                entities: list[ExtractedEntity] = [
                    ExtractedEntity(
                        entity_id=f"concept-{self._slugify(c.text)}",
                        text=c.text,
                        label="concept",
                        confidence=c.confidence,
                    )
                    for c in slm_result.concepts
                    if c.text.strip().lower() not in _PIPELINE_STOPWORDS
                ]
                relations: list[ExtractedRelation] = [
                    ExtractedRelation(
                        subject_id=f"concept-{self._slugify(r.source)}",
                        subject_text=r.source,
                        predicate=r.type,
                        object_id=f"concept-{self._slugify(r.target)}",
                        object_text=r.target,
                        confidence=r.confidence,
                    )
                    for r in slm_result.relations
                ]

                embedding_started = time.perf_counter()
                if self._settings.use_semantic_embeddings:
                    embedding = build_semantic_embedding(content_text)
                    if embedding is None:
                        embedding = build_embedding(content_text) if self._settings.enable_embeddings else None
                else:
                    embedding = build_embedding(content_text) if self._settings.enable_embeddings else None
                stage_timings.append(
                    StageTiming(
                        stage="embedding",
                        duration_ms=(time.perf_counter() - embedding_started) * 1000.0,
                    )
                )
                stage_timings.append(
                    StageTiming(
                        stage="total",
                        duration_ms=(time.perf_counter() - started_at) * 1000.0,
                    )
                )
                self._last_stage_timings = format_stage_timings(stage_timings)
                self._last_extraction_hit_counts = {"slm_concepts": len(entities), "slm_relations": len(relations)}
                _LOGGER.debug("NLP stage timings (llm-enhanced): %s", self._last_stage_timings)
                slm_extraction_result = NoteExtractionResult(
                    note_id=note_id,
                    content_hash=content_hash,
                    entities=entities,
                    keyphrases=[],
                    relations=relations,
                    embedding=embedding,
                    entity_mentions=[],
                    summary=slm_result.summary,
                )
                _EXTRACTION_CACHE[content_hash] = slm_extraction_result
                if len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
                    _EXTRACTION_CACHE.popitem(last=False)
                return slm_extraction_result
            # SLM failed — fall through to rule-based path

        # ── Rule-based / hybrid-spacy path ────────────────────────────────────
        model_handle = None
        if self._settings.extraction_profile in {"hybrid-spacy", "llm-enhanced"}:
            model_handle = self._get_model_handle(self._settings.model_name)
        stage_timings.append(StageTiming(stage="model_handle_ready", duration_ms=0.0))

        entities_started = time.perf_counter()
        extraction_blocks = list(blocks or [BlockTextInput(block_index=0, content_text=content_text)])
        entities, entity_mentions, extraction_metrics = extract_entities_with_mentions_and_metrics(
            blocks=extraction_blocks,
            dictionary_terms=dictionary_terms or [],
            extraction_profile=self._settings.extraction_profile,
            model_handle=model_handle,
            seed_terms=list(self._settings.entity_seed_terms),
            enable_regex_fallback=self._settings.enable_regex_fallback,
        )
        self._last_extraction_hit_counts = {
            "dictionary_hits": extraction_metrics.dictionary_hits,
            "spacy_hits": extraction_metrics.spacy_hits,
            "regex_hits": extraction_metrics.regex_hits,
            "merged_mentions": extraction_metrics.merged_mentions,
        }
        stage_timings.append(
            StageTiming(
                stage="entities",
                duration_ms=(time.perf_counter() - entities_started) * 1000.0,
            )
        )
        if self._is_timed_out(started_at):
            stage_timings.append(StageTiming(stage="timeout_guard", duration_ms=0.0))
            self._last_stage_timings = format_stage_timings(stage_timings)
            return self._empty_result(note_id=note_id, content_hash=content_hash)

        keyphrases_started = time.perf_counter()
        keyphrases = extract_keyphrases(content_text)
        stage_timings.append(
            StageTiming(
                stage="keyphrases",
                duration_ms=(time.perf_counter() - keyphrases_started) * 1000.0,
            )
        )
        if self._is_timed_out(started_at):
            stage_timings.append(StageTiming(stage="timeout_guard", duration_ms=0.0))
            self._last_stage_timings = format_stage_timings(stage_timings)
            return self._empty_result(note_id=note_id, content_hash=content_hash)

        relations_started = time.perf_counter()
        relations = extract_relations(content_text)
        stage_timings.append(
            StageTiming(
                stage="relations",
                duration_ms=(time.perf_counter() - relations_started) * 1000.0,
            )
        )
        if self._is_timed_out(started_at):
            stage_timings.append(StageTiming(stage="timeout_guard", duration_ms=0.0))
            self._last_stage_timings = format_stage_timings(stage_timings)
            return self._empty_result(note_id=note_id, content_hash=content_hash)

        embedding = None
        if self._settings.enable_embeddings:
            embedding_started = time.perf_counter()
            embedding = build_embedding(content_text)
            stage_timings.append(
                StageTiming(
                    stage="embedding",
                    duration_ms=(time.perf_counter() - embedding_started) * 1000.0,
                )
            )

        stage_timings.append(
            StageTiming(
                stage="total",
                duration_ms=(time.perf_counter() - started_at) * 1000.0,
            )
        )
        self._last_stage_timings = format_stage_timings(stage_timings)
        _LOGGER.debug("NLP stage timings: %s", self._last_stage_timings)

        result = NoteExtractionResult(
            note_id=note_id,
            content_hash=content_hash,
            entities=entities,
            keyphrases=keyphrases,
            relations=relations,
            embedding=embedding,
            entity_mentions=entity_mentions,
        )
        _EXTRACTION_CACHE[content_hash] = result
        if len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
            _EXTRACTION_CACHE.popitem(last=False)
        return result
