from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.graph_cache import get_cached, get_notes_version, set_cached
from app.db.models.note import Note
from app.db.models.note_tag import NoteTag
from app.db.models.tag import Tag
from app.db.repositories.graph_repository import EntityMention, GraphRepository
from app.utils.text import (
    extract_wiki_link_titles,
    normalize_include_types,
    normalize_title_key,
)
from shared.contracts.python.v1.graph import GlobalGraphFilters
from shared.contracts.python.v1.graph import GlobalGraphMeta
from shared.contracts.python.v1.graph import GlobalGraphResponse
from shared.contracts.python.v1.graph import LocalGraphEdge
from shared.contracts.python.v1.graph import LocalGraphNode


@dataclass(frozen=True, slots=True)
class GlobalGraphQuery:
    limit_nodes: int
    min_confidence: float
    include_types: list[str]
    subject_id: str | None = None
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class _NoteSnapshot:
    note_id: str
    note_title: str
    content_text: str
    subject_id: str


class GlobalGraphService:
    def __init__(self, session: Session, *, graph_name: str = "neuronote") -> None:
        self._session = session
        self._graph_name = graph_name

    @staticmethod
    def _normalize_title(value: str) -> str:
        return normalize_title_key(value)

    @staticmethod
    def _normalize_include_types(values: list[str]) -> list[str]:
        return normalize_include_types(values)

    @staticmethod
    def _extract_wiki_links(content_text: str) -> list[str]:
        return extract_wiki_link_titles(content_text)

    def _list_notes(
        self,
        *,
        limit: int,
        subject_id: str | None = None,
        tag: str | None = None,
    ) -> list[_NoteSnapshot]:
        """Fetch most-recently-updated notes up to limit, filtered by subject/tag."""
        stmt = (
            select(Note.note_id, Note.note_title, Note.content_text, Note.subject_id)
            .order_by(desc(Note.updated_at))
            .limit(limit)
        )
        if subject_id:
            stmt = stmt.where(Note.subject_id == subject_id)
        if tag:
            stmt = stmt.where(
                Note.note_id.in_(
                    select(NoteTag.note_id)
                    .join(Tag, NoteTag.tag_id == Tag.id)
                    .where(Tag.name == tag)
                )
            )
        rows = self._session.execute(stmt).all()
        return [
            _NoteSnapshot(
                note_id=str(row[0]),
                note_title=str(row[1]),
                content_text=str(row[2]),
                subject_id=str(row[3]) if row[3] else "inbox",
            )
            for row in rows
        ]

    def get_global_graph(self, query: GlobalGraphQuery) -> GlobalGraphResponse:
        include_types = self._normalize_include_types(query.include_types)

        notes_version = get_notes_version(self._session)
        cache_key = (
            f"global:{query.limit_nodes}:{query.min_confidence}"
            f":{'|'.join(sorted(include_types))}"
            f":{query.subject_id or ''}:{query.tag or ''}:{notes_version}"
        )
        cached = get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        include_type_set = set(include_types)

        notes = self._list_notes(
            limit=query.limit_nodes * 2,
            subject_id=query.subject_id,
            tag=query.tag,
        )
        total_notes = len(notes)
        title_index: dict[str, str] = {
            self._normalize_title(n.note_title): n.note_id for n in notes
        }

        node_map: dict[str, LocalGraphNode] = {}
        edge_map: dict[tuple[str, str, str], LocalGraphEdge] = {}

        # Note nodes + LINKS_TO edges (SQL — always available)
        for note in notes:
            if "note" in include_type_set:
                node_map[note.note_id] = LocalGraphNode(
                    id=note.note_id,
                    type="note",
                    label=note.note_title,
                    confidence=None,
                    source_note_id=note.note_id,
                    metadata={
                        "note_id": note.note_id,
                        "subject_id": note.subject_id,
                        "content_preview": note.content_text[:140],
                    },
                )
            if "relation" in include_type_set:
                for linked_title in self._extract_wiki_links(note.content_text):
                    target_id = title_index.get(linked_title)
                    if target_id is None or target_id == note.note_id:
                        continue
                    key = (note.note_id, target_id, "LINKS_TO")
                    if key not in edge_map:
                        edge_map[key] = LocalGraphEdge(
                            id=f"{note.note_id}->LINKS_TO->{target_id}",
                            source=note.note_id,
                            target=target_id,
                            type="LINKS_TO",
                            confidence=1.0,
                            source_note_id=note.note_id,
                        )

        # Entity nodes + relation edges (AGE graph)
        if "entity" in include_type_set:
            note_ids = [n.note_id for n in notes]
            graph_repo = GraphRepository(self._session)
            graph_result = graph_repo.fetch_graph_for_notes(
                note_ids=note_ids,
                min_confidence=query.min_confidence,
                graph_name=self._graph_name,
            )

            # Deduplicate entities by highest confidence across all source notes
            entity_best: dict[str, tuple[float, EntityMention]] = {}
            for mention in graph_result.mentions:
                if (mention.entity_id not in entity_best
                        or mention.confidence > entity_best[mention.entity_id][0]):
                    entity_best[mention.entity_id] = (mention.confidence, mention)

            for entity_id, (conf, mention) in entity_best.items():
                node_map[entity_id] = LocalGraphNode(
                    id=entity_id,
                    type="entity",
                    label=mention.entity_name,
                    confidence=conf,
                    source_note_id=mention.source_note_id,
                    metadata={
                        "entity_id": entity_id,
                        "entity_label": mention.entity_kind,
                    },
                )

            if "relation" in include_type_set:
                # MENTIONS edges (Note→Entity), one per (note, entity) pair
                seen_mention_keys: set[tuple[str, str]] = set()
                for mention in graph_result.mentions:
                    if mention.entity_id not in node_map:
                        continue
                    pair = (mention.source_note_id, mention.entity_id)
                    if pair in seen_mention_keys:
                        continue
                    seen_mention_keys.add(pair)
                    key = (mention.source_note_id, mention.entity_id, "MENTIONS")
                    edge_map[key] = LocalGraphEdge(
                        id=f"{mention.source_note_id}->MENTIONS->{mention.entity_id}",
                        source=mention.source_note_id,
                        target=mention.entity_id,
                        type="MENTIONS",
                        confidence=mention.confidence,
                        source_note_id=mention.source_note_id,
                    )

                # Typed Concept→Concept relation edges
                for rel in graph_result.relations:
                    if rel.source_id not in node_map or rel.target_id not in node_map:
                        continue
                    key = (rel.source_id, rel.target_id, rel.edge_type)
                    if key not in edge_map:
                        edge_map[key] = LocalGraphEdge(
                            id=f"{rel.source_id}->{rel.edge_type}->{rel.target_id}",
                            source=rel.source_id,
                            target=rel.target_id,
                            type=rel.edge_type,
                            confidence=rel.confidence,
                            source_note_id=rel.source_note_id,
                        )

        nodes = sorted(node_map.values(), key=lambda item: (item.type, item.id))
        truncated = len(nodes) > query.limit_nodes

        if truncated:
            kept_ids = [node.id for node in nodes[: query.limit_nodes]]
            kept_id_set = set(kept_ids)
            nodes = [node_map[node_id] for node_id in kept_ids if node_id in node_map]
        else:
            kept_id_set = {node.id for node in nodes}

        edges = sorted(
            (
                edge
                for edge in edge_map.values()
                if edge.source in kept_id_set and edge.target in kept_id_set
            ),
            key=lambda item: (item.type, item.source, item.target, item.id),
        )

        response = GlobalGraphResponse(
            nodes=nodes,
            edges=edges,
            meta=GlobalGraphMeta(
                total_notes=total_notes,
                applied_filters=GlobalGraphFilters(
                    limit_nodes=query.limit_nodes,
                    min_confidence=query.min_confidence,
                    include_types=include_types,
                    subject_id=query.subject_id,
                    tag=query.tag,
                ),
                truncated=truncated,
            ),
        )
        set_cached(cache_key, response)
        return response
