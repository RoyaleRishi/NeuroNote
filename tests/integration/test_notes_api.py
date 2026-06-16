from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _payload(
    note_id: str,
    text: str,
    updated_at: str,
    *,
    note_title: str | None = None,
    subject_id: str = "inbox",
    tags: list[str] | None = None,
    is_pinned: bool = False,
    is_archived: bool = False,
) -> dict[str, object]:
    return {
        "note_id": note_id,
        "note_title": note_title or f"Title for {note_id}",
        "subject_id": subject_id,
        "tags": tags or [],
        "is_pinned": is_pinned,
        "is_archived": is_archived,
        "content_json": {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            ],
        },
        "content_text": text,
        "updated_at": updated_at,
    }


def test_put_note_saves_and_versions(client: TestClient) -> None:
    first = client.put(
        "/v1/notes/note-e1",
        json=_payload("note-e1", "First text", "2026-03-01T12:00:00Z"),
    )
    assert first.status_code == 200
    assert first.json()["note_id"] == "note-e1"
    assert first.json()["version"] == 1

    second = client.put(
        "/v1/notes/note-e1",
        json=_payload("note-e1", "Updated text", "2026-03-01T12:01:00Z"),
    )
    assert second.status_code == 200
    assert second.json()["version"] == 2


def test_put_note_succeeds_when_media_schema_unavailable(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.services import note_asset_service

    monkeypatch.setattr(note_asset_service, "note_assets_table_exists", lambda _session: False)

    response = client.put(
        "/v1/notes/note-no-media-schema",
        json=_payload("note-no-media-schema", "First text", "2026-03-01T12:00:00Z"),
    )
    assert response.status_code == 200


def test_put_note_succeeds_when_media_reconcile_hits_missing_table_during_delete_mark(
    client: TestClient,
    monkeypatch,
) -> None:
    from sqlalchemy.exc import ProgrammingError

    from app.db.repositories.note_asset_repository import NoteAssetRecord
    from app.services import note_asset_service

    class _FailingRepository:
        def __init__(self, _session) -> None:
            pass

        def list_active_assets_for_note(self, _note_id: str) -> list[NoteAssetRecord]:
            return [
                NoteAssetRecord(
                    asset_id="asset-1",
                    note_id="note-delete-mark",
                    mime_type="image/png",
                    file_ext="png",
                    byte_size=10,
                    relative_path="note-delete-mark/asset-1.png",
                    deleted_at=None,
                )
            ]

        def mark_deleted_many(self, _asset_ids: set[str]) -> int:
            raise ProgrammingError(
                "UPDATE note_assets SET deleted_at = now()",
                {},
                Exception('relation "note_assets" does not exist'),
            )

    monkeypatch.setattr(note_asset_service, "note_assets_table_exists", lambda _session: True)
    monkeypatch.setattr(note_asset_service, "NoteAssetRepository", _FailingRepository)

    response = client.put(
        "/v1/notes/note-delete-mark",
        json=_payload("note-delete-mark", "First text", "2026-03-01T12:00:00Z"),
    )
    assert response.status_code == 200


def test_get_note_returns_saved_payload(client: TestClient) -> None:
    client.put(
        "/v1/notes/note-fetch",
        json=_payload(
            "note-fetch",
            "Fetch text",
            "2026-03-01T12:02:00Z",
            subject_id="ml",
            tags=["graph", "ml"],
            is_pinned=True,
        ),
    )

    response = client.get("/v1/notes/note-fetch")
    assert response.status_code == 200
    body = response.json()
    assert body["note_id"] == "note-fetch"
    assert body["note_title"] == "Title for note-fetch"
    assert body["subject_id"] == "ml"
    assert set(body["tags"]) == {"graph", "ml"}
    assert body["is_pinned"] is True
    assert body["is_archived"] is False
    assert body["content_text"] == "Fetch text"
    assert body["version"] == 1


def test_put_note_rejects_path_payload_mismatch(client: TestClient) -> None:
    response = client.put(
        "/v1/notes/path-note",
        json=_payload("body-note", "Mismatch", "2026-03-01T12:03:00Z"),
    )
    assert response.status_code == 400


def test_get_note_returns_404_for_unknown_note(client: TestClient) -> None:
    response = client.get("/v1/notes/does-not-exist")
    assert response.status_code == 404


def test_put_note_rejects_invalid_payload(client: TestClient) -> None:
    response = client.put(
        "/v1/notes/note-invalid",
        json={
            "note_id": "",
            "note_title": "",
            "content_json": {},
            "content_text": "",
            "updated_at": "",
        },
    )
    assert response.status_code == 422


def test_put_note_rejects_duplicate_title_with_conflict(client: TestClient) -> None:
    first = client.put(
        "/v1/notes/conflict-a",
        json=_payload(
            "conflict-a",
            "Body A",
            "2026-03-13T12:00:00Z",
            note_title="Duplicate Guard",
        ),
    )
    assert first.status_code == 200

    second = client.put(
        "/v1/notes/conflict-b",
        json=_payload(
            "conflict-b",
            "Body B",
            "2026-03-13T12:01:00Z",
            note_title="Duplicate Guard",
        ),
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "note_title_conflict"


def test_backlinks_endpoint_returns_wikilink_sources(client: TestClient) -> None:
    client.put(
        "/v1/notes/backlink-target",
        json=_payload(
            "backlink-target",
            "Target body",
            "2026-03-13T13:00:00Z",
            note_title="Backlink Target",
        ),
    )
    client.put(
        "/v1/notes/backlink-source-1",
        json=_payload(
            "backlink-source-1",
            "Reference [[Backlink Target]] in note one",
            "2026-03-13T13:01:00Z",
            note_title="Source One",
        ),
    )
    client.put(
        "/v1/notes/backlink-source-2",
        json=_payload(
            "backlink-source-2",
            "Another ref [[backlink target]] in note two",
            "2026-03-13T13:02:00Z",
            note_title="Source Two",
        ),
    )

    response = client.get("/v1/notes/backlink-target/backlinks")
    assert response.status_code == 200
    body = response.json()
    assert body["note_id"] == "backlink-target"
    assert [item["source_note_id"] for item in body["items"]] == [
        "backlink-source-2",
        "backlink-source-1",
    ]


def test_backlinks_endpoint_returns_404_for_unknown_note(client: TestClient) -> None:
    response = client.get("/v1/notes/unknown-note/backlinks")
    assert response.status_code == 404


def test_list_notes_returns_saved_items_with_total(client: TestClient) -> None:
    client.put(
        "/v1/notes/note-list-1",
        json=_payload(
            "note-list-1",
            "First list value",
            "2026-03-01T12:10:00Z",
            subject_id="ml",
            tags=["graph"],
            is_pinned=True,
        ),
    )
    client.put(
        "/v1/notes/note-list-2",
        json=_payload(
            "note-list-2",
            "Second list value",
            "2026-03-01T12:11:00Z",
            subject_id="math",
            tags=["algebra"],
            is_archived=True,
        ),
    )

    response = client.get("/v1/notes?limit=10&offset=0")
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 1
    note_ids = {item["note_id"] for item in body["items"]}
    assert note_ids == {"note-list-1"}
    assert all(isinstance(item["note_title"], str) for item in body["items"])


def test_list_notes_supports_search_and_metadata_filters(client: TestClient) -> None:
    client.put(
        "/v1/notes/filter-1",
        json=_payload(
            "filter-1",
            "Graph relation extraction",
            "2026-03-01T12:13:00Z",
            note_title="Graph basics",
            subject_id="ml",
            tags=["graph", "nlp"],
            is_pinned=True,
        ),
    )
    client.put(
        "/v1/notes/filter-2",
        json=_payload(
            "filter-2",
            "Matrix decomposition",
            "2026-03-01T12:14:00Z",
            note_title="Linear algebra",
            subject_id="math",
            tags=["algebra"],
            is_pinned=False,
        ),
    )
    client.put(
        "/v1/notes/filter-3",
        json=_payload(
            "filter-3",
            "Archived graph note",
            "2026-03-01T12:15:00Z",
            note_title="Old graph",
            subject_id="ml",
            tags=["graph"],
            is_archived=True,
        ),
    )

    filtered = client.get(
        "/v1/notes",
        params={
            "limit": 10,
            "offset": 0,
            "search": "graph",
            "subject_id": "ml",
            "tag": "graph",
            "is_archived": "false",
        },
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["items"][0]["note_id"] == "filter-1"

    archived = client.get("/v1/notes", params={"is_archived": "true"})
    assert archived.status_code == 200
    archived_body = archived.json()
    assert archived_body["total"] == 1
    assert archived_body["items"][0]["note_id"] == "filter-3"


def test_delete_note_removes_record(client: TestClient) -> None:
    client.put(
        "/v1/notes/note-delete",
        json=_payload("note-delete", "Delete me", "2026-03-01T12:12:00Z"),
    )

    delete_response = client.delete("/v1/notes/note-delete")
    assert delete_response.status_code == 204

    get_response = client.get("/v1/notes/note-delete")
    assert get_response.status_code == 404


def test_delete_note_rolls_back_sql_when_graph_prune_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomicity: the SQL row delete and the AGE graph prune run in one transaction.

    If the graph prune raises, the SQL delete must roll back too — the note row
    survives. Guards the inline-transactional contract (and that prune errors are
    no longer swallowed).
    """
    from app.routes import notes as notes_route

    client.put(
        "/v1/notes/note-rb",
        json=_payload("note-rb", "Keep me on failure", "2026-03-01T12:20:00Z"),
    )

    def _boom(self, *, note_id: str, live_subject_ids: list[str]) -> None:
        raise RuntimeError("simulated graph prune failure")

    monkeypatch.setattr(
        notes_route.GraphReconciliationService, "delete_note_graph", _boom
    )

    with pytest.raises(Exception):
        client.delete("/v1/notes/note-rb")

    # The note row survived the failed transaction (atomic rollback).
    assert client.get("/v1/notes/note-rb").status_code == 200


def test_delete_note_returns_404_for_unknown_note(client: TestClient) -> None:
    response = client.delete("/v1/notes/unknown-note")
    assert response.status_code == 404
