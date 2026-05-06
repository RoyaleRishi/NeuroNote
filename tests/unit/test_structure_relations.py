from app.nlp.structure_relations import _walk_blocks, BlockInfo


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
