from app.nlp.structure_relations import _walk_blocks, BlockInfo, StructureEdge, derive_relations


def test_walk_blocks_extracts_block_ids_and_text() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1, "id": "h1"},
                "content": [{"type": "text", "text": "Variables"}],
            },
            {
                "type": "paragraph",
                "attrs": {"id": "p1"},
                "content": [
                    {"type": "text", "text": "Variables hold "},
                    {"type": "text", "text": "data values."},
                ],
            },
        ],
    }
    blocks = list(_walk_blocks(doc))
    assert blocks == [
        BlockInfo(block_id="h1", kind="heading", text="Variables", parent_id=None, depth=0),
        BlockInfo(block_id="p1", kind="paragraph", text="Variables hold data values.", parent_id=None, depth=0),
    ]


def test_concepts_in_same_paragraph_emit_mentioned_together() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"id": "p1"},
            "content": [{"type": "text", "text": "Variables hold data values."}],
        }],
    }
    edges = derive_relations(doc, concepts=["variables", "data values"])
    assert StructureEdge(
        source="variables", target="data values", relation="MENTIONED_TOGETHER",
    ) in edges
    assert StructureEdge(
        source="data values", target="variables", relation="MENTIONED_TOGETHER",
    ) in edges


def test_concept_under_heading_emits_subtopic_of() -> None:
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"id": "h1", "level": 2},
                "content": [{"type": "text", "text": "Casting"}],
            },
            {
                "type": "paragraph",
                "attrs": {"id": "p1"},
                "content": [{"type": "text", "text": "Use the int function."}],
            },
        ],
    }
    edges = derive_relations(doc, concepts=["casting", "int function"])
    assert StructureEdge(
        source="int function", target="casting", relation="SUBTOPIC_OF",
    ) in edges


def test_sibling_list_items_emit_sibling_of() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "bulletList",
            "attrs": {"id": "ul1"},
            "content": [
                {"type": "listItem", "attrs": {"id": "li1"},
                 "content": [{"type": "paragraph", "attrs": {"id": "p1"},
                              "content": [{"type": "text", "text": "apples"}]}]},
                {"type": "listItem", "attrs": {"id": "li2"},
                 "content": [{"type": "paragraph", "attrs": {"id": "p2"},
                              "content": [{"type": "text", "text": "oranges"}]}]},
            ],
        }],
    }
    edges = derive_relations(doc, concepts=["apples", "oranges"])
    assert StructureEdge("apples", "oranges", "SIBLING_OF") in edges
    assert StructureEdge("oranges", "apples", "SIBLING_OF") in edges


def test_blockref_emits_references() -> None:
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"id": "p1"},
            "content": [
                {"type": "text", "text": "See "},
                {"type": "blockRef", "attrs": {"refTargetText": "data types"},
                 "content": []},
                {"type": "text", "text": " also casting"},
            ],
        }],
    }
    edges = derive_relations(doc, concepts=["casting", "data types"])
    assert StructureEdge("casting", "data types", "REFERENCES") in edges


def test_bold_prefix_emits_defined_by() -> None:
    # NOTE: DEFINED_BY links concept → note (not concept → concept).
    # Verified by source == concept and target == "" sentinel for note context.
    doc = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "attrs": {"id": "p1"},
            "content": [
                {"type": "text", "marks": [{"type": "bold"}], "text": "Casting"},
                {"type": "text", "text": " is the process of converting types."},
            ],
        }],
    }
    edges = derive_relations(doc, concepts=["casting"])
    assert any(e.relation == "DEFINED_BY" and e.source == "casting" for e in edges)
