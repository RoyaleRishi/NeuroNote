"""Integration test: derive_relations against real production document shape.

These fixtures were pseudonymised from real notes in the running
database. Their *structure* (block UIDs, nesting, list / heading
arrangement) matches what the frontend produces; their *content* has
been replaced with deterministic placeholders.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.nlp.structure_relations import derive_relations
from app.utils.tiptap import walk_structural_blocks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "notes"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _all_concepts(doc: dict) -> list[str]:
    """Collect every distinct text token (>=4 chars) appearing in the doc."""
    seen: set[str] = set()
    for block in walk_structural_blocks(doc):
        for token in block.text.split():
            token = token.strip(",.;:()[]{}!?")
            if len(token) >= 4:
                seen.add(token)
    return sorted(seen)


@pytest.mark.parametrize("fixture", [
    "syntax_pseudonymised.json",
    "goals_pseudonymised.json",
])
def test_walk_structural_blocks_yields_block_uids(fixture: str) -> None:
    doc = _load(fixture)
    blocks = list(walk_structural_blocks(doc))
    assert blocks, f"{fixture} produced zero structural blocks"
    missing_uid = [b for b in blocks if not b.block_uid]
    assert not missing_uid, (
        f"{fixture} has {len(missing_uid)} blocks without blockUid — "
        "ensure_block_uids contract violated upstream"
    )


@pytest.mark.parametrize("fixture", [
    "syntax_pseudonymised.json",
    "goals_pseudonymised.json",
])
def test_derive_relations_emits_edges_against_real_shape(fixture: str) -> None:
    doc = _load(fixture)
    concepts = _all_concepts(doc)
    result = derive_relations(doc, concepts=concepts)

    assert len(result.edges) > 0, (
        f"{fixture}: derive_relations produced 0 edges — likely a "
        "contract drift between attrs.blockUid stamping and "
        "structure_relations consumer"
    )
    for edge in result.edges:
        assert edge.source != "" or edge.relation == "DEFINED_BY", (
            f"empty source on non-DEFINED_BY edge: {edge}"
        )
        assert edge.target is not None
