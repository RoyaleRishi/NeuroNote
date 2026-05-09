"""Unit tests for the shared TipTap utilities."""
from __future__ import annotations

import pytest

from app.utils.tiptap import (
    ensure_block_uids,
    extract_plain_text,
)


def test_ensure_block_uids_stamps_missing_uids() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
        ],
    }
    out = ensure_block_uids(doc)
    para = out["content"][0]
    assert isinstance(para["attrs"]["blockUid"], str)
    assert len(para["attrs"]["blockUid"]) > 0


def test_ensure_block_uids_preserves_existing() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"blockUid": "existing-uid"},
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    }
    out = ensure_block_uids(doc)
    assert out["content"][0]["attrs"]["blockUid"] == "existing-uid"


def test_ensure_block_uids_is_idempotent() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
        ],
    }
    once = ensure_block_uids(doc)
    twice = ensure_block_uids(once)
    assert once["content"][0]["attrs"]["blockUid"] == twice["content"][0]["attrs"]["blockUid"]
    assert once["content"][1]["attrs"]["blockUid"] == twice["content"][1]["attrs"]["blockUid"]


def test_ensure_block_uids_regenerates_collisions() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"blockUid": "dup"},
             "content": [{"type": "text", "text": "a"}]},
            {"type": "paragraph", "attrs": {"blockUid": "dup"},
             "content": [{"type": "text", "text": "b"}]},
        ],
    }
    out = ensure_block_uids(doc)
    a, b = out["content"][0]["attrs"]["blockUid"], out["content"][1]["attrs"]["blockUid"]
    assert a == "dup" or b == "dup"  # one keeps the original
    assert a != b  # the other is regenerated


def test_extract_plain_text_concatenates_text_nodes() -> None:
    node = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ],
    }
    assert extract_plain_text(node) == "Hello world"
