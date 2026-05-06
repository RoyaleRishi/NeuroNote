"""Derive typed relations from TipTap document structure.

Reads the TipTap JSON tree and emits typed edges between concept pairs
based on structural co-location:
  - MENTIONED_TOGETHER: same block
  - SUBTOPIC_OF: concept under a heading mentioning a parent concept
  - SIBLING_OF: adjacent list items
  - REFERENCES: blockRef target
  - DEFINED_BY: bold-prefixed paragraph (definition pattern)

No LLM. No statistical inference. Pure tree walking + string matching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

EdgeRelation = Literal["MENTIONED_TOGETHER", "SUBTOPIC_OF", "SIBLING_OF", "REFERENCES", "DEFINED_BY"]

BlockKind = Literal[
    "heading", "paragraph", "listItem", "bulletList", "orderedList",
    "codeBlock", "blockquote", "blockRef", "other",
]


@dataclass(frozen=True, slots=True)
class BlockInfo:
    block_id: str
    kind: BlockKind
    text: str
    parent_id: str | None
    depth: int


def _kind_of(node: dict) -> BlockKind:
    t = node.get("type", "")
    if t in {"heading", "paragraph", "listItem", "bulletList", "orderedList",
             "codeBlock", "blockquote", "blockRef"}:
        return t  # type: ignore[return-value]
    return "other"


def _text_of(node: dict) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    parts: list[str] = []
    for child in node.get("content", []) or []:
        parts.append(_text_of(child))
    return "".join(parts)


def _walk_blocks(doc: dict, parent_id: str | None = None, depth: int = 0) -> Iterator[BlockInfo]:
    for node in doc.get("content", []) or []:
        kind = _kind_of(node)
        if kind == "other":
            continue
        block_id = (node.get("attrs") or {}).get("id") or ""
        if not block_id:
            continue
        # Container blocks (lists) yield their children but not themselves.
        if kind in {"bulletList", "orderedList"}:
            yield from _walk_blocks(node, parent_id=block_id, depth=depth + 1)
            continue
        text = _text_of(node).strip()
        yield BlockInfo(
            block_id=block_id,
            kind=kind,
            text=text,
            parent_id=parent_id,
            depth=depth,
        )
        # Recurse into list items so nested content is captured.
        if kind == "listItem":
            yield from _walk_blocks(node, parent_id=block_id, depth=depth + 1)


@dataclass(frozen=True, slots=True)
class StructureEdge:
    source: str
    target: str
    relation: EdgeRelation


def _concepts_in_text(text: str, concepts: list[str]) -> set[str]:
    """Return the subset of `concepts` that appear (case-insensitive substring) in `text`."""
    hay = text.lower()
    return {c for c in concepts if c.lower() in hay}


def derive_relations(
    document_json: dict,
    *,
    concepts: list[str],
) -> list[StructureEdge]:
    """Walk TipTap blocks and emit MENTIONED_TOGETHER and SUBTOPIC_OF edges.

    MENTIONED_TOGETHER: emitted for every pair of concepts in the same block
    (both directions for query symmetry).

    SUBTOPIC_OF: emitted when a concept appears in a non-heading block that
    immediately follows a heading block mentioning a different concept.
    """
    if not concepts:
        return []
    blocks = list(_walk_blocks(document_json))
    edges: set[StructureEdge] = set()

    current_heading_concepts: set[str] = set()
    for block in blocks:
        present = _concepts_in_text(block.text, concepts)
        # Emit MENTIONED_TOGETHER for every pair in this block (both directions).
        listed = list(present)
        for i, a in enumerate(listed):
            for b in listed[i + 1:]:
                edges.add(StructureEdge(a, b, "MENTIONED_TOGETHER"))
                edges.add(StructureEdge(b, a, "MENTIONED_TOGETHER"))
        if block.kind == "heading":
            current_heading_concepts = present
        else:
            for child in present:
                for parent in current_heading_concepts:
                    if child != parent:
                        edges.add(StructureEdge(child, parent, "SUBTOPIC_OF"))

    return sorted(edges, key=lambda e: (e.relation, e.source, e.target))
