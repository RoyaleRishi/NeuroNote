"""Integration tests for AGE graph delta sync read methods.

Run against PostgreSQL+AGE via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_graph_sync_delta.py -v
"""
from __future__ import annotations

import pytest

_GRAPH = "nn_user_test0001"


def test_fetch_block_states_returns_empty_for_unsynced_note(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    states = repo.fetch_block_states(note_id="nonexistent-note", graph_name=_GRAPH)
    assert states == {}


def test_fetch_block_states_returns_correct_hash_after_upsert(db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)
    repo.upsert_node(
        label="Block",
        node_id="delta-note1:block:b1",
        properties={
            "id": "delta-note1:block:b1",
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
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

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
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)

    # Seed: Note node, Entity node, Note→Entity MENTIONS edge
    repo.upsert_node(
        label="Note",
        node_id="fetch-note1",
        properties={
            "id": "fetch-note1",
            "source_note_id": "fetch-note1",
            "name": "Test Note",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_node(
        label="Entity",
        node_id="concept-python",
        properties={
            "id": "concept-python",
            "name": "Python",
            "kind": "concept",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_typed_edge(
        source_label="Note",
        source_id="fetch-note1",
        target_label="Entity",
        target_id="concept-python",
        relation_type="MENTIONS",
        properties={
            "source_note_id": "fetch-note1",
            "confidence": 0.9,
            "created_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )

    # Seed: Concept nodes + typed relation edge
    repo.upsert_node(
        label="Concept",
        node_id="concept-python",
        properties={
            "id": "concept-python",
            "name": "Python",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_node(
        label="Concept",
        node_id="concept-django",
        properties={
            "id": "concept-django",
            "name": "Django",
            "updated_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    repo.upsert_typed_edge(
        source_label="Concept",
        source_id="concept-python",
        target_label="Concept",
        target_id="concept-django",
        relation_type="USES",
        properties={
            "source_note_id": "fetch-note1",
            "confidence": 0.85,
            "predicate": "USES",
            "created_at": "2026-05-03T10:00:00Z",
        },
        graph_name=_GRAPH,
    )
    db_session.commit()

    result = repo.fetch_graph_for_notes(
        note_ids=["fetch-note1"],
        min_confidence=0.0,
        graph_name=_GRAPH,
    )

    entity_ids = {m.entity_id for m in result.mentions}
    assert "concept-python" in entity_ids

    rel_keys = {(r.source_id, r.target_id, r.edge_type) for r in result.relations}
    assert ("concept-python", "concept-django", "USES") in rel_keys


# ---------------------------------------------------------------------------
# Batched edge upsert (Task 3.3) — AGE compatibility regression guard
# ---------------------------------------------------------------------------


def test_upsert_typed_edges_batch_writes_against_real_age(db_session) -> None:
    """Batched MENTIONS upsert must execute against AGE without rejection.

    Regression guard for the AGE Cypher quirk: ``SET r += row.properties``
    against a nested-map projection raises ``FeatureNotSupported``. The fix
    flattens properties to top-level row keys and emits explicit
    ``SET r.<key> = row.<key>`` assignments. Unit tests with fakes do not
    exercise the real Cypher parser, so this test is required to catch
    AGE-compatibility regressions in future edits.
    """
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")

    from app.db.repositories.graph_repository import GraphRepository

    repo = GraphRepository(db_session)

    note_id = "batch-edge-note-1"
    # Seed Note + 3 Entity nodes so the MENTIONS batch has > 1 edge (the
    # single-edge fallback path bypasses the batched UNWIND entirely).
    repo.upsert_node(
        label="Note",
        node_id=note_id,
        properties={"id": note_id, "name": "Batch Test", "updated_at": "2026-06-12T00:00:00Z"},
        graph_name=_GRAPH,
    )
    entity_ids = ["batch-ent-python", "batch-ent-fastapi", "batch-ent-ml"]
    for eid in entity_ids:
        repo.upsert_node(
            label="Entity",
            node_id=eid,
            properties={"id": eid, "name": eid, "kind": "concept",
                        "updated_at": "2026-06-12T00:00:00Z"},
            graph_name=_GRAPH,
        )

    edges = [
        {
            "source_id": note_id,
            "target_id": eid,
            "properties": {
                "source_note_id": note_id,
                "confidence": 0.9,
                "created_at": "2026-06-12T00:00:00Z",
                "updated_at": "2026-06-12T00:00:00Z",
            },
        }
        for eid in entity_ids
    ]
    # The pre-fix Cypher (`SET r += row.properties`) would raise here.
    repo.upsert_typed_edges_batch(
        source_label="Note",
        target_label="Entity",
        relation_type="MENTIONS",
        edges=edges,
        graph_name=_GRAPH,
    )
    db_session.commit()

    result = repo.fetch_graph_for_notes(
        note_ids=[note_id],
        min_confidence=0.0,
        graph_name=_GRAPH,
    )
    fetched_ids = {m.entity_id for m in result.mentions}
    for eid in entity_ids:
        assert eid in fetched_ids, f"Missing MENTIONS edge for {eid}"
    for m in result.mentions:
        if m.entity_id in entity_ids:
            assert m.source_note_id == note_id
            assert abs(m.confidence - 0.9) < 1e-6


# ---------------------------------------------------------------------------
# Delta sync correctness tests (Task 2)
# ---------------------------------------------------------------------------

def _note_payload(note_id: str, title: str, text: str) -> dict:
    return {
        "note_id": note_id,
        "note_title": title,
        "content_json": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        },
        "content_text": text,
        "updated_at": "2026-05-03T10:00:00Z",
    }


def _process_note(client, note_id: str, text: str, title: str = "Test") -> None:
    """Create a note and trigger synchronous processing via the API."""
    import hashlib
    import time
    content_hash = hashlib.md5(text.encode()).hexdigest()
    put_resp = client.put(f"/v1/notes/{note_id}", json=_note_payload(note_id, title, text))
    assert put_resp.status_code in (200, 201), (
        f"PUT /v1/notes/{note_id} returned {put_resp.status_code}: {put_resp.text[:200]}"
    )
    resp = client.post("/v1/process-note", json={
        "note_id": note_id,
        "content_text": text,
        "content_hash": content_hash,
        "updated_at": "2026-05-03T10:00:00Z",
    })
    assert resp.status_code in (200, 202), (
        f"POST /v1/process-note returned {resp.status_code}: {resp.text[:200]}"
    )
    # Poll until done (max 10s), then add a fixed settle wait so the background
    # worker has time to commit its AGE writes before the caller reads AGE state.
    job_id = resp.json().get("job_id")
    if job_id:
        for _ in range(20):
            s = client.get(f"/v1/process-note/status/{job_id}").json()
            if s.get("status") in ("completed", "failed"):
                break
            time.sleep(0.5)
    time.sleep(1)  # Allow background-thread DB commit to flush


def test_delta_sync_skips_unchanged_blocks(client, db_session) -> None:
    """Re-syncing an unchanged note must not replace its Block nodes."""
    import uuid
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")
    from app.db.repositories.graph_repository import GraphRepository

    _GRAPH = "nn_user_test0001"
    # Use a unique note ID per run to avoid stale state from previous test runs
    note_id = f"delta-unchanged-{uuid.uuid4().hex[:8]}"
    _process_note(client, note_id, "machine learning improves reasoning", title=f"Delta Unchanged {note_id}")

    # Commit to advance our transaction snapshot past the API session's writes.
    # Create a new GraphRepository after commit so _age_ready_graphs is reset —
    # AGE requires LOAD 'age' + SET search_path to be re-run in each transaction.
    db_session.commit()
    repo = GraphRepository(db_session)
    states_before = repo.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    assert states_before, "Expected blocks in AGE after first sync"

    # Re-process without changing content — all blocks should stay identical
    _process_note(client, note_id, "machine learning improves reasoning", title=f"Delta Unchanged {note_id}")

    # Commit again so we see any changes (should be none for unchanged content)
    db_session.commit()
    repo2 = GraphRepository(db_session)
    states_after = repo2.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    assert states_before == states_after, "Unchanged blocks should not be re-synced"


def test_delta_sync_only_updates_changed_block(client, db_session) -> None:
    """Changing one block must update only that block's AGE state."""
    import uuid
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")
    from app.db.repositories.graph_repository import GraphRepository

    _GRAPH = "nn_user_test0001"
    # Use a unique note ID per run to avoid stale state from previous test runs
    note_id = f"delta-change-{uuid.uuid4().hex[:8]}"
    _process_note(client, note_id, "first paragraph content here", title=f"Delta Change {note_id}")

    # Commit to get a fresh transaction snapshot of the API session's writes.
    # Create a new GraphRepository after commit so _age_ready_graphs is reset —
    # AGE requires LOAD 'age' + SET search_path to be re-run in each transaction.
    db_session.commit()
    repo = GraphRepository(db_session)
    states_before = repo.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    assert len(states_before) >= 1

    # Change content (new hash), re-process
    _process_note(client, note_id, "completely different paragraph content", title=f"Delta Change {note_id}")

    # Commit again so we see the AGE writes from the second processing run.
    db_session.commit()
    repo2 = GraphRepository(db_session)
    states_after = repo2.fetch_block_states(note_id=note_id, graph_name=_GRAPH)
    # Block hashes must differ (content changed)
    assert states_before != states_after
