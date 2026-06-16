from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _payload(note_id: str, note_title: str, text: str, updated_at: str) -> dict[str, object]:
    return {
        "note_id": note_id,
        "note_title": note_title,
        "subject_id": "inbox",
        "tags": [],
        "is_pinned": False,
        "is_archived": False,
        "content_json": {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            ],
        },
        "content_text": text,
        "updated_at": updated_at,
    }


def test_local_graph_returns_note_neighbors_and_metadata(client: TestClient) -> None:
    client.put(
        "/v1/notes/local-root",
        json=_payload(
            "local-root",
            "Root Note",
            "Machine Learning links to [[Neighbor Note]]",
            "2026-03-15T16:00:00Z",
        ),
    )
    client.put(
        "/v1/notes/local-neighbor",
        json=_payload(
            "local-neighbor",
            "Neighbor Note",
            "Neighbor body",
            "2026-03-15T16:01:00Z",
        ),
    )
    client.put(
        "/v1/notes/local-inbound",
        json=_payload(
            "local-inbound",
            "Inbound Note",
            "Inbound points to [[Root Note]]",
            "2026-03-15T16:02:00Z",
        ),
    )

    response = client.get(
        "/v1/graph/local/local-root",
        params={
            "max_hops": 1,
            "limit_nodes": 80,
            "node_salience_threshold": 0,
            "relationship_confidence_threshold": 0,
            "include_types": "note,entity,relation",
        },
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["meta"]["root_note_id"] == "local-root"
    assert payload["meta"]["truncated"] is False
    assert payload["meta"]["applied_filters"] == {
        "max_hops": 1,
        "limit_nodes": 80,
        "node_salience_threshold": 0.0,
        "relationship_confidence_threshold": 0.0,
        "include_types": ["note", "entity", "relation"],
    }

    node_ids = {node["id"] for node in payload["nodes"]}
    assert "local-root" in node_ids
    assert "local-neighbor" in node_ids
    assert "local-inbound" in node_ids

    sorted_nodes = sorted(payload["nodes"], key=lambda item: (item["type"], item["id"]))
    assert payload["nodes"] == sorted_nodes

    edge_pairs = {(edge["source"], edge["target"], edge["type"]) for edge in payload["edges"]}
    assert ("local-root", "local-neighbor", "LINKS_TO") in edge_pairs
    assert ("local-inbound", "local-root", "LINKS_TO") in edge_pairs


def test_local_graph_respects_node_limit_and_marks_truncated(client: TestClient) -> None:
    client.put(
        "/v1/notes/local-limit-root",
        json=_payload(
            "local-limit-root",
            "Limit Root",
            "Links to [[Limit Neighbor]]",
            "2026-03-15T16:10:00Z",
        ),
    )
    client.put(
        "/v1/notes/local-limit-neighbor",
        json=_payload(
            "local-limit-neighbor",
            "Limit Neighbor",
            "Neighbor body",
            "2026-03-15T16:11:00Z",
        ),
    )

    response = client.get(
        "/v1/graph/local/local-limit-root",
        params={"limit_nodes": 1, "include_types": "note,relation"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) == 1
    assert body["meta"]["truncated"] is True
    assert len(body["edges"]) == 0


def test_local_graph_returns_404_for_unknown_note(client: TestClient) -> None:
    response = client.get("/v1/graph/local/missing-note")
    assert response.status_code == 404


def test_local_graph_excludes_note_titles_and_link_targets_from_entities(
    client: TestClient,
) -> None:
    from app.db.engine import get_engine
    if get_engine().dialect.name != "postgresql":
        pytest.skip("AGE entity data requires PostgreSQL")
    client.put(
        "/v1/notes/local-noise-root",
        json=_payload(
            "local-noise-root",
            "Noise Root",
            "Machine Learning links to [[Noise Neighbor]]",
            "2026-03-29T12:20:00Z",
        ),
    )
    client.put(
        "/v1/notes/local-noise-neighbor",
        json=_payload(
            "local-noise-neighbor",
            "Noise Neighbor",
            "Neighbor body",
            "2026-03-29T12:21:00Z",
        ),
    )

    response = client.get(
        "/v1/graph/local/local-noise-root",
        params={
            "max_hops": 1,
            "limit_nodes": 80,
            "node_salience_threshold": 0,
            "relationship_confidence_threshold": 0,
            "include_types": "note,entity,relation",
        },
    )
    assert response.status_code == 200

    entity_labels = {
        node["label"].lower()
        for node in response.json()["nodes"]
        if node["type"] == "entity"
    }
    assert "machine learning" in entity_labels
    assert "noise root" not in entity_labels
    assert "noise neighbor" not in entity_labels


def test_global_graph_filters_by_subject_id(client: TestClient) -> None:
    client.put(
        "/v1/notes/subj-physics-1",
        json={**_payload("subj-physics-1", "Physics Note", "Newton laws", "2026-05-02T10:00:00Z"),
              "subject_id": "physics"},
    )
    client.put(
        "/v1/notes/subj-math-1",
        json={**_payload("subj-math-1", "Math Note", "Calculus derivatives", "2026-05-02T10:01:00Z"),
              "subject_id": "math"},
    )

    resp = client.get("/v1/graph/global", params={"subject_id": "physics", "include_types": "note"})
    assert resp.status_code == 200
    body = resp.json()
    note_ids = {n["id"] for n in body["nodes"]}
    assert "subj-physics-1" in note_ids
    assert "subj-math-1" not in note_ids
    assert body["meta"]["applied_filters"]["subject_id"] == "physics"


def test_global_graph_filters_by_tag(client: TestClient) -> None:
    client.put(
        "/v1/notes/tag-lecture-1",
        json={**_payload("tag-lecture-1", "Lecture Note", "Today we covered photosynthesis", "2026-05-02T11:00:00Z"),
              "tags": ["lecture"]},
    )
    client.put(
        "/v1/notes/tag-notag-1",
        json=_payload("tag-notag-1", "Untagged Note", "Some content", "2026-05-02T11:01:00Z"),
    )

    resp = client.get("/v1/graph/global", params={"tag": "lecture", "include_types": "note"})
    assert resp.status_code == 200
    body = resp.json()
    note_ids = {n["id"] for n in body["nodes"]}
    assert "tag-lecture-1" in note_ids
    assert "tag-notag-1" not in note_ids
    assert body["meta"]["applied_filters"]["tag"] == "lecture"
