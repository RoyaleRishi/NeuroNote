"""Unit tests for the shared TipTap utilities."""
from __future__ import annotations



from app.utils.tiptap import (
    BlockInfo,
    STRUCTURAL_BLOCK_TYPES,
    ensure_block_uids,
    extract_plain_text,
    find_concept_mentions,
    walk_structural_blocks,
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


def test_walk_structural_blocks_yields_block_info() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"blockUid": "h1", "level": 1},
                "content": [{"type": "text", "text": "Variables"}],
            },
            {
                "type": "paragraph",
                "attrs": {"blockUid": "p1"},
                "content": [{"type": "text", "text": "Variables hold values."}],
            },
        ],
    }
    blocks = list(walk_structural_blocks(doc))
    assert blocks == [
        BlockInfo(block_uid="h1", kind="heading", text="Variables", parent_uid=None, depth=0),
        BlockInfo(block_uid="p1", kind="paragraph", text="Variables hold values.", parent_uid=None, depth=0),
    ]


def test_walk_structural_blocks_records_list_parents() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "bulletList",
            "attrs": {"blockUid": "ul1"},
            "content": [
                {"type": "listItem", "attrs": {"blockUid": "li1"},
                 "content": [{"type": "paragraph", "attrs": {"blockUid": "p1"},
                              "content": [{"type": "text", "text": "apples"}]}]},
                {"type": "listItem", "attrs": {"blockUid": "li2"},
                 "content": [{"type": "paragraph", "attrs": {"blockUid": "p2"},
                              "content": [{"type": "text", "text": "oranges"}]}]},
            ],
        }],
    }
    blocks = list(walk_structural_blocks(doc))
    by_uid = {b.block_uid: b for b in blocks}
    assert by_uid["li1"].parent_uid == "ul1"
    assert by_uid["li2"].parent_uid == "ul1"
    assert by_uid["p1"].parent_uid == "li1"
    assert by_uid["p2"].parent_uid == "li2"


def test_walk_structural_blocks_skips_text_leaves() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "ignored as a yielded block"}],
        }],
    }
    kinds = [b.kind for b in walk_structural_blocks(doc)]
    assert kinds == ["paragraph"]


def test_structural_block_types_includes_listitem() -> None:
    assert "listItem" in STRUCTURAL_BLOCK_TYPES
    assert "paragraph" in STRUCTURAL_BLOCK_TYPES
    assert "text" not in STRUCTURAL_BLOCK_TYPES


def test_find_concept_mentions_word_boundary() -> None:
    found = find_concept_mentions("AI is the future. Again, AI wins.", ["AI", "JS"])
    assert found == {"AI"}


def test_find_concept_mentions_does_not_match_substring() -> None:
    found = find_concept_mentions("Again I tried adjustments", ["AI", "JS"])
    assert found == set()


def test_find_concept_mentions_is_case_insensitive() -> None:
    found = find_concept_mentions("JavaScript is great", ["javascript"])
    assert found == {"javascript"}


def test_find_concept_mentions_handles_regex_special_chars() -> None:
    # Concepts containing regex metacharacters must not break the matcher.
    found = find_concept_mentions("we use C++ for performance", ["C++"])
    assert found == {"C++"}
