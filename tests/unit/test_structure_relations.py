"""Unit tests for derive_relations.

Fixtures use ``attrs.blockUid`` to match the storage contract — the
attribute the production stamper writes and the consumer now reads.
"""
from __future__ import annotations

from app.nlp.structure_relations import derive_relations
from app.nlp.types import ConceptSurface, RelationDerivation, StructureEdge


def _cs(s: str) -> ConceptSurface:
    """Shorthand: surface == canonical (identity case used by most tests)."""
    return ConceptSurface(surface=s, canonical=s)


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
    result = derive_relations(doc, concepts=[_cs("variables"), _cs("data values")])
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
    result = derive_relations(doc, concepts=[_cs("casting"), _cs("int function")])
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
    result = derive_relations(doc, concepts=[_cs("apples"), _cs("oranges")])
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
    result = derive_relations(doc, concepts=[_cs("casting"), _cs("data types")])
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
    result = derive_relations(doc, concepts=[_cs("casting")])
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
    result = derive_relations(doc, concepts=[_cs("AI"), _cs("JS")])
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
    result = derive_relations(doc, concepts=[_cs("casting"), _cs("variables")])
    assert result.distinct_blocks_with_concepts == 2


def test_matches_surface_but_emits_canonical_endpoints() -> None:
    """The bug we fixed: pipeline passed canonicals to derive_relations,
    but the canonical text often doesn't appear verbatim in the document.
    Match on surface, emit on canonical."""
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "Variables hold data values."}],
        }],
    }
    # The extracted surface is "Variables"; the cross-note canonical is "python variables".
    # The matcher must find the word "Variables" (it's in the text) and emit edges
    # keyed by "python variables" (it's not in the text but is the canonical id).
    concepts = [
        ConceptSurface(surface="Variables", canonical="python variables"),
        ConceptSurface(surface="data values", canonical="data values"),
    ]
    result = derive_relations(doc, concepts=concepts)
    assert StructureEdge("python variables", "data values", "MENTIONED_TOGETHER") in result.edges
    assert StructureEdge("data values", "python variables", "MENTIONED_TOGETHER") in result.edges


def test_synonyms_with_shared_canonical_do_not_self_pair() -> None:
    """If two surface forms share the same canonical and both appear in
    one block, they are the same logical concept — no MENTIONED_TOGETHER."""
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"blockUid": "p1"},
            "content": [{"type": "text", "text": "JS and JavaScript are the same."}],
        }],
    }
    concepts = [
        ConceptSurface(surface="JS", canonical="javascript"),
        ConceptSurface(surface="JavaScript", canonical="javascript"),
    ]
    result = derive_relations(doc, concepts=concepts)
    # No self-pair MENTIONED_TOGETHER for the same canonical.
    mt = [e for e in result.edges if e.relation == "MENTIONED_TOGETHER"]
    assert mt == []
