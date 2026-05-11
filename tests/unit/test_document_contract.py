"""Tests for the shared TipTap block-attrs contract."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.contracts.python.v1.document import (
    STRUCTURAL_BLOCK_TYPES,
    TipTapBlockAttrs,
)


def test_tiptap_block_attrs_requires_block_uid() -> None:
    with pytest.raises(ValidationError):
        TipTapBlockAttrs()  # type: ignore[call-arg]


def test_tiptap_block_attrs_accepts_minimum_payload() -> None:
    attrs = TipTapBlockAttrs(blockUid="abc123")
    assert attrs.blockUid == "abc123"
    assert attrs.parentBlockUid is None
    assert attrs.indentLevel is None
    assert attrs.level is None


def test_tiptap_block_attrs_accepts_optional_fields() -> None:
    attrs = TipTapBlockAttrs(
        blockUid="abc",
        parentBlockUid="parent",
        indentLevel=2,
        level=3,
    )
    assert attrs.parentBlockUid == "parent"
    assert attrs.indentLevel == 2
    assert attrs.level == 3


def test_structural_block_types_matches_util_constant() -> None:
    """Contract and util share the same set; drift would fail this test."""
    from app.utils.tiptap import STRUCTURAL_BLOCK_TYPES as UTIL_TYPES
    assert STRUCTURAL_BLOCK_TYPES == UTIL_TYPES
