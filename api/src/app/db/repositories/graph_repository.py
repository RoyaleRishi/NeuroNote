from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import cast

from sqlalchemy import text
from sqlalchemy.orm import Session

_GRAPH_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(slots=True)
class EntityMention:
    """An entity mentioned in a note, returned by fetch_graph_for_notes."""

    entity_id: str
    entity_name: str
    entity_kind: str
    source_note_id: str
    confidence: float


@dataclass(slots=True)
class RelationEdge:
    """A typed Concept→Concept edge, returned by fetch_graph_for_notes."""

    source_id: str
    target_id: str
    edge_type: str
    confidence: float
    source_note_id: str


@dataclass(slots=True)
class GraphFetchResult:
    """Aggregated AGE query result for a set of notes."""

    mentions: list[EntityMention] = field(default_factory=list)
    relations: list[RelationEdge] = field(default_factory=list)


class GraphRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        # Track which graph names have been confirmed to exist this session so
        # LOAD 'age' + SET search_path + graph-existence check only fire once.
        self._age_ready_graphs: set[str] = set()

    def _is_postgresql(self) -> bool:
        """Return True when the session is backed by PostgreSQL (AGE is available)."""
        try:
            from app.db.engine import get_engine
            return get_engine().dialect.name == "postgresql"
        except Exception:
            return False

    def _validate_graph_name(self, graph_name: str) -> None:
        if not _GRAPH_NAME_PATTERN.fullmatch(graph_name):
            raise ValueError(f"Invalid AGE graph name: {graph_name!r}")

    def _validate_label(self, label: str) -> None:
        if not _LABEL_PATTERN.fullmatch(label):
            raise ValueError(f"Invalid label: {label!r}")

    def _cypher_map_literal(self, properties: dict[str, object]) -> str:
        items: list[str] = []
        for key, value in properties.items():
            self._validate_label(key)
            items.append(f"{key}: {json.dumps(value)}")
        return "{" + ", ".join(items) + "}"

    def _exec_cypher(self, graph_name: str, query: str) -> list:
        """Execute a Cypher query using exec_driver_sql with no parameters.

        AGE requires graph_name and query to be literal SQL string constants —
        bound parameters ($1/$2) are rejected at plan time with "a name constant
        is expected".  Both values are therefore embedded directly in the SQL.

        Dollar-quoting ($$ ... $$) handles the Cypher query so single-quotes in
        user content don't break the SQL string.

        exec_driver_sql bypasses SQLAlchemy's _pyformat_pattern scanner (which
        text() applies at compile time).  Passing parameters=None tells psycopg3
        to skip its own placeholder-scan step and send the SQL to PostgreSQL
        verbatim — so %(name)s patterns in user content are never mistaken for
        bind parameters by either layer.
        """
        sql = (
            "SELECT * FROM ag_catalog.cypher("
            f"'{graph_name}', "
            f"$${query}$$"
            ") AS (value ag_catalog.agtype)"
        )
        # psycopg3 still scans the SQL for %-style placeholders even with
        # parameters=None, so a literal "%" inside user content (e.g. "25%
        # tuition") trips "incomplete placeholder". Escape to "%%" so the
        # driver passes a single "%" through to PostgreSQL untouched.
        sql = sql.replace("%", "%%")
        conn = self._session.connection()
        return list(conn.exec_driver_sql(sql, None).all())

    def ensure_graph_exists(self, *, graph_name: str = "neuronote") -> None:
        self._validate_graph_name(graph_name)

        if graph_name in self._age_ready_graphs:
            return  # Already set up for this session — skip the 3 round-trips.

        self._session.execute(text("LOAD 'age'"))
        self._session.execute(text('SET search_path = ag_catalog, "$user", public'))

        graph_exists = self._session.execute(
            text(
                """
                SELECT 1
                FROM ag_catalog.ag_graph
                WHERE name = :graph_name
                LIMIT 1
                """
            ),
            {"graph_name": graph_name},
        ).first()

        if graph_exists is None:
            self._session.execute(
                text("SELECT ag_catalog.create_graph(:graph_name)"),
                {"graph_name": graph_name},
            )

        self._age_ready_graphs.add(graph_name)

    def upsert_nodes_batch(
        self,
        *,
        label: str,
        nodes: list[dict[str, object]],
        graph_name: str = "neuronote",
    ) -> None:
        """Upsert multiple nodes of the same label in a single AGE UNWIND query.

        Each dict in `nodes` must contain an ``id`` key used as the MERGE key;
        all other keys become node properties.
        Reduces n individual round-trips down to 1 for homogeneous node batches.
        Falls back to individual upserts for a single-node list to keep call
        sites simple.
        """
        if not nodes:
            return
        if len(nodes) == 1:
            row = nodes[0]
            node_id = str(row["id"])
            self.upsert_node(label=label, node_id=node_id, properties=row, graph_name=graph_name)
            return

        self._validate_label(label)
        self.ensure_graph_exists(graph_name=graph_name)

        row_literals = ", ".join(self._cypher_map_literal(row) for row in nodes)
        query = f"""
        UNWIND [{row_literals}] AS row
        MERGE (n:{label} {{id: row.id}})
        SET n += row
        RETURN count(n)
        """
        self._exec_cypher(graph_name, query)

    def upsert_node(
        self,
        *,
        label: str,
        node_id: str,
        properties: dict[str, object],
        graph_name: str = "neuronote",
    ) -> None:
        self._validate_label(label)
        self.ensure_graph_exists(graph_name=graph_name)

        node_id_json = json.dumps(node_id)
        properties_literal = self._cypher_map_literal(properties)
        query = f"""
        MERGE (n:{label} {{id: {node_id_json}}})
        SET n += {properties_literal}
        RETURN n
        """

        self._exec_cypher(graph_name, query)

    def upsert_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str,
        confidence: float,
        graph_name: str = "neuronote",
    ) -> None:
        self.upsert_typed_edge(
            source_label="Concept",
            source_id=source_id,
            target_label="Concept",
            target_id=target_id,
            relation_type=relation_type,
            properties={"confidence": float(confidence)},
            graph_name=graph_name,
        )

    def upsert_typed_edge(
        self,
        *,
        source_label: str,
        source_id: str,
        target_label: str,
        target_id: str,
        relation_type: str,
        properties: dict[str, object] | None = None,
        graph_name: str = "neuronote",
    ) -> None:
        self._validate_label(source_label)
        self._validate_label(target_label)
        self._validate_label(relation_type)
        self.ensure_graph_exists(graph_name=graph_name)

        source_id_json = json.dumps(source_id)
        target_id_json = json.dumps(target_id)
        relation_properties = self._cypher_map_literal(properties or {})
        query = f"""
        MERGE (a:{source_label} {{id: {source_id_json}}})
        MERGE (b:{target_label} {{id: {target_id_json}}})
        MERGE (a)-[r:{relation_type}]->(b)
        SET r += {relation_properties}
        RETURN r
        """

        self._exec_cypher(graph_name, query)

    def upsert_typed_edges_batch(
        self,
        *,
        source_label: str,
        target_label: str,
        relation_type: str,
        edges: list[dict[str, object]],
        graph_name: str = "neuronote",
    ) -> None:
        """Upsert N edges that share the same source label, target label, and
        relation type in a single AGE UNWIND query.

        Each dict in ``edges`` must contain ``source_id``, ``target_id``, and a
        ``properties`` mapping (the edge property bag that ``SET r += `` will
        receive).

        Reduces N round-trips to 1 for homogeneous edge batches; degrades to
        the single-edge path when ``len(edges) <= 1`` so call sites stay simple.
        """
        if not edges:
            return
        if len(edges) == 1:
            row = edges[0]
            self.upsert_typed_edge(
                source_label=source_label,
                source_id=str(row["source_id"]),
                target_label=target_label,
                target_id=str(row["target_id"]),
                relation_type=relation_type,
                properties=dict(cast("dict[str, object]", row.get("properties") or {})),
                graph_name=graph_name,
            )
            return

        self._validate_label(source_label)
        self._validate_label(target_label)
        self._validate_label(relation_type)
        self.ensure_graph_exists(graph_name=graph_name)

        # Determine the property key set from the first row. Apache AGE's Cypher
        # implementation rejects `SET r += row.properties` when `row.properties`
        # is a nested-map projection (it expects a literal map). We work around
        # this by flattening properties into the row literal and emitting an
        # explicit `SET r.<key> = row.<key>` chain — same shape AGE accepts for
        # `upsert_nodes_batch` (which sets `n += row` against a flat row).
        first_props = dict(cast("dict[str, object]", edges[0].get("properties") or {}))
        property_keys = list(first_props.keys())

        # Defense in depth: property keys are substituted into raw Cypher as
        # `row.<key>` field accesses, so they must be safe identifiers.
        for key in property_keys:
            self._validate_label(key)

        # Defensive: every row in a batch must carry the same property key set,
        # otherwise the per-key SET assignments would silently write missing
        # keys as NULL. Today's call sites always pass homogeneous bags, but
        # validate so future regressions surface loudly.
        expected_keys = set(property_keys)
        for idx, row in enumerate(edges):
            row_keys = set(cast("dict[str, object]", row.get("properties") or {}).keys())
            if row_keys != expected_keys:
                raise ValueError(
                    "upsert_typed_edges_batch: heterogeneous property keys in "
                    f"batch (row 0 keys={sorted(expected_keys)}, "
                    f"row {idx} keys={sorted(row_keys)})"
                )

        row_literals: list[str] = []
        for row in edges:
            flat: dict[str, object] = {
                "source_id": str(row["source_id"]),
                "target_id": str(row["target_id"]),
            }
            props = row.get("properties") or {}
            for key in property_keys:
                flat[key] = props[key]  # type: ignore[index]
            row_literals.append(self._cypher_map_literal(flat))

        set_clause = ", ".join(f"r.{key} = row.{key}" for key in property_keys)
        # If there are no properties (unlikely for current call sites), skip the
        # SET clause entirely — MERGE alone is sufficient.
        set_line = f"SET {set_clause}" if set_clause else ""

        query = f"""
        UNWIND [{", ".join(row_literals)}] AS row
        MERGE (a:{source_label} {{id: row.source_id}})
        MERGE (b:{target_label} {{id: row.target_id}})
        MERGE (a)-[r:{relation_type}]->(b)
        {set_line}
        RETURN count(r)
        """
        self._exec_cypher(graph_name, query)

    def delete_source_artifacts(
        self,
        *,
        source_note_id: str,
        graph_name: str = "neuronote",
    ) -> None:
        self.ensure_graph_exists(graph_name=graph_name)
        source_json = json.dumps(source_note_id)

        delete_edges_query = f"""
        MATCH ()-[r]-()
        WHERE r.source_note_id = {source_json}
        DELETE r
        RETURN 1
        """
        self._exec_cypher(graph_name, delete_edges_query)

        delete_nodes_query = f"""
        MATCH (n)
        WHERE n.source_note_id = {source_json}
        DETACH DELETE n
        RETURN 1
        """
        self._exec_cypher(graph_name, delete_nodes_query)

    def fetch_local_neighborhood(
        self,
        *,
        node_id: str,
        max_hops: int = 2,
        limit: int = 50,
        graph_name: str = "neuronote",
    ) -> list[str]:
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        self.ensure_graph_exists(graph_name=graph_name)
        node_id_json = json.dumps(node_id)
        query = f"""
        MATCH p = (n {{id: {node_id_json}}})-[*1..{max_hops}]-(m)
        RETURN p
        LIMIT {limit}
        """

        rows = self._exec_cypher(graph_name, query)
        return [str(row[0]) for row in rows]

    # ------------------------------------------------------------------
    # AGE agtype helpers
    # ------------------------------------------------------------------

    def _parse_agtype_map(self, value: object) -> dict:
        """Parse an AGE agtype map return value to a Python dict.

        AGE RETURN {key: val} expressions serialise to standard JSON
        when converted to str, so json.loads() works directly.
        """
        return json.loads(str(value))

    # ------------------------------------------------------------------
    # Write helpers for delta sync
    # ------------------------------------------------------------------

    def delete_block_node(
        self,
        *,
        block_node_id: str,
        graph_name: str = "neuronote",
    ) -> None:
        """DETACH DELETE a single Block node (cascades all its edges)."""
        self.ensure_graph_exists(graph_name=graph_name)
        node_id_json = json.dumps(block_node_id)
        query = (
            f"MATCH (b:Block {{id: {node_id_json}}}) "
            f"DETACH DELETE b "
            f"RETURN 1"
        )
        self._exec_cypher(graph_name, query)

    def delete_note_mention_edges(
        self,
        *,
        note_id: str,
        graph_name: str = "neuronote",
    ) -> None:
        """Delete all Note→Entity MENTIONS edges for a note (to recompute aggregate)."""
        self.ensure_graph_exists(graph_name=graph_name)
        note_id_json = json.dumps(note_id)
        query = (
            f"MATCH (n:Note {{id: {note_id_json}}})-[r:MENTIONS]->(:Entity) "
            f"DELETE r "
            f"RETURN 1"
        )
        self._exec_cypher(graph_name, query)

    def delete_concept_relation_edges(
        self,
        *,
        source_note_id: str,
        graph_name: str = "neuronote",
    ) -> None:
        """Delete Concept→Concept edges sourced from a note.

        Used by ``sync_note_graph`` before re-emitting relations so stale
        edges from a previous pipeline run don't accumulate. Scoped to
        ``source_note_id`` so unrelated tenants/notes are unaffected.
        """
        self.ensure_graph_exists(graph_name=graph_name)
        source_json = json.dumps(source_note_id)
        query = (
            f"MATCH (:Concept)-[r]->(:Concept) "
            f"WHERE r.source_note_id = {source_json} "
            f"DELETE r "
            f"RETURN 1"
        )
        self._exec_cypher(graph_name, query)

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def fetch_block_states(
        self,
        *,
        note_id: str,
        graph_name: str = "neuronote",
    ) -> dict[str, str]:
        """Return {block_uid: content_hash} for all Block nodes of a note in AGE."""
        if not self._is_postgresql():
            return {}
        self.ensure_graph_exists(graph_name=graph_name)
        note_id_json = json.dumps(note_id)
        query = (
            f"MATCH (b:Block {{source_note_id: {note_id_json}}}) "
            f"RETURN {{block_uid: b.block_uid, content_hash: b.content_hash}}"
        )
        rows = self._exec_cypher(graph_name, query)
        result: dict[str, str] = {}
        for row in rows:
            data = self._parse_agtype_map(row[0])
            uid = data.get("block_uid")
            chash = data.get("content_hash")
            if isinstance(uid, str) and isinstance(chash, str):
                result[uid] = chash
        return result

    def fetch_graph_for_notes(
        self,
        *,
        note_ids: list[str],
        min_confidence: float = 0.0,
        graph_name: str = "neuronote",
    ) -> GraphFetchResult:
        """Fetch entity mentions and concept relation edges for a set of notes.

        Runs two Cypher queries:
          1. Note→Entity MENTIONS (note-level aggregate edges)
          2. Concept→Concept edges in one pass — note-scoped structural edges
             (filtered by source_note_id) OR durable meta edges (IS_A / SYNONYM_OF,
             no source_note_id) between concepts these notes mention, so the
             semantic hierarchy renders alongside the note-scoped structure.
        """
        if not note_ids or not self._is_postgresql():
            return GraphFetchResult()

        self.ensure_graph_exists(graph_name=graph_name)
        note_ids_json = json.dumps(note_ids)
        min_conf_json = json.dumps(min_confidence)

        # Query 1: entity mentions via Note→Entity MENTIONS edges
        mentions_query = (
            f"MATCH (n:Note)-[r:MENTIONS]->(e:Entity) "
            f"WHERE n.id IN {note_ids_json} AND r.confidence >= {min_conf_json} "
            f"RETURN {{entity_id: e.id, name: e.name, kind: e.kind, "
            f"source_note_id: n.id, confidence: r.confidence}}"
        )
        mentions: list[EntityMention] = []
        for row in self._exec_cypher(graph_name, mentions_query):
            d = self._parse_agtype_map(row[0])
            mentions.append(EntityMention(
                entity_id=str(d.get("entity_id", "")),
                entity_name=str(d.get("name", "")),
                entity_kind=str(d.get("kind", "concept")),
                source_note_id=str(d.get("source_note_id", "")),
                confidence=float(d.get("confidence", 0.0)),
            ))

        # Query 2: Concept→Concept edges — in ONE round-trip, both the note-scoped
        # structural edges AND the durable meta edges (IS_A / SYNONYM_OF). Durable
        # edges carry no source_note_id, so they're matched by concept membership
        # (both endpoints mentioned by these notes); without them the semantic
        # hierarchy would be persisted but never rendered.
        mentioned_ids = sorted({m.entity_id for m in mentions if m.entity_id})
        ids_json = json.dumps(mentioned_ids)
        relations_query = (
            f"MATCH (c1:Concept)-[r]->(c2:Concept) "
            f"WHERE (r.source_note_id IN {note_ids_json}) "
            f"OR (r.source_note_id IS NULL "
            f"AND c1.id IN {ids_json} AND c2.id IN {ids_json} "
            f"AND r.confidence >= {min_conf_json}) "
            f"RETURN {{source_id: c1.id, target_id: c2.id, type: type(r), "
            f"confidence: r.confidence, source_note_id: r.source_note_id}}"
        )
        relations: list[RelationEdge] = []
        for row in self._exec_cypher(graph_name, relations_query):
            d = self._parse_agtype_map(row[0])
            relations.append(RelationEdge(
                source_id=str(d.get("source_id", "")),
                target_id=str(d.get("target_id", "")),
                edge_type=str(d.get("type", "RELATED_TO")),
                confidence=float(d.get("confidence", 0.0)),
                source_note_id=str(d.get("source_note_id") or ""),
            ))

        return GraphFetchResult(mentions=mentions, relations=relations)

