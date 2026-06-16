from __future__ import annotations

from pathlib import Path

from shared.contracts.python.v1.graph import LocalGraphResponse

ROOT = Path(__file__).resolve().parents[2]


def test_local_graph_response_contract_shape() -> None:
    result = LocalGraphResponse(
        nodes=[
            {
                "id": "note-1",
                "type": "note",
                "label": "Note 1",
                "confidence": None,
                "source_note_id": "note-1",
                "metadata": {},
            }
        ],
        edges=[
            {
                "id": "edge-1",
                "source": "note-1",
                "target": "note-2",
                "type": "LINKS_TO",
                "confidence": 1.0,
                "source_note_id": "note-1",
            }
        ],
        meta={
            "root_note_id": "note-1",
            "applied_filters": {
                "max_hops": 1,
                "limit_nodes": 80,
                "node_salience_threshold": 0.5,
                "relationship_confidence_threshold": 0.5,
                "include_types": ["note", "entity", "relation"],
            },
            "truncated": False,
        },
    )
    assert result.meta.root_note_id == "note-1"


def test_ts_graph_contract_contains_required_fields() -> None:
    ts_contract = (ROOT / "shared/contracts/ts/v1/graph.ts").read_text()
    required_tokens = [
        "interface LocalGraphResponse",
        "interface LocalGraphNode",
        "interface LocalGraphEdge",
        "interface LocalGraphFilters",
        "root_note_id: string",
        "include_types: string[]",
        "truncated: boolean",
    ]

    for token in required_tokens:
        assert token in ts_contract, f"Missing token in TS graph contract: {token}"
