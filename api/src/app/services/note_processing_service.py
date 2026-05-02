from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import get_session_factory
from app.db.tenant import validate_schema_name
from app.db.models.block import Block
from app.db.models.nlp_extraction_cache import NlpExtractionCache
from app.db.repositories.entity_alias_repository import AliasRecord, EntityAliasRepository
from app.db.repositories.graph_repository import GraphRepository
from app.db.repositories.note_repository import NoteRepository
from app.nlp.concept_meta import ConceptMetaClassifier
from app.nlp.concept_registry import get_known_concepts, register_concepts
from app.nlp.config import get_nlp_settings
from app.nlp.pipeline import NoteNlpPipeline
from app.nlp.resolution.resolver import CanonicalAlias, EntityResolver
from app.nlp.types import (
    BlockTextInput,
    ExtractedEntity,
    ExtractedEntityMention,
    ExtractedKeyphrase,
    ExtractedRelation,
    NoteExtractionResult,
)
from app.services.graph_sync_service import (
    CanonicalEntityMapping,
    GraphSyncPayload,
    GraphSyncService,
)
from shared.contracts.python.v1.process import ExtractionSummary, ProcessNoteRequest

_DEFAULT_GRAPH_NAME = "neuronote"
_LOGGER = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class NoteNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessedNoteSnapshot:
    note_id: str
    subject_id: str
    note_title: str
    content_text: str
    content_hash: str
    updated_at: str
    blocks: list[BlockTextInput]


class NoteProcessingService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        pipeline: NoteNlpPipeline | None = None,
        graph_name: str = _DEFAULT_GRAPH_NAME,
        schema_name: str | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._pipeline = pipeline or NoteNlpPipeline()
        self._graph_name = graph_name
        self._schema_name = schema_name

    def _open_session(self) -> Session:
        """Open a session — search_path is set by the engine's pool checkout
        event based on the contextvar set in ``process_note``."""
        return self._session_factory()

    def _load_snapshot(self, note_id: str) -> ProcessedNoteSnapshot:
        with self._open_session() as session:
            note = NoteRepository(session).get_note(note_id)
            if note is None:
                raise NoteNotFoundError(f"Note {note_id} was not found")
            blocks = session.execute(
                select(Block).where(Block.note_id == note_id).order_by(Block.block_index.asc())
            ).scalars()
            block_inputs = [
                BlockTextInput(
                    block_index=block.block_index,
                    content_text=block.content_text,
                )
                for block in blocks
            ]
            return ProcessedNoteSnapshot(
                note_id=note.note_id,
                subject_id=note.subject_id,
                note_title=note.note_title,
                content_text=note.content_text,
                content_hash=note.content_hash,
                updated_at=note.updated_at,
                blocks=block_inputs,
            )

    def _is_postgres(self, session: Session) -> bool:
        if session.bind is None:
            return False
        return session.bind.dialect.name == "postgresql"

    def _compose_pipeline_text(self, snapshot: ProcessedNoteSnapshot) -> str:
        title = snapshot.note_title.strip()
        body = snapshot.content_text.strip()
        if not title:
            return body
        if not body:
            return title
        return f"{title}\n\n{body}"

    def _load_alias_records(self) -> dict[str, AliasRecord]:
        with self._open_session() as session:
            return EntityAliasRepository(session).list_alias_index()

    def _build_dictionary_terms(self, alias_records: dict[str, AliasRecord]) -> list[str]:
        terms: list[str] = []
        for alias_text, record in alias_records.items():
            terms.append(alias_text)
            terms.append(record.canonical_name)
        seen: set[str] = set()
        ordered_terms: list[str] = []
        for term in terms:
            normalized = " ".join(term.split()).strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered_terms.append(normalized)
        return ordered_terms

    def _build_resolver(self, alias_records: dict[str, AliasRecord]) -> EntityResolver:
        alias_index = {
            alias_text: CanonicalAlias(
                canonical_entity_id=record.canonical_entity_id,
                canonical_name=record.canonical_name,
            )
            for alias_text, record in alias_records.items()
        }
        abbreviation_index = {
            alias_text.replace(" ", ""): record.canonical_name
            for alias_text, record in alias_records.items()
            if " " not in alias_text and 1 < len(alias_text) <= 10
        }
        return EntityResolver(
            alias_index=alias_index,
            abbreviation_index=abbreviation_index,
        )

    # ── NLP extraction cache ─────────────────────────────────────────────────

    def _try_load_nlp_cache(
        self, content_hash: str, profile: str
    ) -> NoteExtractionResult | None:
        """Return cached extraction or None. note_id is "" — callers re-stamp it.
        Cache miss if stored profile differs (profile change forces fresh extraction).
        """
        try:
            with self._open_session() as session:
                row = session.execute(
                    select(NlpExtractionCache).where(
                        NlpExtractionCache.content_hash == content_hash,
                    )
                ).scalar_one_or_none()
            if row is None or row.extraction_profile != profile:
                return None
            data: dict = json.loads(row.result_json)  # type: ignore[type-arg]
            return NoteExtractionResult(
                note_id="",  # re-stamped by caller
                content_hash=content_hash,
                entities=[ExtractedEntity(**e) for e in data.get("entities", [])],
                keyphrases=[ExtractedKeyphrase(**k) for k in data.get("keyphrases", [])],
                relations=[ExtractedRelation(**r) for r in data.get("relations", [])],
                embedding=data.get("embedding"),
                entity_mentions=[
                    ExtractedEntityMention(**m) for m in data.get("entity_mentions", [])
                ],
                summary=data.get("summary", ""),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("nlp_extraction_cache read skipped", exc_info=True)
            return None

    def _save_nlp_cache(
        self, content_hash: str, profile: str, result: NoteExtractionResult
    ) -> None:
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            data = dataclasses.asdict(result)
            data.pop("note_id", None)  # note_id is ephemeral, not cached
            result_json = json.dumps(data)
            stmt = (
                pg_insert(NlpExtractionCache)
                .values(
                    content_hash=content_hash,
                    extraction_profile=profile,
                    result_json=result_json,
                )
                .on_conflict_do_update(
                    index_elements=["content_hash"],
                    set_={
                        "extraction_profile": profile,
                        "result_json": result_json,
                    },
                )
            )
            with self._open_session() as session:
                with session.begin():
                    session.execute(stmt)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("nlp_extraction_cache write skipped", exc_info=True)

    # ── Core processing ──────────────────────────────────────────────────────

    def _persist_graph_and_vector(self, *, snapshot: ProcessedNoteSnapshot) -> ExtractionSummary:
        alias_records = self._load_alias_records()
        # Merge entity-alias terms with all concepts extracted from previous notes.
        # This feeds the SLM its own prior output as "known concepts", closing the
        # normalisation loop: once "machine learning" is extracted once, future calls
        # see it and reuse that exact form instead of producing "ML" or "machine-learning".
        base_terms = self._build_dictionary_terms(alias_records)
        with self._open_session() as session:
            known = get_known_concepts(session)
        dictionary_terms = base_terms + [c for c in known if c not in set(t.lower() for t in base_terms)]

        profile = getattr(self._pipeline, "extraction_profile", "rule-only")
        cached_result = self._try_load_nlp_cache(snapshot.content_hash, profile)
        if cached_result is not None:
            _LOGGER.debug(
                "nlp_extraction_cache hit for content_hash=%s profile=%s",
                snapshot.content_hash[:8],
                profile,
            )
            result = dataclasses.replace(cached_result, note_id=snapshot.note_id)
        else:
            result = self._pipeline.extract(
                note_id=snapshot.note_id,
                title=snapshot.note_title,
                content_text=self._compose_pipeline_text(snapshot),
                content_hash=snapshot.content_hash,
                blocks=snapshot.blocks,
                dictionary_terms=dictionary_terms,
            )
            self._save_nlp_cache(snapshot.content_hash, profile, result)

        # Register newly extracted concepts so subsequent notes see them.
        if result.entities:
            with self._open_session() as session:
                with session.begin():
                    register_concepts(session, [(e.text, e.entity_id) for e in result.entities if e.label == "concept"])
        resolution_batch = self._build_resolver(alias_records).resolve(result.entities)

        summary = ExtractionSummary(
            entity_count=len(result.entities),
            relation_count=len(result.relations),
            keyphrase_count=len(result.keyphrases),
            top_entities=[e.text for e in result.entities[:5]],
        )

        with self._open_session() as session:
            if not self._is_postgres(session):
                return summary

            with session.begin():
                resolved_index: dict[str, CanonicalEntityMapping] = {
                    item.source_entity_id: CanonicalEntityMapping(
                        canonical_entity_id=item.canonical_entity_id,
                        canonical_name=item.canonical_name,
                        confidence=float(item.confidence),
                    )
                    for item in resolution_batch.resolved
                }
                GraphSyncService(
                    session=session,
                    graph_name=self._graph_name,
                ).sync_note_graph(
                    GraphSyncPayload(
                        note_id=snapshot.note_id,
                        note_title=snapshot.note_title,
                        subject_id=snapshot.subject_id,
                        content_hash=snapshot.content_hash,
                        updated_at=snapshot.updated_at,
                        entities=result.entities,
                        keyphrases=result.keyphrases,
                        relations=result.relations,
                        resolved_entities=resolved_index,
                        embedding=result.embedding,
                        entity_mentions=result.entity_mentions,
                        note_summary=result.summary,
                    )
                )

        # Classify synonym/subtopic relationships for new concepts.
        # Runs in its own session after the graph sync commits.
        self._run_concept_meta_classification(result.entities)

        return summary

    # ── Concept meta-classification ──────────────────────────────────────────

    def _run_concept_meta_classification(self, entities: list[ExtractedEntity]) -> None:
        """Classify synonym/subtopic edges for new concepts (meta_classified_at IS NULL only).
        Runs in its own session after graph sync commits.
        """
        cfg = getattr(self._pipeline, "settings", None) or get_nlp_settings()
        if not cfg.llm_api_key:
            return

        concept_texts = [
            e.text for e in entities if e.label == "concept"
        ]
        if not concept_texts:
            return

        try:
            with self._open_session() as session:
                rows = session.execute(
                    sa_text(
                        "SELECT concept_text FROM concept_registry "
                        "WHERE concept_text = ANY(:texts) AND meta_classified_at IS NULL"
                    ),
                    {"texts": concept_texts},
                ).all()
                unclassified = [r[0] for r in rows]
        except Exception:
            _LOGGER.debug("concept_meta: failed to query unclassified concepts", exc_info=True)
            return

        if not unclassified:
            return

        # Pass unclassified concepts + a sample of known concepts as context
        # so the SLM can spot cross-note synonyms and hierarchies.
        with self._open_session() as session:
            known = get_known_concepts(session)[:60]
        all_concepts = list(dict.fromkeys(unclassified + known))

        classifier = ConceptMetaClassifier(
            api_key=cfg.llm_api_key,
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
        )
        meta = classifier.classify(all_concepts)

        if meta.synonym_pairs or meta.subtopic_pairs:
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                with self._open_session() as session:
                    if not self._is_postgres(session):
                        return
                    repo = GraphRepository(session=session)
                    with session.begin():
                        for a, b in meta.synonym_pairs:
                            repo.upsert_typed_edge(
                                source_label="Entity",
                                source_id="concept-" + _SLUG_RE.sub("-", a).strip("-"),
                                target_label="Entity",
                                target_id="concept-" + _SLUG_RE.sub("-", b).strip("-"),
                                relation_type="SYNONYM_OF",
                                properties={"confidence": 0.9, "created_at": now_iso},
                                graph_name=self._graph_name,
                            )
                        for specific, broader in meta.subtopic_pairs:
                            repo.upsert_typed_edge(
                                source_label="Entity",
                                source_id="concept-" + _SLUG_RE.sub("-", specific).strip("-"),
                                target_label="Entity",
                                target_id="concept-" + _SLUG_RE.sub("-", broader).strip("-"),
                                relation_type="SUBTOPIC_OF",
                                properties={"confidence": 0.85, "created_at": now_iso},
                                graph_name=self._graph_name,
                            )
            except Exception:
                _LOGGER.debug("concept_meta: failed to write edges", exc_info=True)
                return

        self._mark_concepts_classified(unclassified)

    def _mark_concepts_classified(self, concept_texts: list[str]) -> None:
        try:
            now_dt = datetime.now(timezone.utc)
            with self._open_session() as session:
                with session.begin():
                    session.execute(
                        sa_text(
                            "UPDATE concept_registry SET meta_classified_at = :now "
                            "WHERE concept_text = ANY(:texts)"
                        ),
                        {"now": now_dt, "texts": concept_texts},
                    )
        except Exception:
            _LOGGER.debug("concept_meta: failed to mark classified", exc_info=True)

    def process_note(self, payload: ProcessNoteRequest) -> ExtractionSummary:
        # Set the tenant schema contextvar so connections checked out from the
        # pool by every internal session apply the right SET search_path.
        from app.db.engine import set_tenant_schema
        if self._schema_name:
            validate_schema_name(self._schema_name)
        set_tenant_schema(self._schema_name)
        try:
            snapshot = self._load_snapshot(payload.note_id)
            return self._persist_graph_and_vector(snapshot=snapshot)
        finally:
            set_tenant_schema(None)
