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


def _list_item_groups(doc: dict) -> Iterator[list[BlockInfo]]:
    """Yield groups of sibling list items (children of the same list)."""
    for node in doc.get("content", []) or []:
        if node.get("type") in {"bulletList", "orderedList"}:
            group: list[BlockInfo] = []
            for li in node.get("content", []) or []:
                li_id = (li.get("attrs") or {}).get("id") or ""
                if not li_id:
                    continue
                group.append(BlockInfo(
                    block_id=li_id,
                    kind="listItem",
                    text=_text_of(li).strip(),
                    parent_id=(node.get("attrs") or {}).get("id"),
                    depth=1,
                ))
            if group:
                yield group
        # Recurse into other containers to find nested lists.
        for child in node.get("content", []) or []:
            if isinstance(child, dict) and child.get("content"):
                yield from _list_item_groups(child)


def _blockref_targets(doc: dict) -> Iterator[tuple[str, str]]:
    """Yield (source_block_text, refTargetText) for every blockRef in the doc."""
    for node in doc.get("content", []) or []:
        node_text = _text_of(node)
        for sub in (node.get("content", []) or []):
            if isinstance(sub, dict) and sub.get("type") == "blockRef":
                target = (sub.get("attrs") or {}).get("refTargetText", "")
                if target:
                    yield (node_text, target)
        # Recurse
        if node.get("content"):
            yield from _blockref_targets(node)


def _bold_prefix_concepts(doc: dict, concepts: list[str]) -> set[str]:
    """Concepts that appear as a bold span at the start of a paragraph."""
    out: set[str] = set()
    for node in doc.get("content", []) or []:
        if node.get("type") != "paragraph":
            if node.get("content"):
                out |= _bold_prefix_concepts(node, concepts)
            continue
        children = node.get("content", []) or []
        if not children:
            continue
        first = children[0]
        if first.get("type") != "text":
            continue
        marks = first.get("marks") or []
        if not any(m.get("type") == "bold" for m in marks):
            continue
        bold_text = first.get("text", "").strip().lower()
        for c in concepts:
            if c.lower() == bold_text:
                out.add(c)
    return out


def derive_relations(
    document_json: dict,
    *,
    concepts: list[str],
) -> list[StructureEdge]:
    """Walk TipTap blocks and emit typed structure edges between concepts.

    MENTIONED_TOGETHER: every pair of concepts in the same block (both directions).
    SUBTOPIC_OF: concept in a non-heading block following a heading that names another concept.
    SIBLING_OF: concepts in adjacent list items under the same parent list (both directions).
    REFERENCES: concept in a block containing a blockRef, pointing to refTargetText concepts.
    DEFINED_BY: concept appearing as a bold span at paragraph start; target="" sentinel.
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

    # SIBLING_OF: concepts in adjacent list items under the same list.
    for group in _list_item_groups(document_json):
        for i, a_block in enumerate(group):
            a_concepts = _concepts_in_text(a_block.text, concepts)
            for b_block in group[i + 1:]:
                b_concepts = _concepts_in_text(b_block.text, concepts)
                for a in a_concepts:
                    for b in b_concepts:
                        if a != b:
                            edges.add(StructureEdge(a, b, "SIBLING_OF"))
                            edges.add(StructureEdge(b, a, "SIBLING_OF"))

    # REFERENCES: concept appearing in a block that contains a blockRef.
    for source_text, target_text in _blockref_targets(document_json):
        source_concepts = _concepts_in_text(source_text, concepts)
        target_concepts = _concepts_in_text(target_text, concepts)
        for s in source_concepts:
            for t in target_concepts:
                if s != t:
                    edges.add(StructureEdge(s, t, "REFERENCES"))

    # DEFINED_BY: concept appears as a bold span at start of a paragraph.
    # source = concept, target = "" sentinel (note-level context, not concept→concept).
    for c in _bold_prefix_concepts(document_json, concepts):
        edges.add(StructureEdge(c, "", "DEFINED_BY"))

    return sorted(edges, key=lambda e: (e.relation, e.source, e.target))
