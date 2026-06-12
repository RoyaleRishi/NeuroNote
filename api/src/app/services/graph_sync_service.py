from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.block import Block
from app.db.repositories.block_repository import BlockRepository
from app.db.repositories.embedding_repository import EmbeddingRepository
from app.db.repositories.graph_repository import GraphRepository
from app.nlp.types import (
    ExtractedEntity,
    ExtractedRelation,
)

_LOG = logging.getLogger(__name__)

# Concept→Concept relation predicates emitted by the deterministic
# pipeline. Anything outside this set is logged and dropped — we do not
# silently coerce unknown predicates to a generic edge type any more.
_STRUCTURAL_RELATIONS: frozenset[str] = frozenset({
    "MENTIONED_TOGETHER",
    "SUBTOPIC_OF",
    "SIBLING_OF",
    "REFERENCES",
})


@dataclass(frozen=True, slots=True)
class CanonicalEntityMapping:
    canonical_entity_id: str
    canonical_name: str
    confidence: float


@dataclass(frozen=True, slots=True)
class GraphSyncPayload:
    note_id: str
    note_title: str
    subject_id: str
    content_hash: str
    updated_at: str
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    resolved_entities: dict[str, CanonicalEntityMapping]
    embedding: list[float] | None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class GraphSyncService:
    """Synchronises NLP extraction results into the Apache AGE property graph.

    Uses block-level delta sync: on each call to sync_note_graph, the set of
    Block nodes currently in AGE is compared against the current block list.
    Only dirty (new or hash-changed) and deleted blocks trigger AGE writes.
    Unchanged blocks are left untouched, avoiding full delete-and-replace.
    """

    def __init__(
        self,
        *,
        session: Session,
        graph_name: str = "neuronote",
    ) -> None:
        self._session = session
        self._repository = GraphRepository(session)
        self._graph_name = graph_name

    def _iter_blocks(self, note_id: str) -> list[Block]:
        return list(
            self._session.execute(
                select(Block)
                .where(Block.note_id == note_id)
                .order_by(Block.block_index.asc()),
            ).scalars()
        )

    def _block_node_id(self, *, note_id: str, block_uid: str) -> str:
        return f"{note_id}:block:{block_uid}"

    def _upsert_note_and_subject(
        self,
        *,
        payload: GraphSyncPayload,
        now_iso: str,
    ) -> None:
        self._repository.upsert_node(
            label="Subject",
            node_id=payload.subject_id,
            properties={"name": payload.subject_id, "updated_at": now_iso},
            graph_name=self._graph_name,
        )
        note_props: dict[str, object] = {
            "name": payload.note_title,
            "source_note_id": payload.note_id,
            "content_hash": payload.content_hash,
            "updated_at": payload.updated_at,
            "created_at": now_iso,
        }
        self._repository.upsert_node(
            label="Note",
            node_id=payload.note_id,
            properties=note_props,
            graph_name=self._graph_name,
        )

    def _upsert_dirty_blocks(
        self,
        *,
        blocks: list[Block],
        block_node_ids_by_uid: dict[str, str],
        payload: GraphSyncPayload,
        now_iso: str,
        dirty_uids: set[str],
    ) -> None:
        dirty_blocks = [b for b in blocks if b.block_uid in dirty_uids]
        if not dirty_blocks:
            return

        block_node_props: list[dict[str, object]] = []
        for block in dirty_blocks:
            block_node_id = block_node_ids_by_uid[block.block_uid]
            block_node_props.append({
                "id": block_node_id,
                "block_uid": block.block_uid,
                "parent_block_uid": block.parent_block_uid,
                "sibling_order": block.sibling_order,
                "block_index": block.block_index,
                "content_hash": block.content_hash,
                "text": block.content_text,
                "source_note_id": payload.note_id,
                "created_at": now_iso,
                "updated_at": now_iso,
            })
        self._repository.upsert_nodes_batch(
            label="Block",
            nodes=block_node_props,
            graph_name=self._graph_name,
        )

        for block in dirty_blocks:
            block_node_id = block_node_ids_by_uid[block.block_uid]
            self._repository.upsert_typed_edge(
                source_label="Note",
                source_id=payload.note_id,
                target_label="Block",
                target_id=block_node_id,
                relation_type="CONTAINS",
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": 1.0,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )
            if block.parent_block_uid and block.parent_block_uid in block_node_ids_by_uid:
                parent_node_id = block_node_ids_by_uid[block.parent_block_uid]
                self._repository.upsert_typed_edge(
                    source_label="Block",
                    source_id=parent_node_id,
                    target_label="Block",
                    target_id=block_node_id,
                    relation_type="HAS_CHILD",
                    properties={
                        "source_note_id": payload.note_id,
                        "confidence": 1.0,
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                    graph_name=self._graph_name,
                )

    def _upsert_entity_nodes_and_note_edges(
        self,
        *,
        payload: GraphSyncPayload,
        now_iso: str,
    ) -> None:
        """Upsert Entity nodes for every extracted entity and the Note→Entity
        aggregate MENTIONS edge for each canonical entity.

        The deterministic pipeline emits concept entities without block-level
        positions, so MENTIONS edges are computed Note-level only — one edge
        per canonical entity at that entity's confidence.
        """
        if not payload.entities:
            return

        entity_node_props: list[dict[str, object]] = []
        note_entity_max_conf: dict[str, float] = {}
        for entity in payload.entities:
            resolved = payload.resolved_entities.get(entity.entity_id)
            canonical_id = (
                resolved.canonical_entity_id if resolved is not None else entity.entity_id
            )
            canonical_name = resolved.canonical_name if resolved is not None else entity.text
            entity_node_props.append({
                "id": canonical_id,
                "name": canonical_name,
                "kind": entity.label,
                "updated_at": now_iso,
            })
            conf = float(entity.confidence)
            if resolved is not None:
                conf = max(conf, float(resolved.confidence))
            if canonical_id not in note_entity_max_conf or conf > note_entity_max_conf[canonical_id]:
                note_entity_max_conf[canonical_id] = conf

        self._repository.upsert_nodes_batch(
            label="Entity",
            nodes=entity_node_props,
            graph_name=self._graph_name,
        )

        for canonical_id, best_conf in note_entity_max_conf.items():
            self._repository.upsert_typed_edge(
                source_label="Note",
                source_id=payload.note_id,
                target_label="Entity",
                target_id=canonical_id,
                relation_type="MENTIONS",
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": best_conf,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )

    def _upsert_block_refs(
        self,
        *,
        blocks: list[Block],
        block_node_ids_by_uid: dict[str, str],
        payload: GraphSyncPayload,
        now_iso: str,
        dirty_uids: set[str],
    ) -> None:
        dirty_blocks = [b for b in blocks if b.block_uid in dirty_uids]
        if not dirty_blocks:
            return

        block_repository = BlockRepository(self._session)
        ref_uids: set[str] = set()
        refs_by_source_uid: dict[str, list[str]] = {}

        for block in dirty_blocks:
            refs = block_repository.extract_block_refs_from_rich_content(dict(block.rich_content))
            if not refs:
                refs = block_repository.extract_block_refs(block.content_text)
            refs_by_source_uid[block.block_uid] = refs
            ref_uids.update(refs)

        if not ref_uids:
            return

        target_rows = block_repository.get_blocks_by_uid(list(ref_uids))
        target_node_ids = {
            row.block_uid: self._block_node_id(note_id=row.note_id, block_uid=row.block_uid)
            for row in target_rows
        }

        emitted_pairs: set[tuple[str, str]] = set()
        for source_block in dirty_blocks:
            source_node_id = block_node_ids_by_uid.get(source_block.block_uid)
            if source_node_id is None:
                continue
            for target_uid in refs_by_source_uid.get(source_block.block_uid, []):
                target_node_id = target_node_ids.get(target_uid)
                if target_node_id is None:
                    continue
                if source_node_id == target_node_id:
                    continue
                pair = (source_node_id, target_node_id)
                if pair in emitted_pairs:
                    continue
                emitted_pairs.add(pair)
                self._repository.upsert_typed_edge(
                    source_label="Block",
                    source_id=source_node_id,
                    target_label="Block",
                    target_id=target_node_id,
                    relation_type="REFERS_TO",
                    properties={
                        "source_note_id": payload.note_id,
                        "confidence": 1.0,
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                    graph_name=self._graph_name,
                )

    def _upsert_relations(self, *, payload: GraphSyncPayload, now_iso: str) -> None:
        for relation in payload.relations:
            if relation.predicate not in _STRUCTURAL_RELATIONS:
                _LOG.warning(
                    "Skipping relation with unknown predicate: note_id=%s predicate=%s",
                    payload.note_id, relation.predicate,
                )
                continue
            self._repository.upsert_node(
                label="Concept",
                node_id=relation.subject_id,
                properties={
                    "name": relation.subject_text,
                    "canonical_form": relation.subject_text,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )
            self._repository.upsert_node(
                label="Concept",
                node_id=relation.object_id,
                properties={
                    "name": relation.object_text,
                    "canonical_form": relation.object_text,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )
            self._repository.upsert_typed_edge(
                source_label="Concept",
                source_id=relation.subject_id,
                target_label="Concept",
                target_id=relation.object_id,
                relation_type=relation.predicate,
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": float(relation.confidence),
                    "predicate": relation.predicate,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )

    def sync_note_graph(self, payload: GraphSyncPayload) -> None:
        now_iso = _utc_now_iso()

        # Fetch current blocks from relational DB
        blocks = self._iter_blocks(payload.note_id)
        block_node_ids_by_uid: dict[str, str] = {
            b.block_uid: self._block_node_id(note_id=payload.note_id, block_uid=b.block_uid)
            for b in blocks
        }

        # Delta: compare current blocks against AGE state
        age_block_states = self._repository.fetch_block_states(
            note_id=payload.note_id,
            graph_name=self._graph_name,
        )
        current_uids = {b.block_uid for b in blocks}
        dirty_uids: set[str] = {
            b.block_uid
            for b in blocks
            if age_block_states.get(b.block_uid) != b.content_hash
        }
        deleted_uids: set[str] = set(age_block_states.keys()) - current_uids
        # All-unchanged fast path: blocks didn't change, but the pipeline
        # output (concepts, normalisation, structural relations) can still
        # change between runs — so refresh Note→Entity aggregate and the
        # Concept→Concept relation edges. Block nodes themselves stay put.
        if not dirty_uids and not deleted_uids:
            self._upsert_note_and_subject(payload=payload, now_iso=now_iso)
            self._repository.delete_note_mention_edges(
                note_id=payload.note_id,
                graph_name=self._graph_name,
            )
            self._upsert_entity_nodes_and_note_edges(payload=payload, now_iso=now_iso)
            self._repository.delete_concept_relation_edges(
                source_note_id=payload.note_id,
                graph_name=self._graph_name,
            )
            self._upsert_relations(payload=payload, now_iso=now_iso)
            if payload.embedding is not None:
                EmbeddingRepository(self._session).upsert_embedding(
                    item_id=payload.note_id,
                    item_type="note",
                    embedding=payload.embedding,
                )
            return

        # Remove stale Block nodes (DETACH DELETE cascades their edges)
        for uid in dirty_uids | deleted_uids:
            node_id = self._block_node_id(note_id=payload.note_id, block_uid=uid)
            self._repository.delete_block_node(
                block_node_id=node_id,
                graph_name=self._graph_name,
            )

        # Always upsert note-level nodes/edges (idempotent)
        self._upsert_note_and_subject(payload=payload, now_iso=now_iso)

        # Delete Note→Entity MENTIONS edges before recomputing aggregate
        self._repository.delete_note_mention_edges(
            note_id=payload.note_id,
            graph_name=self._graph_name,
        )

        # Sync Block nodes + entity/mention edges for dirty blocks
        self._upsert_dirty_blocks(
            blocks=blocks,
            block_node_ids_by_uid=block_node_ids_by_uid,
            payload=payload,
            now_iso=now_iso,
            dirty_uids=dirty_uids,
        )
        self._upsert_entity_nodes_and_note_edges(payload=payload, now_iso=now_iso)
        self._upsert_block_refs(
            blocks=blocks,
            block_node_ids_by_uid=block_node_ids_by_uid,
            payload=payload,
            now_iso=now_iso,
            dirty_uids=dirty_uids,
        )
        self._upsert_relations(payload=payload, now_iso=now_iso)

        if payload.embedding is not None:
            EmbeddingRepository(self._session).upsert_embedding(
                item_id=payload.note_id,
                item_type="note",
                embedding=payload.embedding,
            )
