"""Single-profile deterministic NLP pipeline.

Runs extraction → normalisation → structure-relation derivation. No LLM
on the critical path. The returned `NoteExtractionResult` is consumed by
the existing graph sync service unchanged.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

from sqlalchemy.orm import Session

from app.nlp.config import NlpSettings, get_nlp_settings
from app.nlp.embeddings import build_embedding
from app.nlp.extraction import extract_concepts
from app.nlp.normalisation import normalise_concepts
from app.nlp.preprocessor import preprocess_content
from app.nlp.semantic_embeddings import build_semantic_embedding
from app.nlp.structure_relations import derive_relations
from app.nlp.types import (
    ExtractedEntity,
    ExtractedRelation,
    NoteExtractionResult,
)

_LOGGER = logging.getLogger(__name__)
_EXTRACTION_CACHE: "OrderedDict[str, NoteExtractionResult]" = OrderedDict()
_EXTRACTION_CACHE_MAX = 256


def clear_extraction_cache() -> None:
    """Evict all in-memory NLP extraction results (call before force re-extraction)."""
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
        cached = _EXTRACTION_CACHE.get(content_hash)
        if cached is not None:
            _EXTRACTION_CACHE.move_to_end(content_hash)
            return cached.with_note_id(note_id)

        started = time.perf_counter()
        composed = self._compose_text(title, content_text)
        preprocessed = preprocess_content(composed)
        spans = extract_concepts(preprocessed)
        norm = normalise_concepts(session, spans, embed=embedder)
        canonicals = [c.canonical_text for c in norm.concepts]

        entities: list[ExtractedEntity] = [
            ExtractedEntity(
                entity_id=f"concept-{_slugify(c.canonical_text)}",
                text=c.canonical_text,
                label="concept",
                confidence=c.confidence,
            )
            for c in norm.concepts
        ]

        struct_edges = derive_relations(document_json, concepts=canonicals)
        relations: list[ExtractedRelation] = []
        for edge in struct_edges:
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

        embedding = (
            build_semantic_embedding(content_text)
            if self._settings.use_semantic_embeddings
            else (build_embedding(content_text) if self._settings.enable_embeddings else None)
        )

        result = NoteExtractionResult(
            note_id=note_id,
            content_hash=content_hash,
            entities=entities,
            keyphrases=[],
            relations=relations,
            embedding=embedding,
            entity_mentions=[],
            summary="",
        )

        _EXTRACTION_CACHE[content_hash] = result
        if len(_EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
            _EXTRACTION_CACHE.popitem(last=False)

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
