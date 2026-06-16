from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.graph_cache import get_cached, get_note_version, set_cached
from app.db.models.note import Note
from app.db.repositories.graph_repository import EntityMention, GraphRepository
from app.services.graph_confidence import normalize_salience
from app.utils.text import (
    extract_wiki_link_titles,
    normalize_include_types,
    normalize_title_key,
)
from shared.contracts.python.v1.graph import LocalGraphResponse
from shared.contracts.python.v1.graph import LocalGraphEdge
from shared.contracts.python.v1.graph import LocalGraphFilters
from shared.contracts.python.v1.graph import LocalGraphMeta
from shared.contracts.python.v1.graph import LocalGraphNode


@dataclass(frozen=True, slots=True)
class LocalGraphQuery:
    note_id: str
    max_hops: int
    limit_nodes: int
    node_salience_threshold: float
    relationship_confidence_threshold: float
    include_types: list[str]


@dataclass(frozen=True, slots=True)
class _NoteSnapshot:
    note_id: str
    note_title: str
    content_text: str
    subject_id: str


class LocalGraphNoteNotFoundError(RuntimeError):
    pass


class LocalGraphService:
    def __init__(self, session: Session, *, graph_name: str = "neuronote") -> None:
        self._session = session
        self._graph_name = graph_name

    def _fetch_reachable_notes(self, seed_id: str, max_hops: int) -> list[_NoteSnapshot]:
        """Load notes reachable from seed_id within max_hops via wiki-links.

        Outgoing links are resolved with a targeted SQL fetch by normalized title.
        Incoming links (notes that link TO a frontier note) are found with an
        ILIKE scan per hop — O(n) for incoming but limited to reachable notes.
        """
        # note_id -> (note_title, content_text, subject_id)
        visited: dict[str, tuple[str, str, str]] = {}

        seed_row = self._session.execute(
            select(Note.note_id, Note.note_title, Note.content_text, Note.subject_id)
            .where(Note.note_id == seed_id)
        ).first()
        if seed_row is None:
            return []

        visited[str(seed_row[0])] = (
            str(seed_row[1]),
            str(seed_row[2]),
            str(seed_row[3]) if seed_row[3] else "inbox",
        )
        frontier_ids: set[str] = {str(seed_row[0])}

        for _hop in range(max_hops):
            if not frontier_ids:
                break

            outgoing_titles: set[str] = set()
            for fid in frontier_ids:
                _, content, _ = visited[fid]
                for t in extract_wiki_link_titles(content):
                    outgoing_titles.add(t)

            new_ids: set[str] = set()
            if outgoing_titles:
                out_rows = self._session.execute(
                    select(Note.note_id, Note.note_title, Note.content_text, Note.subject_id)
                    .where(func.lower(Note.note_title).in_(list(outgoing_titles)))
                    .where(Note.note_id.not_in(list(visited.keys())))
                ).all()
                for r in out_rows:
                    nid = str(r[0])
                    visited[nid] = (str(r[1]), str(r[2]), str(r[3]) if r[3] else "inbox")
                    new_ids.add(nid)

            frontier_titles = [normalize_title_key(visited[fid][0]) for fid in frontier_ids]
            if frontier_titles:
                like_clauses = [
                    Note.content_text.ilike(f"%[[{t}]]%") for t in frontier_titles
                ]
                in_rows = self._session.execute(
                    select(Note.note_id, Note.note_title, Note.content_text, Note.subject_id)
                    .where(or_(*like_clauses))
                    .where(Note.note_id.not_in(list(visited.keys())))
                ).all()
                for r in in_rows:
                    nid = str(r[0])
                    visited[nid] = (str(r[1]), str(r[2]), str(r[3]) if r[3] else "inbox")
                    new_ids.add(nid)

            frontier_ids = new_ids

        return [
            _NoteSnapshot(
                note_id=nid,
                note_title=title,
                content_text=content,
                subject_id=subject_id,
            )
            for nid, (title, content, subject_id) in visited.items()
        ]

    def get_local_graph(self, query: LocalGraphQuery) -> LocalGraphResponse:
        include_types = normalize_include_types(query.include_types)

        note_version = get_note_version(self._session, query.note_id)
        cache_key = (
            f"local:{query.note_id}:{query.max_hops}"
            f":{query.node_salience_threshold}:{query.relationship_confidence_threshold}"
            f":{query.limit_nodes}:{'|'.join(sorted(include_types))}:{note_version}"
        )
        cached = get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        include_type_set = set(include_types)

        notes = self._fetch_reachable_notes(query.note_id, query.max_hops)
        notes_by_id = {note.note_id: note for note in notes}
        if query.note_id not in notes_by_id:
            raise LocalGraphNoteNotFoundError(f"Note {query.note_id} was not found")

        title_index: dict[str, str] = {
            normalize_title_key(note.note_title): note.note_id for note in notes
        }

        # LINKS_TO edges from wiki-link parsing (SQL — always available)
        edge_map: dict[tuple[str, str, str], LocalGraphEdge] = {}
        if "relation" in include_type_set:
            for note in notes:
                for linked_title in extract_wiki_link_titles(note.content_text):
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

        # Note nodes (SQL)
        node_map: dict[str, LocalGraphNode] = {}
        if "note" in include_type_set:
            for note in notes:
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

        # Entity nodes + relation edges (AGE graph)
        if "entity" in include_type_set:
            graph_repo = GraphRepository(self._session)
            # MENTIONS fetched unfiltered (salience_floor=0): node inclusion is
            # decided here, against the *normalized* salience. Relationship edges
            # are gated in-query by the relationship-confidence threshold.
            graph_result = graph_repo.fetch_graph_for_notes(
                note_ids=list(notes_by_id.keys()),
                salience_floor=0.0,
                relation_min_confidence=query.relationship_confidence_threshold,
                graph_name=self._graph_name,
            )

            # Deduplicate entities by highest confidence across all source notes
            entity_best: dict[str, tuple[float, EntityMention]] = {}
            for mention in graph_result.mentions:
                if (mention.entity_id not in entity_best
                        or mention.confidence > entity_best[mention.entity_id][0]):
                    entity_best[mention.entity_id] = (mention.confidence, mention)

            for entity_id, (conf, mention) in entity_best.items():
                # Normalize raw salience onto the global 0–1 scale, then gate the
                # node on the node-salience threshold (decoupled from edges).
                normalized = normalize_salience(conf)
                if normalized < query.node_salience_threshold:
                    continue
                node_map[entity_id] = LocalGraphNode(
                    id=entity_id,
                    type="entity",
                    label=mention.entity_name,
                    confidence=normalized,
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
            if query.note_id in node_map and query.note_id not in kept_ids:
                kept_ids = [query.note_id, *kept_ids[:-1]]
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

        response = LocalGraphResponse(
            nodes=nodes,
            edges=edges,
            meta=LocalGraphMeta(
                root_note_id=query.note_id,
                applied_filters=LocalGraphFilters(
                    max_hops=query.max_hops,
                    limit_nodes=query.limit_nodes,
                    node_salience_threshold=query.node_salience_threshold,
                    relationship_confidence_threshold=query.relationship_confidence_threshold,
                    include_types=include_types,
                ),
                truncated=truncated,
            ),
        )
        set_cached(cache_key, response)
        return response
