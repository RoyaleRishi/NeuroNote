"""TipTap document block-attrs contract (v1).

Backend consumers (NLP pipeline, exporters) and producers
(BlockRepository, future imports) agree on this shape. Mirror in
``shared/contracts/ts/v1/document.ts`` whenever this changes.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# Re-exported from app.utils.tiptap to keep one source of truth.
# (The contract module is the *interface*; the util module is the
# *implementation*. We intentionally couple them.)
from app.utils.tiptap import STRUCTURAL_BLOCK_TYPES  # noqa: F401  (re-exported)


class TipTapBlockAttrs(BaseModel):
    """Attributes carried by every structural TipTap block."""

    blockUid: str = Field(..., min_length=1)
    parentBlockUid: str | None = None
    indentLevel: int | None = None
    level: int | None = None  # heading-only

    model_config = {"extra": "allow"}  # tolerate fields the backend doesn't read
