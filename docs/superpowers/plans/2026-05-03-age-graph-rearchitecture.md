# AGE Graph Rearchitecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AGE the single source of truth for graph state — graph reads query AGE directly, graph writes are incremental at the block level.

**Architecture:** `GraphRepository` gains two read methods and two write helpers. `GraphSyncService` replaces delete-and-replace with a block-level delta algorithm (skip unchanged blocks, delete+re-sync dirty ones). `LocalGraphService` and `GlobalGraphService` drop the NLP pipeline and call `fetch_graph_for_notes` instead. `StartupBackfillService` pre-filters notes against AGE before queueing.

**Tech Stack:** Apache AGE (openCypher via `ag_catalog.cypher()`), FastAPI, SQLAlchemy (sync), Python 3.12, pytest. Integration tests require PostgreSQL + AGE — run via `make compose-test` or set `TEST_DATABASE_URL`.

---

## Spec

`docs/superpowers/specs/2026-05-03-age-graph-rearchitecture-design.md`

---

## File Map

| File | Change |
|---|---|
| `api/src/app/db/repositories/graph_repository.py` | Add `EntityMention`, `RelationEdge`, `GraphFetchResult` dataclasses; add `_parse_agtype_map`, `delete_block_node`, `delete_note_mention_edges`, `fetch_block_states`, `fetch_graph_for_notes` |
| `api/src/app/services/graph_sync_service.py` | Replace delete-and-replace with block-level delta; add `_upsert_note_and_subject`, `_upsert_dirty_blocks`; update `_upsert_mentions` and `_upsert_block_refs` to accept `dirty_uids` |
| `api/src/app/services/local_graph_service.py` | Remove `NoteNlpPipeline`; add `graph_name` param; replace extraction loop with `fetch_graph_for_notes` |
| `api/src/app/services/global_graph_service.py` | Same as local |
| `api/src/app/routes/graph.py` | Add `get_current_user` dependency to both routes; pass `graph_name` to services |
| `api/src/app/services/startup_backfill_service.py` | Add `_filter_stale_notes` AGE pre-filter |
| `tests/unit/test_local_graph_service.py` | Remove `test_local_graph_service_includes_semantic_relation_edges` (requires AGE, moves to integration) |
| `tests/integration/test_graph_sync_delta.py` | New: delta sync correctness tests |
| `tests/integration/test_graph_read_age.py` | New: AGE-backed graph service tests |
| `tests/integration/test_startup_backfill_age.py` | New: AGE-aware backfill pre-filter tests |

---

## Task Dependency

```
Task 1 (serial, foundational)
    ↓
Tasks 2, 3, 4 (parallel — independent files)
    ↓
Task 5 (serial cleanup)
```

---

## Task 1: GraphRepository — AGE Read Methods + Write Helpers

**Files:**
- Modify: `api/src/app/db/repositories/graph_repository.py`
- Test: `tests/integration/test_graph_sync_delta.py` (partial — read method tests only)

- [ ] **Step 1: Write failing integration tests for the new read methods**

Create `tests/integration/test_graph_sync_delta.py`:

```python
"""Integration tests for AGE graph delta sync.

Run against PostgreSQL+AGE via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_GRAPH = "nn_user_test0001"


def _note_payload(note_id: str, title: str, text: str) -> dict:
    return {
        "note_id": note_id,
        "note_title": title,
        "subject_id": "inbox",
        "tags": [],
        "is_pinned": False,
        "is_archived": False,
        "content_json": {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        ]},
        "content_text": text,
        "updated_at": "2026-05-03T10:00:00Z",
    }


def test_fetch_block_states_returns_empty_for_unsynced_note(db_session) -> None:
    from app.db.repositories.graph_repository import GraphRepository
    repo = GraphRepository(db_session)
    states = repo.fetch_block_states(note_id="nonexistent-note", graph_name=_GRAPH)
    assert states == {}


def test_fetch_block_states_returns_correct_hash_after_upsert(db_session) -> None:
    from app.db.repositories.graph_repository import GraphRepository
    repo = GraphRepository(db_session)
    repo.upsert_node(
        label="Block",
        node_id="delta-note1:block:b1",
        properties={
            "block_uid": "b1",
            "source_note_id": "delta-note1",
            "content_hash": "hash-abc",
            "text": "hello",
            "block_index": 0,
            "created_at": "2026-05-03T10:00:00Z",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    db_session.commit()

    states = repo.fetch_block_states(note_id="delta-note1", graph_name=_GRAPH)
    assert states == {"b1": "hash-abc"}


def test_fetch_graph_for_notes_returns_empty_when_no_data(db_session) -> None:
    from app.db.repositories.graph_repository import GraphRepository
    repo = GraphRepository(db_session)
    result = repo.fetch_graph_for_notes(
        note_ids=["no-such-note"],
        min_confidence=0.0,
        graph_name=_GRAPH,
    )
    assert result.mentions == []
    assert result.relations == []


def test_fetch_graph_for_notes_returns_mentions_and_relations(db_session) -> None:
    from app.db.repositories.graph_repository import GraphRepository
    repo = GraphRepository(db_session)
    # Seed: Note node, Entity node, Note→Entity MENTIONS edge
    repo.upsert_node(label="Note", node_id="fetch-note1",
        properties={"source_note_id": "fetch-note1", "name": "Test Note",
                    "updated_at": "2026-05-03T10:00:00Z"},
        graph_name=_GRAPH)
    repo.upsert_node(label="Entity", node_id="concept-python",
        properties={"name": "Python", "kind": "concept", "updated_at": "2026-05-03T10:00:00Z"},
        graph_name=_GRAPH)
    repo.upsert_typed_edge(
        source_label="Note", source_id="fetch-note1",
        target_label="Entity", target_id="concept-python",
        relation_type="MENTIONS",
        properties={"source_note_id": "fetch-note1", "confidence": 0.9,
                    "created_at": "2026-05-03T10:00:00Z"},
        graph_name=_GRAPH,
    )
    # Seed: Concept nodes + typed edge
    repo.upsert_node(label="Concept", node_id="concept-python",
        properties={"name": "Python", "updated_at": "2026-05-03T10:00:00Z"},
        graph_name=_GRAPH)
    repo.upsert_node(label="Concept", node_id="concept-django",
        properties={"name": "Django", "updated_at": "2026-05-03T10:00:00Z"},
        graph_name=_GRAPH)
    repo.upsert_typed_edge(
        source_label="Concept", source_id="concept-python",
        target_label="Concept", target_id="concept-django",
        relation_type="USES",
        properties={"source_note_id": "fetch-note1", "confidence": 0.85,
                    "predicate": "USES", "created_at": "2026-05-03T10:00:00Z"},
        graph_name=_GRAPH,
    )
    db_session.commit()

    result = repo.fetch_graph_for_notes(
        note_ids=["fetch-note1"], min_confidence=0.0, graph_name=_GRAPH
    )

    entity_ids = {m.entity_id for m in result.mentions}
    assert "concept-python" in entity_ids

    rel_keys = {(r.source_id, r.target_id, r.edge_type) for r in result.relations}
    assert ("concept-python", "concept-django", "USES") in rel_keys
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py::test_fetch_block_states_returns_empty_for_unsynced_note tests/integration/test_graph_sync_delta.py::test_fetch_block_states_returns_correct_hash_after_upsert tests/integration/test_graph_sync_delta.py::test_fetch_graph_for_notes_returns_empty_when_no_data tests/integration/test_graph_sync_delta.py::test_fetch_graph_for_notes_returns_mentions_and_relations -v
```

Expected: `ERRORS` — `fetch_block_states`, `fetch_graph_for_notes` not yet defined.

- [ ] **Step 3: Add dataclasses and new methods to `graph_repository.py`**

At the top of `api/src/app/db/repositories/graph_repository.py`, after the existing imports, add:

```python
from dataclasses import dataclass, field


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


@dataclass
class GraphFetchResult:
    """Aggregated AGE query result for a set of notes."""
    mentions: list[EntityMention] = field(default_factory=list)
    relations: list[RelationEdge] = field(default_factory=list)
```

Then inside the `GraphRepository` class, add these four methods after `fetch_local_neighborhood`:

```python
def _parse_agtype_map(self, value: object) -> dict:
    """Parse an AGE agtype map return value to a Python dict.

    AGE RETURN {key: val} expressions serialise to standard JSON
    when converted to str, so json.loads() works directly.
    """
    return json.loads(str(value))

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

def fetch_block_states(
    self,
    *,
    note_id: str,
    graph_name: str = "neuronote",
) -> dict[str, str]:
    """Return {block_uid: content_hash} for all Block nodes of a note in AGE."""
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
) -> "GraphFetchResult":
    """Fetch entity mentions and concept relation edges for a set of notes.

    Runs two Cypher queries:
      1. Note→Entity MENTIONS (note-level aggregate edges)
      2. Concept→Concept typed edges whose source_note_id is in note_ids
    """
    if not note_ids:
        return GraphFetchResult()

    self.ensure_graph_exists(graph_name=graph_name)
    note_ids_json = json.dumps(note_ids)
    min_conf_json = json.dumps(min_confidence)

    # Query 1: entity mentions
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

    # Query 2: concept→concept typed relation edges
    relations_query = (
        f"MATCH (c1:Concept)-[r]->(c2:Concept) "
        f"WHERE r.source_note_id IN {note_ids_json} "
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
            source_note_id=str(d.get("source_note_id", "")),
        ))

    return GraphFetchResult(mentions=mentions, relations=relations)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py::test_fetch_block_states_returns_empty_for_unsynced_note tests/integration/test_graph_sync_delta.py::test_fetch_block_states_returns_correct_hash_after_upsert tests/integration/test_graph_sync_delta.py::test_fetch_graph_for_notes_returns_empty_when_no_data tests/integration/test_graph_sync_delta.py::test_fetch_graph_for_notes_returns_mentions_and_relations -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Run full unit suite to check no regressions**

```bash
uv run --project api python -m pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add api/src/app/db/repositories/graph_repository.py tests/integration/test_graph_sync_delta.py
git commit -m "feat: add AGE read methods (fetch_block_states, fetch_graph_for_notes) to GraphRepository"
```

---

## Task 2: GraphSyncService — Block-Level Delta Sync

**Depends on:** Task 1 complete.

**Files:**
- Modify: `api/src/app/services/graph_sync_service.py`
- Test: `tests/integration/test_graph_sync_delta.py` (add delta-correctness tests)

- [ ] **Step 1: Add delta sync integration tests**

Append to `tests/integration/test_graph_sync_delta.py`:

```python
def _process_note(client: TestClient, note_id: str, text: str, title: str = "Test") -> None:
    """Create a note and trigger synchronous processing via the API."""
    client.put(f"/v1/notes/{note_id}", json=_note_payload(note_id, title, text))
    resp = client.post("/v1/process-note", json={
        "note_id": note_id,
        "content_text": text,
        "content_hash": "",
        "updated_at": "2026-05-03T10:00:00Z",
    })
    assert resp.status_code in (200, 202)
    # Poll until done (max 10s)
    import time
    job_id = resp.json().get("job_id")
    if job_id:
        for _ in range(20):
            s = client.get(f"/v1/process-note/status/{job_id}").json()
            if s.get("status") in ("completed", "failed"):
                break
            time.sleep(0.5)


def test_delta_sync_skips_unchanged_blocks(client: TestClient, db_session) -> None:
    """Re-syncing an unchanged note must not replace its Block nodes."""
    from app.db.repositories.graph_repository import GraphRepository

    note_id = "delta-unchanged-test"
    _process_note(client, note_id, "machine learning improves reasoning")

    # Capture the Block node IDs currently in AGE
    repo = GraphRepository(db_session)
    states_before = repo.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    assert states_before, "Expected blocks in AGE after first sync"

    # Re-process without changing content — all blocks should stay identical
    _process_note(client, note_id, "machine learning improves reasoning")

    states_after = repo.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    assert states_before == states_after, "Unchanged blocks should not be re-synced"


def test_delta_sync_only_updates_changed_block(client: TestClient, db_session) -> None:
    """Changing one block must update only that block's AGE state."""
    from app.db.repositories.graph_repository import GraphRepository
    from app.db.engine import get_session_factory
    from app.db.models.block import Block
    from sqlalchemy import select

    note_id = "delta-partial-change-test"
    _process_note(client, note_id, "first paragraph content here")

    repo = GraphRepository(db_session)
    states_before = repo.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    assert len(states_before) >= 1

    # Change content (new hash), re-process
    _process_note(client, note_id, "completely different paragraph content")

    states_after = repo.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    # Block hashes must differ (content changed)
    assert states_before != states_after
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py::test_delta_sync_skips_unchanged_blocks tests/integration/test_graph_sync_delta.py::test_delta_sync_only_updates_changed_block -v
```

Expected: FAIL (delta logic not yet implemented — `sync_note_graph` still calls `delete_source_artifacts`).

- [ ] **Step 3: Rewrite `graph_sync_service.py`**

Replace the entire file with the delta implementation. The full new file:

```python
from __future__ import annotations

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
    ExtractedEntityMention,
    ExtractedKeyphrase,
    ExtractedRelation,
)


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
    keyphrases: list[ExtractedKeyphrase]
    relations: list[ExtractedRelation]
    resolved_entities: dict[str, CanonicalEntityMapping]
    embedding: list[float] | None
    entity_mentions: list[ExtractedEntityMention]
    note_summary: str = ""


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
        if payload.note_summary:
            note_props["summary"] = payload.note_summary
        self._repository.upsert_node(
            label="Note",
            node_id=payload.note_id,
            properties=note_props,
            graph_name=self._graph_name,
        )
        self._repository.upsert_typed_edge(
            source_label="Note",
            source_id=payload.note_id,
            target_label="Subject",
            target_id=payload.subject_id,
            relation_type="BELONGS_TO",
            properties={
                "source_note_id": payload.note_id,
                "confidence": 1.0,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
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

        block_node_props = []
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

    def _upsert_mentions(
        self,
        *,
        blocks: list[Block],
        block_node_ids_by_index: dict[int, str],
        payload: GraphSyncPayload,
        now_iso: str,
        dirty_uids: set[str],
        dirty_block_indices: set[int],
    ) -> None:
        entity_by_id = {entity.entity_id: entity for entity in payload.entities}

        # Keyphrases: upsert nodes always, but MENTIONS edges only for dirty blocks
        concept_node_props: list[dict[str, object]] = [
            {
                "id": kp.phrase_id,
                "name": kp.text,
                "score": kp.score,
                "updated_at": now_iso,
            }
            for kp in payload.keyphrases
        ]
        self._repository.upsert_nodes_batch(
            label="Concept",
            nodes=concept_node_props,
            graph_name=self._graph_name,
        )

        for keyphrase in payload.keyphrases:
            self._repository.upsert_typed_edge(
                source_label="Concept",
                source_id=keyphrase.phrase_id,
                target_label="Subject",
                target_id=payload.subject_id,
                relation_type="APPEARS_IN",
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": float(keyphrase.score),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )
            for block in blocks:
                if block.block_uid not in dirty_uids:
                    continue  # skip unchanged blocks
                if keyphrase.text.lower() not in block.content_text.lower():
                    continue
                block_node_id = block_node_ids_by_index.get(block.block_index)
                if block_node_id is None:
                    continue
                self._repository.upsert_typed_edge(
                    source_label="Block",
                    source_id=block_node_id,
                    target_label="Concept",
                    target_id=keyphrase.phrase_id,
                    relation_type="MENTIONS",
                    properties={
                        "source_note_id": payload.note_id,
                        "confidence": float(keyphrase.score),
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                    graph_name=self._graph_name,
                )

        # Entity nodes: always upsert (MERGE, idempotent)
        entity_node_props: list[dict[str, object]] = []
        for entity in payload.entities:
            resolved = payload.resolved_entities.get(entity.entity_id)
            canonical_id = resolved.canonical_entity_id if resolved is not None else entity.entity_id
            canonical_name = resolved.canonical_name if resolved is not None else entity.text
            entity_node_props.append({
                "id": canonical_id,
                "name": canonical_name,
                "kind": entity.label,
                "updated_at": now_iso,
            })
        self._repository.upsert_nodes_batch(
            label="Entity",
            nodes=entity_node_props,
            graph_name=self._graph_name,
        )

        # Block→Entity MENTIONS: only for dirty block indices
        seen_mentions: set[tuple[str, str, int, int]] = set()
        for mention in payload.entity_mentions:
            if mention.block_index not in dirty_block_indices:
                continue  # skip mentions from unchanged blocks
            mention_block_node_id = block_node_ids_by_index.get(mention.block_index)
            if mention_block_node_id is None:
                continue
            source_entity = entity_by_id.get(mention.entity_id)
            if source_entity is None:
                continue

            resolved = payload.resolved_entities.get(source_entity.entity_id)
            canonical_id = resolved.canonical_entity_id if resolved is not None else source_entity.entity_id
            mention_key = (
                mention_block_node_id,
                canonical_id,
                mention.start_offset,
                mention.end_offset,
            )
            if mention_key in seen_mentions:
                continue
            seen_mentions.add(mention_key)

            mention_confidence = (
                max(float(source_entity.confidence), float(resolved.confidence))
                if resolved is not None
                else float(source_entity.confidence)
            )
            mention_confidence = max(mention_confidence, float(mention.confidence))
            self._repository.upsert_typed_edge(
                source_label="Block",
                source_id=mention_block_node_id,
                target_label="Entity",
                target_id=canonical_id,
                relation_type="MENTIONS",
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": mention_confidence,
                    "mention_text": mention.mention_text,
                    "start_offset": int(mention.start_offset),
                    "end_offset": int(mention.end_offset),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )

        # Note→Entity aggregate MENTIONS: always recompute (we deleted these before entering)
        note_entity_max_conf: dict[str, float] = {}
        for mention in payload.entity_mentions:
            source_entity = entity_by_id.get(mention.entity_id)
            if source_entity is None:
                continue
            resolved = payload.resolved_entities.get(source_entity.entity_id)
            canonical_id = resolved.canonical_entity_id if resolved is not None else source_entity.entity_id
            conf = float(source_entity.confidence)
            if resolved is not None:
                conf = max(conf, float(resolved.confidence))
            conf = max(conf, float(mention.confidence))
            if canonical_id not in note_entity_max_conf or conf > note_entity_max_conf[canonical_id]:
                note_entity_max_conf[canonical_id] = conf

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
        _TYPED_RELATIONS = frozenset(
            {"IS_A", "PART_OF", "CAUSES", "CONTRASTS_WITH", "USES", "PRODUCES", "RELATED_TO"}
        )
        for relation in payload.relations:
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
            edge_type = relation.predicate if relation.predicate in _TYPED_RELATIONS else "RELATED_TO"
            self._repository.upsert_typed_edge(
                source_label="Concept",
                source_id=relation.subject_id,
                target_label="Concept",
                target_id=relation.object_id,
                relation_type=edge_type,
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": float(relation.confidence),
                    "predicate": relation.predicate,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )
            self._repository.upsert_typed_edge(
                source_label="Concept",
                source_id=relation.subject_id,
                target_label="Subject",
                target_id=payload.subject_id,
                relation_type="APPEARS_IN",
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": float(relation.confidence),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                },
                graph_name=self._graph_name,
            )
            self._repository.upsert_typed_edge(
                source_label="Concept",
                source_id=relation.object_id,
                target_label="Subject",
                target_id=payload.subject_id,
                relation_type="APPEARS_IN",
                properties={
                    "source_note_id": payload.note_id,
                    "confidence": float(relation.confidence),
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
        block_node_ids_by_index: dict[int, str] = {
            b.block_index: block_node_ids_by_uid[b.block_uid]
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
        dirty_block_indices: set[int] = {
            b.block_index for b in blocks if b.block_uid in dirty_uids
        }

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
        self._upsert_mentions(
            blocks=blocks,
            block_node_ids_by_index=block_node_ids_by_index,
            payload=payload,
            now_iso=now_iso,
            dirty_uids=dirty_uids,
            dirty_block_indices=dirty_block_indices,
        )
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
```

- [ ] **Step 4: Run unit tests to check no regressions**

```bash
uv run --project api python -m pytest tests/unit/ -v
```

Expected: all pass (GraphSyncService is only tested via integration in Docker).

- [ ] **Step 5: Run delta integration tests**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/src/app/services/graph_sync_service.py tests/integration/test_graph_sync_delta.py
git commit -m "feat: block-level delta sync in GraphSyncService — skip unchanged blocks"
```

---

## Task 3: AGE-Backed Graph Services

**Depends on:** Task 1 complete.

**Files:**
- Modify: `api/src/app/services/local_graph_service.py`
- Modify: `api/src/app/services/global_graph_service.py`
- Modify: `api/src/app/routes/graph.py`
- Modify: `tests/unit/test_local_graph_service.py` (remove mock-pipeline test)
- Create: `tests/integration/test_graph_read_age.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/integration/test_graph_read_age.py`:

```python
"""Integration tests for AGE-backed graph services.

Requires PostgreSQL + AGE. Run via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_graph_read_age.py -v
"""
from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient


def _note_payload(note_id: str, title: str, text: str) -> dict:
    return {
        "note_id": note_id,
        "note_title": title,
        "subject_id": "inbox",
        "tags": [],
        "is_pinned": False,
        "is_archived": False,
        "content_json": {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        ]},
        "content_text": text,
        "updated_at": "2026-05-03T10:00:00Z",
    }


def _process_and_wait(client: TestClient, note_id: str, text: str, title: str = "Test") -> None:
    client.put(f"/v1/notes/{note_id}", json=_note_payload(note_id, title, text))
    resp = client.post("/v1/process-note", json={
        "note_id": note_id,
        "content_text": text,
        "content_hash": "",
        "updated_at": "2026-05-03T10:00:00Z",
    })
    assert resp.status_code in (200, 202)
    job_id = resp.json().get("job_id")
    if job_id:
        for _ in range(20):
            s = client.get(f"/v1/process-note/status/{job_id}").json()
            if s.get("status") in ("completed", "failed"):
                break
            time.sleep(0.5)


def test_local_graph_returns_entity_nodes_from_age(client: TestClient) -> None:
    _process_and_wait(
        client, "age-local-entity-test",
        "machine learning improves computer vision",
        "Entity Test"
    )
    resp = client.get("/v1/graph/local/age-local-entity-test", params={
        "include_types": "note,entity,relation",
        "min_confidence": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    entity_nodes = [n for n in body["nodes"] if n["type"] == "entity"]
    assert entity_nodes, "Expected entity nodes from AGE after processing"


def test_local_graph_returns_relation_edges_from_age(client: TestClient) -> None:
    _process_and_wait(
        client, "age-local-relation-test",
        "Python uses Django for web development",
        "Relation Test"
    )
    resp = client.get("/v1/graph/local/age-local-relation-test", params={
        "include_types": "note,entity,relation",
        "min_confidence": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    edge_types = {e["type"] for e in body["edges"]}
    # MENTIONS edges should appear (Note→Entity)
    assert "MENTIONS" in edge_types or len(body["nodes"]) > 1


def test_local_graph_still_returns_links_to_edges(client: TestClient) -> None:
    _process_and_wait(client, "age-links-root", "See [[Age Links Target]]", "Links Root")
    _process_and_wait(client, "age-links-target", "Target content", "Age Links Target")
    resp = client.get("/v1/graph/local/age-links-root", params={
        "include_types": "note,relation",
        "max_hops": 1,
    })
    assert resp.status_code == 200
    body = resp.json()
    edge_pairs = {(e["source"], e["target"], e["type"]) for e in body["edges"]}
    assert ("age-links-root", "age-links-target", "LINKS_TO") in edge_pairs


def test_global_graph_returns_entity_nodes_from_age(client: TestClient) -> None:
    _process_and_wait(
        client, "age-global-entity-test",
        "neural networks enable deep learning",
        "Global Entity Test"
    )
    resp = client.get("/v1/graph/global", params={
        "include_types": "note,entity,relation",
        "min_confidence": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body
    # At least our processed note should appear
    note_ids = {n["id"] for n in body["nodes"] if n["type"] == "note"}
    assert "age-global-entity-test" in note_ids
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_read_age.py -v
```

Expected: the entity/relation tests fail since graph services don't yet read from AGE.

- [ ] **Step 3: Remove the mock-pipeline test from unit tests**

In `tests/unit/test_local_graph_service.py`, remove the entire `test_local_graph_service_includes_semantic_relation_edges` function (it was added as a bugfix step but is now superseded by the AGE integration tests):

```python
# DELETE this entire function:
def test_local_graph_service_includes_semantic_relation_edges(
    configured_db: None,
) -> None:
    ...
```

Also remove the now-unused imports at the top:
```python
# REMOVE these three lines:
from unittest.mock import MagicMock
from app.nlp.types import ExtractedEntity, ExtractedRelation, NoteExtractionResult
```

- [ ] **Step 4: Rewrite `local_graph_service.py`**

Replace the entire file:

```python
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.graph_cache import get_cached, get_note_version, set_cached
from app.db.models.block import Block
from app.db.models.note import Note
from app.db.repositories.graph_repository import GraphRepository
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
    min_confidence: float
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

    @staticmethod
    def _normalize_title(value: str) -> str:
        return normalize_title_key(value)

    @staticmethod
    def _normalize_include_types(values: list[str]) -> list[str]:
        return normalize_include_types(values)

    @staticmethod
    def _extract_wiki_links(content_text: str) -> list[str]:
        return extract_wiki_link_titles(content_text)

    def _fetch_reachable_notes(self, seed_id: str, max_hops: int) -> list[_NoteSnapshot]:
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
                for t in self._extract_wiki_links(content):
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

            frontier_titles = [self._normalize_title(visited[fid][0]) for fid in frontier_ids]
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
        include_types = self._normalize_include_types(query.include_types)

        note_version = get_note_version(self._session, query.note_id)
        cache_key = (
            f"local:{query.note_id}:{query.max_hops}:{query.min_confidence}"
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
            self._normalize_title(note.note_title): note.note_id for note in notes
        }

        # LINKS_TO edges from wiki-link parsing (SQL — unchanged)
        edge_map: dict[tuple[str, str, str], LocalGraphEdge] = {}
        if "relation" in include_type_set:
            for note in notes:
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

        # Entity nodes + relation edges (AGE)
        if "entity" in include_type_set:
            graph_repo = GraphRepository(self._session)
            graph_result = graph_repo.fetch_graph_for_notes(
                note_ids=list(notes_by_id.keys()),
                min_confidence=query.min_confidence,
                graph_name=self._graph_name,
            )

            # Deduplicate entities by max confidence
            entity_best: dict[str, tuple[float, object]] = {}  # entity_id → (confidence, mention)
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
                # MENTIONS edges (Note→Entity)
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

                # Typed entity→entity edges
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
                    min_confidence=query.min_confidence,
                    include_types=include_types,
                ),
                truncated=truncated,
            ),
        )
        set_cached(cache_key, response)
        return response
```

- [ ] **Step 5: Rewrite `global_graph_service.py`**

Replace the entire file:

```python
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.graph_cache import get_cached, get_notes_version, set_cached
from app.db.models.note import Note
from app.db.models.note_tag import NoteTag
from app.db.models.tag import Tag
from app.db.repositories.graph_repository import GraphRepository
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

        # Note nodes + LINKS_TO edges (SQL)
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

        # Entity nodes + relation edges (AGE)
        if "entity" in include_type_set:
            note_ids = [n.note_id for n in notes]
            graph_repo = GraphRepository(self._session)
            graph_result = graph_repo.fetch_graph_for_notes(
                note_ids=note_ids,
                min_confidence=query.min_confidence,
                graph_name=self._graph_name,
            )

            entity_best: dict[str, tuple[float, object]] = {}
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
```

- [ ] **Step 6: Update `routes/graph.py` to pass `graph_name`**

Replace the entire file:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import UserContext, get_current_user
from app.db.tenant_session import get_tenant_session
from app.services.global_graph_service import GlobalGraphQuery, GlobalGraphService
from app.services.local_graph_service import LocalGraphNoteNotFoundError
from app.services.local_graph_service import LocalGraphQuery, LocalGraphService
from shared.contracts.python.v1.graph import GlobalGraphResponse
from shared.contracts.python.v1.graph import LocalGraphResponse

router = APIRouter()


@router.get("/graph/global", response_model=GlobalGraphResponse)
def get_global_graph(
    limit_nodes: int = Query(default=500, ge=1, le=2000),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    include_types: str = Query(default="note,entity,relation"),
    subject_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> GlobalGraphResponse:
    include_type_values = [item.strip() for item in include_types.split(",") if item.strip()]
    graph_name = f"nn_{user.schema_name}"
    return GlobalGraphService(session, graph_name=graph_name).get_global_graph(
        GlobalGraphQuery(
            limit_nodes=limit_nodes,
            min_confidence=min_confidence,
            include_types=include_type_values,
            subject_id=subject_id,
            tag=tag,
        )
    )


@router.get("/graph/local/{note_id}", response_model=LocalGraphResponse)
def get_local_graph(
    note_id: str,
    max_hops: int = Query(default=1, ge=1, le=2),
    limit_nodes: int = Query(default=80, ge=1, le=150),
    min_confidence: float = Query(default=0.35, ge=0.0, le=1.0),
    include_types: str = Query(default="note,entity,relation"),
    session: Session = Depends(get_tenant_session),
    user: UserContext = Depends(get_current_user),
) -> LocalGraphResponse:
    include_type_values = [item.strip() for item in include_types.split(",") if item.strip()]
    graph_name = f"nn_{user.schema_name}"
    try:
        return LocalGraphService(session, graph_name=graph_name).get_local_graph(
            LocalGraphQuery(
                note_id=note_id,
                max_hops=max_hops,
                limit_nodes=limit_nodes,
                min_confidence=min_confidence,
                include_types=include_type_values,
            )
        )
    except LocalGraphNoteNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
```

- [ ] **Step 7: Run unit tests**

```bash
uv run --project api python -m pytest tests/unit/ -v
```

Expected: all pass (existing graph service unit tests don't test AGE behaviour).

- [ ] **Step 8: Run AGE integration tests**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_read_age.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 9: Run existing graph API integration tests to check no regressions**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_api.py -v
```

Expected: all pass. (LINKS_TO tests pass because wiki-link logic is unchanged. Entity tests may now return empty if notes weren't processed — that is expected correct behaviour.)

- [ ] **Step 10: Commit**

```bash
git add \
  api/src/app/services/local_graph_service.py \
  api/src/app/services/global_graph_service.py \
  api/src/app/routes/graph.py \
  tests/unit/test_local_graph_service.py \
  tests/integration/test_graph_read_age.py
git commit -m "feat: AGE-backed graph services — read entities/relations from AGE, drop NLP re-extraction"
```

---

## Task 4: AGE-Aware Startup Backfill

**Depends on:** Task 1 complete.

**Files:**
- Modify: `api/src/app/services/startup_backfill_service.py`
- Create: `tests/integration/test_startup_backfill_age.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/integration/test_startup_backfill_age.py`:

```python
"""Integration tests for AGE-aware startup backfill pre-filter.

Requires PostgreSQL + AGE. Run via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_startup_backfill_age.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_filter_stale_notes_includes_unsynced_note(db_session) -> None:
    """A note with no Block nodes in AGE must be included in the stale set."""
    from app.db.repositories.note_repository import NoteRepository
    from app.services.startup_backfill_service import StartupBackfillService

    # Create a note in the relational DB only (no AGE sync)
    NoteRepository(db_session).upsert_note(
        note_id="backfill-unsynced",
        note_title="Unsynced Note",
        content_json={"type": "doc", "content": []},
        content_text="some content",
        updated_at="2026-05-03T10:00:00Z",
    )
    db_session.commit()

    service = StartupBackfillService()
    stale = service._filter_stale_notes(db_session, ["backfill-unsynced"])
    assert "backfill-unsynced" in stale


def test_filter_stale_notes_excludes_fully_synced_note(db_session) -> None:
    """A note whose all blocks are already in AGE with correct hashes must be skipped."""
    from app.db.repositories.graph_repository import GraphRepository
    from app.db.repositories.note_repository import NoteRepository
    from app.db.models.block import Block
    from app.services.startup_backfill_service import StartupBackfillService

    # Create note + block in relational DB
    NoteRepository(db_session).upsert_note(
        note_id="backfill-synced",
        note_title="Synced Note",
        content_json={"type": "doc", "content": []},
        content_text="content",
        updated_at="2026-05-03T10:00:00Z",
    )
    db_session.flush()

    # Manually create a matching Block node in AGE with the correct hash
    block_hash = "synced-content-hash-abc"
    repo = GraphRepository(db_session)
    repo.upsert_node(
        label="Block",
        node_id="backfill-synced:block:synced-b1",
        properties={
            "block_uid": "synced-b1",
            "source_note_id": "backfill-synced",
            "content_hash": block_hash,
            "text": "content",
            "block_index": 0,
            "created_at": "2026-05-03T10:00:00Z",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name="neuronote",
    )
    # Insert matching block in relational DB with same hash
    db_session.add(Block(
        note_id="backfill-synced",
        block_uid="synced-b1",
        block_index=0,
        content_text="content",
        content_hash=block_hash,
        rich_content={"type": "paragraph"},
        sibling_order=0,
    ))
    db_session.commit()

    service = StartupBackfillService()
    stale = service._filter_stale_notes(db_session, ["backfill-synced"])
    assert "backfill-synced" not in stale
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_startup_backfill_age.py -v
```

Expected: `AttributeError` — `_filter_stale_notes` not yet defined.

- [ ] **Step 3: Add `_filter_stale_notes` to `startup_backfill_service.py`**

In `startup_backfill_service.py`, add the following method to the `StartupBackfillService` class and update `run_note_reprocessing_backfill` to use it:

```python
def _filter_stale_notes(self, session: "Session", note_ids: list[str]) -> list[str]:
    """Return only note_ids that have missing or stale Block nodes in AGE.

    Falls back to returning all note_ids if AGE is unavailable.
    """
    try:
        from sqlalchemy.orm import Session as _Session
        from app.db.models.block import Block as _Block
        from app.db.repositories.graph_repository import GraphRepository
        from sqlalchemy import select as _select

        repo = GraphRepository(session)
        stale: list[str] = []
        for note_id in note_ids:
            age_states = repo.fetch_block_states(note_id=note_id, graph_name="neuronote")
            block_rows = session.execute(
                _select(_Block.block_uid, _Block.content_hash)
                .where(_Block.note_id == note_id)
            ).all()
            # Note is stale if any block is missing from AGE or has a different hash
            if any(age_states.get(str(uid)) != str(chash) for uid, chash in block_rows):
                stale.append(note_id)
        return stale
    except Exception:
        # AGE unavailable or other error — process all notes to be safe
        return note_ids
```

Also update `run_note_reprocessing_backfill` to call it. Replace the block that reads `note_ids` with:

```python
        session_factory = get_session_factory()
        with session_factory() as session:
            all_note_ids = NoteRepository(session).list_note_ids()
            note_ids = self._filter_stale_notes(session, all_note_ids)
```

Add the `Session` type annotation import at the top of the file:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlalchemy.orm import Session
```

- [ ] **Step 4: Run backfill integration tests**

```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_startup_backfill_age.py -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Run full unit suite**

```bash
uv run --project api python -m pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add \
  api/src/app/services/startup_backfill_service.py \
  tests/integration/test_startup_backfill_age.py
git commit -m "feat: AGE-aware startup backfill — skip notes with up-to-date block states"
```

---

## Task 5: Cleanup (Serial — after Tasks 2, 3, 4)

**Files:**
- Modify: `api/src/app/services/local_graph_service.py` (remove dead `BlockTextInput` import)
- Modify: `api/src/app/services/global_graph_service.py` (same)

- [ ] **Step 1: Remove dead imports from local_graph_service.py**

The `BlockTextInput` type from `app.nlp.types` is no longer used. Verify with:

```bash
grep -n "BlockTextInput\|NoteNlpPipeline\|EntityAliasRepository\|hashlib" \
  api/src/app/services/local_graph_service.py api/src/app/services/global_graph_service.py
```

Remove any lines found. The files should have already had these removed in Task 3 since we rewrote them in full — this step just confirms no stragglers.

- [ ] **Step 2: Run dead code scan**

```bash
uv run --project api python -m pytest tests/unit/ -v --tb=short
```

Expected: all pass.

- [ ] **Step 3: Full integration suite**

```bash
make compose-test
```

Expected: all pass.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: cleanup dead imports and verify full test suite passes after AGE rearchitecture"
```

---

## Running All Tests

**Unit tests (SQLite, no Docker):**
```bash
uv run --project api python -m pytest tests/unit/ -v
```

**Integration tests (PostgreSQL + AGE via Docker):**
```bash
make compose-test
```

**Individual integration test files:**
```bash
TEST_DATABASE_URL=postgresql://neuronote:neuronote@localhost:5432/neuronote \
  uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py \
    tests/integration/test_graph_read_age.py \
    tests/integration/test_startup_backfill_age.py -v
```
