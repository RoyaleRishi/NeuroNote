from __future__ import annotations

import base64
import io
import zipfile

from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def media_client(configured_db: None, monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("MEDIA_ROOT_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-media-tests")

    from app.main import app
    from app.core.auth import UserContext, get_current_user
    from app.db.session import get_db_session
    from app.db.tenant_session import get_tenant_session
    from app.services.note_asset_service import reset_media_storage

    _fake_user = UserContext(user_id="test-user", email="test@test.com", schema_name="user_test0001")
    app.dependency_overrides[get_current_user] = lambda: _fake_user
    app.dependency_overrides[get_tenant_session] = get_db_session

    reset_media_storage()
    with TestClient(app) as test_client:
        yield test_client
    reset_media_storage()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_tenant_session, None)


def _note_payload(note_id: str, content_json: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "note_id": note_id,
        "note_title": "Media note",
        "subject_id": "inbox",
        "tags": [],
        "is_pinned": False,
        "is_archived": False,
        "content_json": content_json
        or {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Body"}]}],
        },
        "content_text": "Body",
        "updated_at": "2026-03-13T10:00:00Z",
    }


def test_media_upload_get_delete_flow(media_client: TestClient) -> None:
    media_client.put("/v1/notes/media-note-1", json=_note_payload("media-note-1"))

    payload = base64.b64encode(b"\x89PNG\r\n\x1a\nabc").decode("utf-8")
    upload_response = media_client.post(
        "/v1/media/uploads",
        json={
            "note_id": "media-note-1",
            "filename": "diagram.png",
            "mime_type": "image/png",
            "content_base64": payload,
        },
    )
    assert upload_response.status_code == 201
    asset = upload_response.json()

    fetch_response = media_client.get(asset["src"])
    assert fetch_response.status_code == 200
    assert fetch_response.headers["content-type"].startswith("image/png")

    delete_response = media_client.delete(f"/v1/media/{asset['asset_id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    missing_response = media_client.get(asset["src"])
    assert missing_response.status_code == 404


def test_media_upload_rejects_disallowed_mime(media_client: TestClient) -> None:
    media_client.put("/v1/notes/media-note-2", json=_note_payload("media-note-2"))

    payload = base64.b64encode(b"hello").decode("utf-8")
    response = media_client.post(
        "/v1/media/uploads",
        json={
            "note_id": "media-note-2",
            "filename": "payload.txt",
            "mime_type": "text/plain",
            "content_base64": payload,
        },
    )
    assert response.status_code == 400


def test_media_upload_returns_503_when_media_schema_unavailable(
    media_client: TestClient,
    monkeypatch,
) -> None:
    from app.routes import media as media_route_module

    media_client.put("/v1/notes/media-note-2", json=_note_payload("media-note-2"))
    monkeypatch.setattr(media_route_module, "note_assets_table_exists", lambda _session: False)
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\nabc").decode("utf-8")
    response = media_client.post(
        "/v1/media/uploads",
        json={
            "note_id": "media-note-2",
            "filename": "diagram.png",
            "mime_type": "image/png",
            "content_base64": payload,
        },
    )
    assert response.status_code == 503


def test_markdown_export_returns_zip_with_assets(media_client: TestClient) -> None:
    media_client.put("/v1/notes/media-note-3", json=_note_payload("media-note-3"))

    payload = base64.b64encode(b"\x89PNG\r\n\x1a\nxyz").decode("utf-8")
    upload_response = media_client.post(
        "/v1/media/uploads",
        json={
            "note_id": "media-note-3",
            "filename": "graph.png",
            "mime_type": "image/png",
            "content_base64": payload,
        },
    )
    assert upload_response.status_code == 201
    asset = upload_response.json()

    content_json: dict[str, object] = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Graph"}]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "E="},
                    {"type": "mathInline", "attrs": {"latex": "mc^2"}},
                ],
            },
            {"type": "mathBlock", "attrs": {"latex": "x^2 + y^2"}},
            {
                "type": "image",
                "attrs": {
                    "src": asset["src"],
                    "assetId": asset["asset_id"],
                    "alt": "graph",
                    "filename": f"{asset['asset_id']}.png",
                },
            },
        ],
    }
    media_client.put("/v1/notes/media-note-3", json=_note_payload("media-note-3", content_json))

    export_response = media_client.get("/v1/notes/media-note-3/export/markdown")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("application/zip")

    archive = zipfile.ZipFile(io.BytesIO(export_response.content), "r")
    names = set(archive.namelist())
    assert "note.md" in names
    assert f"assets/{asset['asset_id']}.png" in names

    markdown = archive.read("note.md").decode("utf-8")
    assert "# Graph" in markdown
    assert "$mc^2$" in markdown
    assert "$$x^2 + y^2$$" in markdown
    assert f"![graph](assets/{asset['asset_id']}.png)" in markdown
