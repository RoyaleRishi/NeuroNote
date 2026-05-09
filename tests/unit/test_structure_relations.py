"""Unit tests for derive_relations.

Fixtures use ``attrs.blockUid`` to match the storage contract — the
attribute the production stamper writes and the consumer now reads.
"""
from __future__ import annotations

from app.nlp.structure_relations import derive_relations
from app.nlp.types import RelationDerivation, StructureEdge


def _edges(result: RelationDerivation) -> list[StructureEdge]:
    return result.edges


def test_concepts_in_same_paragraph_emit_mentioned_together() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "Variables hold data values."}],
        }],
    }
    result = derive_relations(doc, concepts=["variables", "data values"])
    assert StructureEdge("variables", "data values", "MENTIONED_TOGETHER") in _edges(result)
    assert StructureEdge("data values", "variables", "MENTIONED_TOGETHER") in _edges(result)


def test_concept_under_heading_emits_subtopic_of() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"blockUid": "h1", "level": 2},
                "content": [{"type": "text", "text": "Casting"}],
            },
            {
                "type": "paragraph",
                "attrs": {"blockUid": "p1"},
                "content": [{"type": "text", "text": "Use the int function."}],
            },
        ],
    }
    result = derive_relations(doc, concepts=["casting", "int function"])
    assert StructureEdge("int function", "casting", "SUBTOPIC_OF") in _edges(result)


def test_sibling_list_items_emit_sibling_of() -> None:
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
    result = derive_relations(doc, concepts=["apples", "oranges"])
    assert StructureEdge("apples", "oranges", "SIBLING_OF") in _edges(result)
    assert StructureEdge("oranges", "apples", "SIBLING_OF") in _edges(result)


def test_blockref_emits_references() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [
                {"type": "text", "text": "See "},
                {"type": "blockRef", "attrs": {"blockUid": "br1", "refTargetText": "data types"},
                 "content": []},
                {"type": "text", "text": " also casting"},
            ],
        }],
    }
    result = derive_relations(doc, concepts=["casting", "data types"])
    assert StructureEdge("casting", "data types", "REFERENCES") in _edges(result)


def test_bold_prefix_emits_defined_by() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [
                {"type": "text", "marks": [{"type": "bold"}], "text": "Casting"},
                {"type": "text", "text": " is the process of converting types."},
            ],
        }],
    }
    result = derive_relations(doc, concepts=["casting"])
    assert any(e.relation == "DEFINED_BY" and e.source == "casting" for e in _edges(result))


def test_substring_match_does_not_produce_false_positives() -> None:
    """Pre-fix this would emit MENTIONED_TOGETHER from substring matches."""
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "Again I tried adjustments"}],
        }],
    }
    result = derive_relations(doc, concepts=["AI", "JS"])
    assert _edges(result) == []


def test_distinct_blocks_with_concepts_counts_unique_blocks() -> None:
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "attrs": {"blockUid": "p1"},
             "content": [{"type": "text", "text": "casting and variables"}]},
            {"type": "paragraph", "attrs": {"blockUid": "p2"},
             "content": [{"type": "text", "text": "more on variables"}]},
            {"type": "paragraph", "attrs": {"blockUid": "p3"},
             "content": [{"type": "text", "text": "no concept here"}]},
        ],
    }
    result = derive_relations(doc, concepts=["casting", "variables"])
    assert result.distinct_blocks_with_concepts == 2
