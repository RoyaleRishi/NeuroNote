"""Integration tests for AGE-backed graph services.

Requires PostgreSQL + AGE. Run via: make compose-test
or: TEST_DATABASE_URL=postgresql://... uv run --project api python -m pytest tests/integration/test_graph_read_age.py -v
"""
from __future__ import annotations

import time
import uuid
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


def test_local_graph_returns_entity_nodes_from_age(client: TestClient, db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")
    suffix = uuid.uuid4().hex[:8]
    note_id = f"age-local-entity-{suffix}"
    _process_and_wait(client, note_id, "machine learning improves computer vision", "Entity Test")
    resp = client.get(f"/v1/graph/local/{note_id}", params={
        "include_types": "note,entity,relation",
        "node_salience_threshold": 0.0,
        "relationship_confidence_threshold": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    note_ids_in_response = {n["id"] for n in body["nodes"] if n["type"] == "note"}
    assert note_id in note_ids_in_response
    entity_nodes = [n for n in body["nodes"] if n["type"] == "entity"]
    assert entity_nodes, "Expected entity nodes from AGE after processing"


def test_local_graph_returns_relation_edges_from_age(client: TestClient, db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")
    suffix = uuid.uuid4().hex[:8]
    note_id = f"age-local-relation-{suffix}"
    _process_and_wait(client, note_id, "Python uses Django for web development", "Relation Test")
    resp = client.get(f"/v1/graph/local/{note_id}", params={
        "include_types": "note,entity,relation",
        "node_salience_threshold": 0.0,
        "relationship_confidence_threshold": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    note_ids_in_response = {n["id"] for n in body["nodes"] if n["type"] == "note"}
    assert note_id in note_ids_in_response
    edge_types = {e["type"] for e in body["edges"]}
    # MENTIONS edges should appear (Note→Entity)
    assert "MENTIONS" in edge_types or len(body["nodes"]) > 1


def test_local_graph_still_returns_links_to_edges(client: TestClient, db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")
    suffix = uuid.uuid4().hex[:8]
    root_id = f"age-links-root-{suffix}"
    target_id = f"age-links-target-{suffix}"
    target_title = f"Age Links Target {suffix}"
    _process_and_wait(client, root_id, f"See [[{target_title}]]", f"Links Root {suffix}")
    _process_and_wait(client, target_id, "Target content", target_title)
    resp = client.get(f"/v1/graph/local/{root_id}", params={
        "include_types": "note,relation",
        "max_hops": 1,
    })
    assert resp.status_code == 200
    body = resp.json()
    edge_pairs = {(e["source"], e["target"], e["type"]) for e in body["edges"]}
    assert (root_id, target_id, "LINKS_TO") in edge_pairs


def test_global_graph_returns_entity_nodes_from_age(client: TestClient, db_session) -> None:
    from sqlalchemy import inspect as sa_inspect
    if sa_inspect(db_session.bind).dialect.name != "postgresql":
        pytest.skip("PostgreSQL + AGE required")
    suffix = uuid.uuid4().hex[:8]
    note_id = f"age-global-entity-{suffix}"
    _process_and_wait(
        client, note_id,
        "neural networks enable deep learning",
        f"Global Entity Test {suffix}",
    )
    resp = client.get("/v1/graph/global", params={
        "include_types": "note,entity,relation",
        "node_salience_threshold": 0.0,
        "relationship_confidence_threshold": 0.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body
    # The processed note must appear in the global graph
    note_ids = {n["id"] for n in body["nodes"] if n["type"] == "note"}
    assert note_id in note_ids
