from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.repositories.block_repository import BlockRepository
from app.db.tenant_session import get_tenant_session
from shared.contracts.python.v1.block import (
    BlockBacklinkItem,
    BlockBacklinksResponse,
    BlockNode,
    BlockSearchItem,
    BlockSearchResponse,
    ListBlocksResponse,
)

router = APIRouter()


@router.get("/notes/{note_id}/blocks", response_model=ListBlocksResponse)
def list_blocks_for_note(
    note_id: str,
    session: Session = Depends(get_tenant_session),
) -> ListBlocksResponse:
    rows = BlockRepository(session).list_blocks_for_note(note_id)
    return ListBlocksResponse(
        items=[
            BlockNode(
                block_uid=row.block_uid,
                note_id=row.note_id,
                parent_block_uid=row.parent_block_uid,
                sibling_order=row.sibling_order,
                block_index=row.block_index,
                content_text=row.content_text,
                rich_content=row.rich_content,
            )
            for row in rows
        ]
    )


@router.get("/blocks/search", response_model=BlockSearchResponse)
def search_blocks(
    q: str = Query(default=""),
    note_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_tenant_session),
) -> BlockSearchResponse:
    rows = BlockRepository(session).search_blocks(
        query=q,
        note_id=note_id,
        limit=limit,
    )
    return BlockSearchResponse(
        items=[
            BlockSearchItem(
                block_uid=row.block_uid,
                note_id=row.note_id,
                note_title=row.note_title,
                content_text=row.content_text,
            )
            for row in rows
        ]
    )


@router.get("/blocks/{block_uid}/backlinks", response_model=BlockBacklinksResponse)
def list_block_backlinks(
    block_uid: str,
    session: Session = Depends(get_tenant_session),
) -> BlockBacklinksResponse:
    rows = BlockRepository(session).list_block_backlinks(block_uid)
    if rows is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_uid} was not found",
        )
    return BlockBacklinksResponse(
        block_uid=block_uid,
        items=[
            BlockBacklinkItem(
                source_block_uid=row.source_block_uid,
                source_note_id=row.source_note_id,
                source_note_title=row.source_note_title,
                snippet=row.snippet,
                updated_at=row.updated_at,
            )
            for row in rows
        ],
    )
