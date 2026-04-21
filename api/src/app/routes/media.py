from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.repositories.note_asset_repository import NoteAssetRepository
from app.db.repositories.note_repository import NoteRepository
from app.db.tenant_session import get_tenant_session
from app.media.config import get_media_settings
from app.services.note_asset_service import (
    allowed_image_mime_types,
    create_asset_identity,
    get_media_storage,
    note_assets_table_exists,
)
from shared.contracts.python.v1.media import DeleteImageResponse, UploadImageRequest, UploadImageResponse

router = APIRouter()


@router.post(
    "/media/uploads",
    response_model=UploadImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_media(
    payload: UploadImageRequest,
    session: Session = Depends(get_tenant_session),
) -> UploadImageResponse:
    if not note_assets_table_exists(session):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media schema is unavailable. Run database migrations.",
        )

    mime_type = payload.mime_type.lower()
    if mime_type not in allowed_image_mime_types():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported image type")

    try:
        file_bytes = base64.b64decode(payload.content_base64.encode("utf-8"), validate=True)
    except Exception as exc:  # pragma: no cover - defensive type branch
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 payload") from exc

    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file upload")

    settings = get_media_settings()
    if len(file_bytes) > settings.max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large")

    storage = get_media_storage()
    with session.begin_nested():
        note = NoteRepository(session).get_note(payload.note_id)
        if note is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Note {payload.note_id} was not found",
            )

        asset_id, extension, relative_path = create_asset_identity(payload.note_id, mime_type)
        storage.save_bytes(relative_path=relative_path, content=file_bytes)
        NoteAssetRepository(session).create_asset(
            asset_id=asset_id,
            note_id=payload.note_id,
            mime_type=mime_type,
            file_ext=extension,
            byte_size=len(file_bytes),
            relative_path=relative_path,
        )

    return UploadImageResponse(
        asset_id=asset_id,
        note_id=payload.note_id,
        src=f"/v1/media/{asset_id}",
        mime_type=mime_type,
        byte_size=len(file_bytes),
    )


@router.get("/media/{asset_id}")
def fetch_media(
    asset_id: str,
    session: Session = Depends(get_tenant_session),
) -> Response:
    if not note_assets_table_exists(session):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media schema is unavailable. Run database migrations.",
        )

    asset = NoteAssetRepository(session).get_asset(asset_id)
    if asset is None or asset.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    storage = get_media_storage()
    if not storage.exists(relative_path=asset.relative_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset bytes not found")

    payload = storage.read_bytes(relative_path=asset.relative_path)
    return Response(content=payload, media_type=asset.mime_type)


@router.delete("/media/{asset_id}", response_model=DeleteImageResponse)
def delete_media(
    asset_id: str,
    session: Session = Depends(get_tenant_session),
) -> DeleteImageResponse:
    if not note_assets_table_exists(session):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media schema is unavailable. Run database migrations.",
        )

    storage = get_media_storage()
    with session.begin_nested():
        repository = NoteAssetRepository(session)
        asset = repository.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        repository.mark_deleted(asset_id)
        storage.delete(relative_path=asset.relative_path)

    return DeleteImageResponse(asset_id=asset_id, deleted=True)
