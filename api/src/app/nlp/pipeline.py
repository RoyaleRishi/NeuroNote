"""Single-profile deterministic NLP pipeline.

Runs extraction → normalisation → structure-relation derivation. No LLM
on the critical path. The returned `NoteExtractionResult` is consumed by
the existing graph sync service unchanged.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

from sqlalchemy.orm import Session

from app.nlp.config import NlpSettings, get_nlp_settings
from app.nlp.embeddings import build_embedding
from app.nlp.extraction import extract_concepts
from app.nlp.hierarchy import hearst_is_a
from app.nlp.normalisation import normalise_concepts
from app.nlp.preprocessor import preprocess_content
from app.nlp.salience import rank_and_filter
from app.nlp.semantic_embeddings import build_semantic_embedding
from app.nlp.spacy_model import get_nlp
from app.nlp.structure_relations import derive_relations
from app.nlp.subsumption import merge_and_subsume
from app.nlp.types import (
    ConceptSurface,
    ExtractedEntity,
    ExtractedRelation,
    NoteExtractionResult,
)

_LOGGER = logging.getLogger(__name__)
_EXTRACTION_CACHE: "OrderedDict[str, NoteExtractionResult]" = OrderedDict()
_EXTRACTION_CACHE_MAX = 256
_EXTRACTION_CACHE_LOCK = threading.Lock()


def _cache_get(content_hash: str) -> "NoteExtractionResult | None":
    """Return cached result for *content_hash*, or None. Thread-safe."""
    with _EXTRACTION_CACHE_LOCK:
        result = _EXTRACTION_CACHE.get(content_hash)
        if result is not None:
            _EXTRACTION_CACHE.move_to_end(content_hash)
        return result


def _cache_put(content_hash: str, result: "NoteExtractionResult") -> None:
    """Insert *result* into the cache, evicting the LRU entry if at capacity. Thread-safe."""
    with _EXTRACTION_CACHE_LOCK:
        _EXTRACTION_CACHE[content_hash] = result
        if len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
            _EXTRACTION_CACHE.popitem(last=False)


def clear_extraction_cache() -> None:
    """Evict all in-memory NLP extraction results (call before force re-extraction)."""
    with _EXTRACTION_CACHE_LOCK:
        _EXTRACTION_CACHE.clear()


def _slugify(raw: str) -> str:
    s = raw.lower().strip()
    out = []
    last_dash = True
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        elif not last_dash:
            out.append("-")
            last_dash = True
    result = "".join(out).strip("-")
    return result or "entity"


class NoteNlpPipeline:
    def __init__(self, *, settings: NlpSettings | None = None) -> None:
        self._settings: NlpSettings = settings or get_nlp_settings()

    @property
    def settings(self) -> NlpSettings:
        return self._settings

    def extract(
        self,
        *,
        session: Session,
        embedder,
        note_id: str,
        title: str,
        content_text: str,
        document_json: dict,
        content_hash: str,
    ) -> NoteExtractionResult:
        cached = _cache_get(content_hash)
        if cached is not None:
            return cached.with_note_id(note_id)

        started = time.perf_counter()
        composed = self._compose_text(title, content_text)
        preprocessed = preprocess_content(composed)
        # Parse the note once; the same Doc feeds both candidate extraction and
        # Hearst matching (spaCy parsing is the dominant per-note cost).
        doc = get_nlp()(preprocessed)

        # Stage 1: noun-phrase candidates (high recall, unranked).
        spans = extract_concepts(
            preprocessed,
            enable_yake_fallback=self._settings.enable_yake_fallback,
            doc=doc,
        )
        # Stage 2: salience ranking + redundancy filter (no hard cap).
        salient = rank_and_filter(
            preprocessed,
            spans,
            embed=embedder,
            threshold_delta=self._settings.salience_threshold_delta,
            redundancy_threshold=self._settings.salience_redundancy_threshold,
        )
        # Stage 3: merge inflectional variants + seed compound IS_A hierarchy.
        subsumed = merge_and_subsume(salient)
        # Stage 4: cross-note normalisation against the concept registry.
        norm = normalise_concepts(session, subsumed.concepts, embed=embedder)
        # Build ConceptSurface list: match on surface (verbatim in-document
        # noun phrase), but key edges by canonical (cross-note identity).
        concept_surfaces = [
            ConceptSurface(surface=c.raw_text, canonical=c.canonical_text)
            for c in norm.concepts
        ]

        entities: list[ExtractedEntity] = [
            ExtractedEntity(
                entity_id=f"concept-{_slugify(c.canonical_text)}",
                text=c.canonical_text,
                label="concept",
                confidence=c.confidence,
            )
            for c in norm.concepts
        ]

        derivation = derive_relations(document_json, concepts=concept_surfaces)
        relations: list[ExtractedRelation] = []
        for edge in derivation.edges:
            if edge.relation == "DEFINED_BY":
                # DEFINED_BY links concept → note; graph sync handles it separately.
                continue
            relations.append(ExtractedRelation(
                subject_id=f"concept-{_slugify(edge.source)}",
                subject_text=edge.source,
                predicate=edge.relation,
                object_id=f"concept-{_slugify(edge.target)}",
                object_text=edge.target,
                confidence=0.7 if edge.relation == "MENTIONED_TOGETHER" else 1.0,
            ))

        for syn in norm.synonym_edges:
            relations.append(ExtractedRelation(
                subject_id=f"concept-{_slugify(syn.from_text)}",
                subject_text=syn.from_text,
                predicate="SYNONYM_OF",
                object_id=f"concept-{_slugify(syn.to_text)}",
                object_text=syn.to_text,
                confidence=0.95,
            ))

        # Semantic IS_A hierarchy: compound head-modifier subsumption (Stage 3)
        # plus Hearst lexico-syntactic patterns over the note text. Both speak in
        # concept *surfaces*; map to canonical identity and dedup before emitting.
        surface_to_canonical = {c.raw_text: c.canonical_text for c in norm.concepts}
        # (surface, spaCy lemma) pairs straight from the subsumed concepts, so
        # Hearst matches on lemmas. Their surfaces are exactly the keys of
        # surface_to_canonical (normalisation preserves raw_text), so edges map back.
        hearst_concepts = [(c.text, c.lemma or c.text.lower()) for c in subsumed.concepts]
        hearst_edges = hearst_is_a(preprocessed, hearst_concepts, doc=doc)
        is_a_pairs: set[tuple[str, str]] = set()
        for is_a_edge in (*subsumed.is_a_edges, *hearst_edges):
            child = surface_to_canonical.get(is_a_edge.child)
            parent = surface_to_canonical.get(is_a_edge.parent)
            if child and parent and child != parent:
                is_a_pairs.add((child, parent))
        for child, parent in sorted(is_a_pairs):
            relations.append(ExtractedRelation(
                subject_id=f"concept-{_slugify(child)}",
                subject_text=child,
                predicate="IS_A",
                object_id=f"concept-{_slugify(parent)}",
                object_text=parent,
                confidence=0.9,
            ))

        embedding = (
            build_semantic_embedding(content_text)
            if self._settings.use_semantic_embeddings
            else (build_embedding(content_text) if self._settings.enable_embeddings else None)
        )

        result = NoteExtractionResult(
            note_id=note_id,
            content_hash=content_hash,
            entities=entities,
            relations=relations,
            embedding=embedding,
            distinct_blocks_with_concepts=derivation.distinct_blocks_with_concepts,
        )

        _cache_put(content_hash, result)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        _LOGGER.info(
            "pipeline.extract: note_id=%s concepts=%d relations=%d %.0fms",
            note_id, len(entities), len(relations), elapsed_ms,
        )
        return result

    @staticmethod
    def _compose_text(title: str, body: str) -> str:
        title = title.strip()
        body = body.strip()
        if not title:
            return body
        if not body:
            return title
        return f"{title}\n\n{body}"
