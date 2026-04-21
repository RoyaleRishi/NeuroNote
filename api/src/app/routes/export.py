from __future__ import annotations

from copy import deepcopy
import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.repositories.note_asset_repository import NoteAssetRepository, NoteAssetRecord
from app.db.repositories.note_repository import NoteRepository
from app.db.tenant_session import get_tenant_session
from app.export.markdown import render_note_markdown
from app.media.references import extract_asset_ids_from_doc
from app.services.note_asset_service import get_media_storage, note_assets_table_exists

router = APIRouter()


def _as_object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _hydrate_image_filenames(
    content_json: dict[str, object],
    *,
    assets_by_id: dict[str, NoteAssetRecord],
) -> dict[str, object]:
    cloned = deepcopy(content_json)

    def _walk(node: dict[str, object]) -> None:
        node_type = str(node.get("type", ""))
        if node_type == "image":
            attrs = _as_object(node.get("attrs")) or {}
            asset_id = attrs.get("assetId")
            if isinstance(asset_id, str):
                asset = assets_by_id.get(asset_id)
                if asset is not None:
                    attrs["filename"] = f"{asset.asset_id}.{asset.file_ext}"
                    attrs["ext"] = asset.file_ext
            node["attrs"] = attrs

        raw_content = node.get("content")
        if isinstance(raw_content, list):
            for item in raw_content:
                child = _as_object(item)
                if child is not None:
                    _walk(child)

    root = _as_object(cloned)
    if root is None:
        return cloned
    _walk(root)
    return root


@router.get("/notes/{note_id}/export/markdown")
def export_note_markdown(
    note_id: str,
    session: Session = Depends(get_tenant_session),
) -> Response:
    note = NoteRepository(session).get_note(note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Note {note_id} was not found")

    assets_by_id: dict[str, NoteAssetRecord] = {}
    if note_assets_table_exists(session):
        referenced_asset_ids = extract_asset_ids_from_doc(note.content_json)
        assets = NoteAssetRepository(session).list_by_ids(referenced_asset_ids)
        assets_by_id = {asset.asset_id: asset for asset in assets if asset.deleted_at is None}

    hydrated_content = _hydrate_image_filenames(note.content_json, assets_by_id=assets_by_id)
    markdown = render_note_markdown(hydrated_content)

    storage = get_media_storage()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("note.md", markdown)
        for asset in assets_by_id.values():
            if not storage.exists(relative_path=asset.relative_path):
                continue
            filename = f"{asset.asset_id}.{asset.file_ext}"
            archive.writestr(f"assets/{filename}", storage.read_bytes(relative_path=asset.relative_path))

    payload = archive_bytes.getvalue()
    headers = {"Content-Disposition": f'attachment; filename="{note_id}.zip"'}
    return Response(content=payload, media_type="application/zip", headers=headers)
