# AGE Graph Rearchitecture

**Date:** 2026-05-03
**Status:** Approved

## Problem

The graph view services (`LocalGraphService`, `GlobalGraphService`) ignore the AGE graph entirely. On every `GET /v1/graph/*` request they re-run the full NLP pipeline from raw note text, discarding all pre-computed extraction results stored in AGE. Separately, `GraphSyncService` uses delete-and-replace semantics at the note level — every save wipes and re-creates every Block node and every edge, even for unchanged blocks.

Two consequences:
1. Edge-mode relations (extracted by the browser LLM and stored in AGE) never appear in the graph view.
2. A 100-block note with 1 changed block triggers full deletion and re-creation of all 100 blocks' AGE artifacts.

## Goal

Make AGE the single source of truth for graph state. Graph reads come from AGE. Graph writes are incremental at the block level.

## Architecture

```
Note saved
    ↓
GraphSyncService (write — incremental)
    ├── Query AGE: which of this note's blocks are already current?
    ├── Skip unchanged blocks (Block node exists with matching content_hash)
    ├── Delete + re-sync only dirty / new / removed blocks
    └── AGE is up to date

GET /v1/graph/* (read — AGE-backed)
    ├── GraphRepository: Cypher queries for nodes + edges
    └── Map AGE results → LocalGraphNode / LocalGraphEdge (contracts unchanged)

Startup backfill (AGE-aware)
    ├── Query AGE: which notes have missing or stale Block nodes?
    └── Queue only those — skip fully-synced notes
```

Three components change: `GraphSyncService` (write), `LocalGraphService` + `GlobalGraphService` (read), `StartupBackfillService` (startup). `GraphRepository` gets new read methods. All graph API contracts stay the same.

---

## Section 1: Write Path — Block-Level Delta Sync

### Algorithm

`GraphSyncService.sync_note_graph()` becomes:

```
1. Query AGE → fetch {block_uid: content_hash} for all Block nodes of this note
2. Diff against current blocks from payload:
   - unchanged = uid in AGE with matching hash  → skip entirely
   - dirty     = uid in AGE with different hash → DETACH DELETE + re-sync
   - new       = uid not in AGE                 → sync
   - deleted   = uid in AGE but not in payload  → DETACH DELETE
3. DETACH DELETE Block nodes for dirty + deleted (cascades all their edges)
4. Upsert always (idempotent): Note node, Subject node, BELONGS_TO edge
5. Upsert always: Entity/Concept nodes (MERGE — shared, cheap)
6. Create Block nodes + CONTAINS + HAS_CHILD + MENTIONS edges for new + dirty only
7. Upsert Concept→Concept relation edges (note-level, always re-merge)
8. Recompute Note→Entity MENTIONS aggregate from full NLP payload
```

**All-unchanged fast path:** Steps 3–8 skipped. Only steps 4 and 8 run (both idempotent upserts). Near-zero AGE cost for metadata-only saves.

### New GraphRepository method

`fetch_block_states(note_id: str, graph_name: str) -> dict[str, str]`

Single Cypher query: `MATCH (b:Block {source_note_id: $note_id}) RETURN b.block_uid, b.content_hash`

Returns `{block_uid: content_hash}` for all Block nodes of that note.

---

## Section 2: Read Path — AGE-Backed Graph Services

### What changes

`LocalGraphService` and `GlobalGraphService` drop the `NoteNlpPipeline` dependency. The per-note `self._pipeline.extract()` loop is replaced with a single call to a new `GraphRepository` read method.

### New GraphRepository method

`fetch_graph_for_notes(note_ids: list[str], min_confidence: float, graph_name: str) -> GraphFetchResult`

`GraphFetchResult` is a dataclass:
```python
@dataclass
class GraphFetchResult:
    entity_nodes: list[dict]        # {id, name, kind, confidence}
    mention_edges: list[dict]       # {source_note_id, target_entity_id, confidence}
    relation_edges: list[dict]      # {source_id, target_id, type, confidence, source_note_id}
    links_to_edges: list[dict]      # {source_note_id, target_note_id}
```

Returns:
- All `Entity` nodes with a `MENTIONS` edge from a `Block` whose `source_note_id` is in `note_ids`
- Note→Entity `MENTIONS` edges (aggregated from block-level — confidence is max across blocks)
- All typed `Concept→Concept` edges (IS_A, USES, CAUSES, PART_OF, etc.) where both endpoints are in the returned entity set
- Note→Note `LINKS_TO` edges between the requested notes

**AGE agtype parsing:** AGE returns all values as `agtype` (a PostgreSQL composite type). Each row from `_exec_cypher` returns a single `agtype` string that must be JSON-parsed. New read methods must parse these strings via `json.loads` on each returned row value. The existing write path avoids this (it only uses `MERGE`/`SET`, never `RETURN`). The new read methods introduce the first `RETURN`-based queries — a small parsing layer sits between `_exec_cypher` and the return value.

**Safe embedding of note_ids in Cypher:** Note IDs are user-supplied strings. They must be embedded using `json.dumps` (same pattern used by existing write methods) rather than string formatting, to prevent injection via IDs containing quotes or special characters. For list values, the full list is serialized as a JSON array literal embedded in the Cypher query.

### LocalGraphService

Keeps wiki-link traversal for finding reachable note IDs (pure SQL, unchanged). Once it has the note ID set, calls `fetch_graph_for_notes` and maps results to `LocalGraphNode` / `LocalGraphEdge`.

Removed entirely: `NoteNlpPipeline` import, `_entity_is_note_noise`, `_build_dictionary_terms`, the per-note extraction loop.

### GlobalGraphService

Keeps SQL query for note metadata (titles, subject_ids, content previews). Same swap — `fetch_graph_for_notes` replaces the NLP loop.

Removed entirely: same as above.

### Graph cache

`get_cached` / `set_cached` stays unchanged. Cache keys include `notes_version`, so cache invalidates correctly when a note is re-synced to AGE.

### Behavioral note

Notes not yet synced to AGE will return empty graph data until their processing job completes. The frontend should surface this as a "processing" state. Handling that UI state is a follow-on task.

---

## Section 3: Startup Backfill — AGE-Aware

### Current problem

`StartupBackfillService` re-queues every note on every startup, even notes fully synced to AGE. On large knowledge bases this fires unnecessary NLP jobs on every container restart.

### New algorithm

```
On startup (PostgreSQL only):
1. Fetch all note_ids + {block_uid → content_hash} from relational DB
2. For each note, call fetch_block_states(note_id) against AGE
3. Any block missing from AGE or with stale content_hash → note is dirty
4. Queue only dirty notes
5. Fully-synced notes → skip
```

Reuses `fetch_block_states` — no new infrastructure.

**Brand new install:** AGE is empty, all notes queue normally.

**Concurrency:** If a note is edited while backfill runs, the existing `create_or_get_job` content_hash dedup handles it correctly — no change needed.

---

## Section 4: Testing

### PostgreSQL-only (graph path)

The AGE read and write paths require PostgreSQL. Graph service tests move from SQLite unit tests to Docker-backed integration tests.

### Unit tests (SQLite — unchanged)

- `GraphRepository` write methods
- `NoteNlpPipeline`, `extract_relations`, `extract_candidates`
- `GraphSyncService` delta diff logic — the dirty/unchanged/new/deleted set computation is pure Python and can be tested by mocking `GraphRepository`

### New integration tests (`tests/integration/` — PostgreSQL)

| File | What it covers |
|---|---|
| `test_graph_sync_delta.py` | Save note with N blocks, change 1, re-sync, assert only that block's AGE artifacts replaced |
| `test_graph_read_age.py` | `LocalGraphService` + `GlobalGraphService` return correct nodes/edges from AGE-stored data |
| `test_startup_backfill_age.py` | Backfill only queues notes with stale/missing blocks |

### Existing tests

`tests/integration/test_graph_api.py` (already PostgreSQL, end-to-end) stays valid.

`test_local_graph_service_includes_semantic_relation_edges` (added in the preceding bugfix session) moves to integration tests — the mock-pipeline approach is no longer valid once the service reads from AGE.

---

## Files Affected

| File | Change |
|---|---|
| `api/src/app/db/repositories/graph_repository.py` | Add `fetch_block_states`, `fetch_graph_for_notes` |
| `api/src/app/services/graph_sync_service.py` | Replace delete-and-replace with block-level delta algorithm |
| `api/src/app/services/local_graph_service.py` | Drop NLP pipeline, read from AGE via `fetch_graph_for_notes` |
| `api/src/app/services/global_graph_service.py` | Same |
| `api/src/app/services/startup_backfill_service.py` | Add AGE-aware pre-filter before queueing |
| `tests/unit/test_local_graph_service.py` | Move AGE-dependent test to integration suite |
| `tests/integration/test_graph_sync_delta.py` | New |
| `tests/integration/test_graph_read_age.py` | New |
| `tests/integration/test_startup_backfill_age.py` | New |
